import { useState } from "react";

import { useDataSource } from "../data/context";
import type { GoogleReturnTo } from "../data/source";
import type { ConnectionStatus } from "../domain/account";
import { leaveApp } from "../lib/google";
import { buttonClass } from "./styles";
import { Icon } from "./ui";

// "Connect Google": the api hands back google-gateway's URL with a one-time ticket, and the
// browser goes there. The consent and the tokens stay with the gateway (invariant 1, T16).
export function GoogleConnectButton({ status, returnTo }: { status: ConnectionStatus; returnTo: GoogleReturnTo }) {
  const source = useDataSource();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function connect() {
    setBusy(true);
    setFailed(false);
    const url = await source.connectGoogle(returnTo);
    if (url) {
      leaveApp.to(url);
    } else {
      setBusy(false);
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button type="button" disabled={busy} onClick={() => void connect()} className={status === "connected" ? buttonClass.secondary : buttonClass.primary}>
        <Icon name="mail" className="size-[18px]" />
        {status === "connected" ? "חיבור מחדש ל-Google" : "חיבור ל-Google"}
      </button>
      {failed && (
        <p role="alert" className="text-sm text-danger">
          לא הצלחנו להתחיל את החיבור. נסו שוב.
        </p>
      )}
    </div>
  );
}

/** The scopes the gateway asks for, and why (ADR-010, invariant 6). */
export function GoogleScopes() {
  return (
    <ul className="flex flex-col gap-1.5 text-sm text-ink-soft">
      <li>קריאת מיילים, כדי לזהות בקשות לפגישה. בלי הרשאה למחוק או לשנות מיילים.</li>
      <li>שליחת מיילים, רק תשובות שאישרת, באותה שיחה.</li>
      <li>אירועים ביומנים שלך, כדי לבדוק מתי אתה פנוי ולקבוע פגישות עם Meet.</li>
    </ul>
  );
}
