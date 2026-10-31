"""Builds the real dependencies from the environment. Tests pass fakes to create_app."""

from uuid import UUID

from redis import Redis

from api.config import ApiConfig
from api.google_login import GoogleIdentityLogin
from api.main import Deps, WhatsAppDeps
from api.sessions import RedisSessionStore
from api.store import SqlApiStore
from api.whatsapp import Inbox, InboxState, MetaSender, Notifier, agent_display_number
from db.engine import make_engine
from shared.streams import APPROVED_ACTIONS, REDIS_SOCKET_TIMEOUT_SECONDS, STREAM_MAX_LENGTH


def deps_from_env() -> Deps:
    config = ApiConfig.from_env()
    redis = Redis(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password.get_secret_value(),
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )
    engine = make_engine(
        "api_service", config.db_password.get_secret_value(), config.db_host, config.db_port
    )
    store = SqlApiStore(engine)
    whatsapp = None
    notifier = None

    def hand_over(user_id: UUID, action_id: UUID) -> None:
        # The same stream web approvals use; the gateway re-checks everything (1.10).
        redis.xadd(
            APPROVED_ACTIONS,
            {"action_id": str(action_id), "user_id": str(user_id)},
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )

    if config.whatsapp_configured:
        assert config.whatsapp_token and config.whatsapp_phone_number_id  # noqa: S101 - checked above
        assert config.whatsapp_app_secret and config.whatsapp_verify_token  # noqa: S101
        state = InboxState(redis)
        sender = MetaSender(config.whatsapp_token, config.whatsapp_phone_number_id)
        inbox = Inbox(store=store, state=state, sender=sender, hand_over=hand_over)
        notifier = Notifier(
            store=store, state=state, inbox=inbox, sender=sender, template=config.whatsapp_template
        )
        whatsapp = WhatsAppDeps(
            inbox=inbox,
            state=state,
            app_secret=config.whatsapp_app_secret,
            verify_token=config.whatsapp_verify_token,
            agent_number=agent_display_number(
                config.whatsapp_token, config.whatsapp_phone_number_id
            ),
        )
    return Deps(
        login=GoogleIdentityLogin(
            config.google_client_id, config.google_client_secret, config.redirect_uri
        ),
        sessions=RedisSessionStore(redis),
        store=store,
        redis=redis,
        web_app_url=config.web_app_url,
        cookie_secure=config.cookie_secure,
        whatsapp=whatsapp,
        notifier=notifier,
    )
