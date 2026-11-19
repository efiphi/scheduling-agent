import { NavLink } from "react-router";

import { Icon, type IconName } from "../components/ui";

const items: readonly { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "תור", icon: "queue" },
  { to: "/history", label: "היסטוריה", icon: "history" },
  { to: "/contacts", label: "אנשי קשר", icon: "contacts" },
  { to: "/settings", label: "הגדרות", icon: "settings" },
];

// Mobile-first: the four main screens from docs/04-web-app.md, always reachable by thumb.
export function BottomNav() {
  return (
    <nav
      aria-label="ניווט ראשי"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <ul className="mx-auto grid max-w-xl grid-cols-4 gap-1 px-3 pt-2 pb-3">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-xs ${
                  isActive ? "font-semibold text-accent" : "text-muted hover:text-ink"
                }`
              }
            >
              <Icon name={item.icon} className="size-[22px]" />
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
