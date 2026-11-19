import { Outlet } from "react-router";

// Screens before the user is fully set up (login, invite, onboarding): no bottom nav.
export function BareLayout() {
  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <main className="mx-auto max-w-xl px-6 py-10">
        <Outlet />
      </main>
    </div>
  );
}
