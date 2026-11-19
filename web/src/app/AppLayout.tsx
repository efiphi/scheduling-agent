import { Outlet, useLoaderData } from "react-router";

import { StatusBanners } from "../components/StatusBanners";
import type { Account } from "../domain/account";
import { BottomNav } from "./BottomNav";

export function AppLayout() {
  const account = useLoaderData<Account | null>();

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <StatusBanners account={account} />
      {/* Bottom padding keeps content clear of the fixed bottom nav. */}
      <main className="mx-auto max-w-xl px-5 pt-7 pb-28">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
