// Israeli format: day.month and a 24-hour clock (docs/04-web-app.md, "language and design").
export const USER_TIME_ZONE = "Asia/Jerusalem";

function format(iso: string, timeZone: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("he-IL", { timeZone, hourCycle: "h23", ...options }).format(new Date(iso));
}

export function formatDateTime(iso: string, timeZone: string = USER_TIME_ZONE): string {
  return format(iso, timeZone, {
    weekday: "short",
    day: "numeric",
    month: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(iso: string, timeZone: string = USER_TIME_ZONE): string {
  return format(iso, timeZone, { hour: "2-digit", minute: "2-digit" });
}
