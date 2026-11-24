import { useEffect, useState } from "react";
import { Link } from "react-router";

import { buttonClass } from "../components/styles";
import { Icon } from "../components/ui";
import { useDataSource } from "../data/context";
import { leaveApp } from "../lib/google";
import { PageTitle } from "./PageTitle";

/**
 * The invite token comes in the link's fragment (`/invite#<token>`). Browsers never send the
 * fragment to a server, so it stays out of every log (T22). It is read once into state and
 * then removed from the address bar, so it does not stay in the history either.
 */
function readToken(): string {
  return window.location.hash.slice(1);
}

function forgetToken() {
  window.history.replaceState(window.history.state, "", window.location.pathname);
}

type State = { kind: "checking" } | { kind: "missing" } | { kind: "ready"; token: string; emailHint: string };

// /invite — a single-use, expiring invite bound to one email address (UC-A1, T14).
export function InvitePage() {
  const source = useDataSource();
  const [token] = useState(readToken);
  const [state, setState] = useState<State>(token ? { kind: "checking" } : { kind: "missing" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    forgetToken();
    void source.checkInvite(token).then(
      (found) => setState(found ? { kind: "ready", token, emailHint: found.emailHint } : { kind: "missing" }),
      () => setState({ kind: "missing" }),
    );
  }, [source, token]);

  async function join(token: string) {
    setBusy(true);
    const url = await source.startInviteLogin(token);
    if (url) leaveApp.to(url);
    else setState({ kind: "missing" });
  }

  return (
    <section className="flex flex-col gap-5 pt-10">
      <span className="flex size-14 items-center justify-center rounded-[1.125rem] bg-accent text-white">
        <Icon name="calendar" className="size-7" />
      </span>
      <PageTitle>הזמנה</PageTitle>

      {state.kind === "checking" && <p className="text-muted">בודק את ההזמנה…</p>}

      {state.kind === "missing" && (
        <>
          <p className="text-ink-soft">ההזמנה לא נמצאה, פגה או כבר נוצלה.</p>
          <p className="text-sm text-muted">כל הזמנה מיועדת לכתובת מייל אחת, לפעם אחת. אפשר לבקש ממי שהזמין אותך קישור חדש.</p>
          <Link to="/login" className={buttonClass.link}>
            למסך ההתחברות
          </Link>
        </>
      )}

      {state.kind === "ready" && (
        <>
          <p className="text-[1.0625rem] leading-relaxed text-ink-soft">
            הוזמנת להשתמש בסוכן הפגישות. ההזמנה מיועדת לחשבון Google <bdi className="font-semibold text-ink">{state.emailHint}</bdi>.
          </p>
          <ul className="flex flex-col gap-2 text-sm text-ink-soft">
            <li>1. התחברות עם Google, עם אותו חשבון.</li>
            <li>2. חיבור המייל והיומן, ואימות מספר הווטסאפ.</li>
            <li>3. הסוכן מתחיל לעבוד, ושום דבר לא נשלח בלי האישור שלך.</li>
          </ul>
          <button type="button" disabled={busy} onClick={() => void join(state.token)} className={`${buttonClass.primary} min-h-14`}>
            התחברות עם Google
          </button>
          <p className="text-center text-[0.8125rem] text-muted">ההתחברות מבקשת רק את הזהות שלך. גישה למייל מבקשים בשלב הבא, בנפרד.</p>
        </>
      )}
    </section>
  );
}
