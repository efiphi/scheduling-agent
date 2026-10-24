import type { Slot } from "../domain/actions";
import { formatDateTime, formatTime, USER_TIME_ZONE } from "../lib/time";

// E3: a full date and time, and when the other side is in another zone, both zones.
export function SlotTime({ slot }: { slot: Slot }) {
  const other = slot.counterpartTimeZone;
  return (
    <span>
      <span>
        {formatDateTime(slot.start)}–{formatTime(slot.end)} שעון ישראל
      </span>
      {other && other !== USER_TIME_ZONE && (
        <span className="block text-sm text-slate-600">
          {formatDateTime(slot.start, other)}–{formatTime(slot.end, other)} <bdi>{other}</bdi>
        </span>
      )}
    </span>
  );
}
