import { Outlet } from "react-router";

import { BottomNav } from "./BottomNav";

export function AppLayout() {
  return (
    <div className="min-h-dvh bg-slate-50 text-slate-900">
      {/* Bottom padding keeps content clear of the fixed bottom nav. */}
      <main className="mx-auto max-w-xl px-4 pt-6 pb-24">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
