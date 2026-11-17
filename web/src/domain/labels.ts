import type { HistoryEntry } from "./account";
import { actionKindLabel, type Channel } from "./actions";

export const channelLabel: Record<Channel, string> = {
  email: "מייל",
  whatsapp: "ווטסאפ",
  web: "אפליקציה",
};

export function historyKindLabel(kind: HistoryEntry["kind"]): string {
  if (kind === "settings_change") return "שינוי הגדרות";
  if (kind === "security_event") return "אירוע אבטחה";
  return actionKindLabel[kind];
}
