import { Outlet } from "react-router";

// Screens before the user is fully set up (login, invite, onboarding): no bottom nav.
export function BareLayout() {
  return (
    <div className="min-h-dvh bg-slate-50 text-slate-900">
      <main className="mx-auto max-w-xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
