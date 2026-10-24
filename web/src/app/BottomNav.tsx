import { NavLink } from "react-router";

const items = [
  { to: "/", label: "תור" },
  { to: "/history", label: "היסטוריה" },
  { to: "/contacts", label: "אנשי קשר" },
  { to: "/settings", label: "הגדרות" },
] as const;

// Mobile-first: the four main screens from docs/04-web-app.md, always reachable by thumb.
export function BottomNav() {
  return (
    <nav aria-label="ניווט ראשי" className="fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white">
      <ul className="mx-auto flex max-w-xl">
        {items.map((item) => (
          <li key={item.to} className="flex-1">
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `block py-3 text-center text-sm ${isActive ? "font-semibold text-blue-700" : "text-slate-600"}`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
