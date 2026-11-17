"""Alerts to the owner's WhatsApp (Layer 5, ADR-022).

    uvicorn api.alert_relay:create_alert_relay_app --factory --port 8003

Alertmanager posts what fires here, and this sends it to the owner on WhatsApp. It runs as
its own pod from the api image, because the api alone holds the Meta token: if the api pod
falls over, alerts still go out.

- **Who may post:** a bearer token shared with Alertmanager, compared in constant time, and a
  NetworkPolicy that lets only the monitoring namespace in.
- **What is sent:** the rule's fixed Hebrew summary and its severity. The text comes from our
  own rules (detections/rules.yml), and is still checked: no links, addresses or long
  numbers, never cut (shared.display). Nothing from an email or a message reaches it.
- **How:** inside Meta's 24-hour window a plain message. Outside it, the approved template,
  which costs money, so only for alerts that fire, not for "resolved".
- **How many:** Alertmanager groups and repeats slowly, and this caps messages per hour on
  top of that (T24), so a storm of alerts cannot run up a bill.
"""

import hmac
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis import Redis

from api.whatsapp import InboxState, WhatsAppSender
from shared import log, metrics, tracing
from shared.display import clean_line, safe_question

logger = logging.getLogger(__name__)

MAX_MESSAGES_PER_HOUR = 10
SEVERITY_HE = {"critical": "קריטי", "warning": "אזהרה"}
FALLBACK_SUMMARY = "התראה ממערכת הניטור"


class Alert(BaseModel):
    """One alert as Alertmanager sends it. Unknown fields are ignored, sizes are bounded."""

    model_config = ConfigDict(extra="ignore")
    status: str = Field(max_length=20)
    labels: dict[str, Annotated[str, Field(max_length=200)]] = Field(max_length=30)
    annotations: dict[str, Annotated[str, Field(max_length=500)]] = Field(
        default_factory=dict, max_length=30
    )


class Notification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alerts: list[Alert] = Field(max_length=100)


def message_for(alert: Alert) -> str:
    """The text of one alert: fixed summary and severity only."""
    summary = safe_question(alert.annotations.get("summary_he")) or FALLBACK_SUMMARY
    severity = SEVERITY_HE.get(alert.labels.get("severity", ""), "התראה")
    if alert.status == "resolved":
        return f"נפתר: {summary}"
    return f"{severity}: {summary}"


@dataclass(frozen=True)
class AlertRelay:
    sender: WhatsAppSender
    state: InboxState
    redis: Redis
    owner_id: UUID
    owner_number: str
    template: str | None

    def relay(self, alert: Alert) -> str:
        if not self._under_cap():
            return "capped"
        text = message_for(alert)
        if self.state.window_open(self.owner_id):
            self.sender.send_text(self.owner_number, text)
            return "sent"
        if alert.status != "firing" or self.template is None:
            return "window_closed"
        # The template's {{1}} gets the summary only; Meta adds the approved text around it.
        summary = clean_line(text.split(": ", 1)[-1])
        self.sender.send_template(self.owner_number, self.template, "he", (summary,))
        return "template"

    def _under_cap(self) -> bool:
        key = "alert-relay:sent-this-hour"
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 3600, nx=True)
        count, _ = pipe.execute()
        return int(count) <= MAX_MESSAGES_PER_HOUR


def create_alert_relay_app(
    relay: AlertRelay | None = None, token: SecretStr | None = None
) -> FastAPI:
    if relay is None or token is None:
        log.configure("alert-relay")
        tracing.configure("alert-relay")
        metrics.configure("alert-relay")
        relay, token = _from_env()
    app = FastAPI(title="alert relay", docs_url=None, redoc_url=None, openapi_url=None)
    expected = f"Bearer {token.get_secret_value()}".encode()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/alerts")
    def alerts(
        notification: Notification, authorization: Annotated[str, Header()] = ""
    ) -> dict[str, Any]:
        if not hmac.compare_digest(authorization.encode(), expected):
            raise HTTPException(status_code=401, detail="unauthorized")
        outcomes = [relay.relay(alert) for alert in notification.alerts]
        for outcome in outcomes:
            metrics.ALERTS_RELAYED.add(1, {"outcome": outcome})
        # Alert names only: they are ours, and say what fired.
        names = sorted({a.labels.get("alertname", "?") for a in notification.alerts})
        logger.info("alerts relayed: names=%s outcomes=%s", ",".join(names), ",".join(outcomes))
        return {"outcomes": outcomes}

    return app


def _from_env() -> tuple[AlertRelay, SecretStr]:
    from api.store import SqlApiStore
    from api.whatsapp import MetaSender
    from api.wiring import api_engine, api_redis

    token = SecretStr(os.environ["ALERT_RELAY_TOKEN"])
    owner_id = UUID(os.environ["ALERT_USER_ID"])
    redis = api_redis()
    number = SqlApiStore(api_engine()).whatsapp_number(owner_id)
    if number is None:
        raise SystemExit("the alert owner has no verified WhatsApp number")
    sender = MetaSender(
        SecretStr(os.environ["WHATSAPP_ACCESS_TOKEN"]), os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    )
    relay = AlertRelay(
        sender=sender,
        state=InboxState(redis),
        redis=redis,
        owner_id=owner_id,
        owner_number=number,
        template=os.environ.get("WHATSAPP_ALERT_TEMPLATE") or None,
    )
    return relay, token
