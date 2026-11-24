// After "Connect Google", google-gateway sends the browser back with ?google=<outcome>
// (services/google_gateway/src/google_gateway/connection.py, Outcome). Only known codes
// become a message: whatever else is in the address bar is never shown (T19).

const messages: Record<string, { tone: "ok" | "warn" | "danger"; text: string }> = {
  connected: { tone: "ok", text: "חשבון Google חובר. הסוכן מתחיל לקרוא מיילים בדקה הקרובה." },
  declined: { tone: "warn", text: "החיבור בוטל. לא נשמר דבר." },
  invalid_state: { tone: "danger", text: "הקישור לחיבור פג או כבר נוצל. נסו שוב." },
  exchange_failed: { tone: "danger", text: "Google לא אישר את החיבור. נסו שוב." },
  wrong_scopes: { tone: "danger", text: "כדי שהסוכן יעבוד צריך לאשר את כל ההרשאות. נסו שוב וסמנו את כולן." },
  wrong_account: { tone: "danger", text: "זה לא החשבון שאיתו נכנסת. בחרו ב-Google את אותו חשבון." },
  no_refresh_token: { tone: "danger", text: "Google לא החזיר הרשאה לטווח ארוך. נסו שוב." },
  unknown_user: { tone: "danger", text: "משהו השתבש. נסו שוב." },
};

export function googleOutcome(search: string) {
  const code = new URLSearchParams(search).get("google");
  return code ? messages[code] : undefined;
}

/** A full-page navigation to Google or to google-gateway. Its own function, so tests can stub it. */
export const leaveApp = {
  to(url: string) {
    window.location.assign(url);
  },
};
