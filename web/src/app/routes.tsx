import { Outlet, type RouteObject } from "react-router";

import { DataSourceProvider } from "../data/DataSourceProvider";
import type { DataSource } from "../data/source";
import { ActionDetailsPage } from "../pages/ActionDetailsPage";
import { AdminUsersPage } from "../pages/AdminUsersPage";
import { ContactsPage } from "../pages/ContactsPage";
import { HistoryPage } from "../pages/HistoryPage";
import { InvitePage } from "../pages/InvitePage";
import { LoginPage } from "../pages/LoginPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { QueuePage } from "../pages/QueuePage";
import { SecurityPage } from "../pages/SecurityPage";
import { SettingsPage } from "../pages/SettingsPage";
import { SummaryPage } from "../pages/SummaryPage";
import { AppLayout } from "./AppLayout";
import { BareLayout } from "./BareLayout";

// Screen map from docs/04-web-app.md.
// Routes take the data source as a parameter so tests can pass their own.
export function createRoutes(source: DataSource): RouteObject[] {
  const beforeSetup: RouteObject = {
    element: <BareLayout />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/invite/:token", element: <InvitePage /> },
      { path: "/onboarding", element: <OnboardingPage /> },
    ],
  };

  const app: RouteObject = {
    element: <AppLayout />,
    // The layout loads the account so the status banners show on every screen.
    loader: () => source.getAccount(),
    hydrateFallbackElement: <p className="p-4 text-slate-600">טוען…</p>,
    children: [
      { path: "/", element: <QueuePage />, loader: () => source.listPendingActions() },
      {
        path: "/actions/:id",
        element: <ActionDetailsPage />,
        loader: ({ params }) => source.getAction(params.id ?? ""),
      },
      { path: "/summary", element: <SummaryPage />, loader: () => source.getSummary() },
      { path: "/history", element: <HistoryPage />, loader: () => source.listHistory() },
      { path: "/contacts", element: <ContactsPage />, loader: () => source.listContacts() },
      { path: "/settings", element: <SettingsPage />, loader: () => source.getSettings() },
      { path: "/settings/security", element: <SecurityPage />, loader: () => source.getAccount() },
      { path: "/admin/users", element: <AdminUsersPage />, loader: () => source.listUsers() },
      { path: "*", element: <NotFoundPage /> },
    ],
  };

  return [
    {
      // Components that subscribe to real-time events read the same source from context.
      element: (
        <DataSourceProvider source={source}>
          <Outlet />
        </DataSourceProvider>
      ),
      children: [beforeSetup, app],
    },
  ];
}
