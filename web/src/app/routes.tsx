import type { RouteObject } from "react-router";

import type { DataSource } from "../data/source";
import { ActionDetailsPage } from "../pages/ActionDetailsPage";
import { ContactsPage } from "../pages/ContactsPage";
import { HistoryPage } from "../pages/HistoryPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { QueuePage } from "../pages/QueuePage";
import { SettingsPage } from "../pages/SettingsPage";
import { AppLayout } from "./AppLayout";

// Screen map from docs/04-web-app.md. Remaining screens are added in later PRs.
// Routes take the data source as a parameter so tests can pass their own.
export function createRoutes(source: DataSource): RouteObject[] {
  return [
    {
      element: <AppLayout />,
      hydrateFallbackElement: <p className="p-4 text-slate-600">טוען…</p>,
      children: [
        { path: "/", element: <QueuePage />, loader: () => source.listPendingActions() },
        {
          path: "/actions/:id",
          element: <ActionDetailsPage />,
          loader: ({ params }) => source.getAction(params.id ?? ""),
        },
        { path: "/history", element: <HistoryPage /> },
        { path: "/contacts", element: <ContactsPage /> },
        { path: "/settings", element: <SettingsPage /> },
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ];
}
