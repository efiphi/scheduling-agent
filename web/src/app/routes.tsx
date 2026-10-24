import type { RouteObject } from "react-router";

import { ContactsPage } from "../pages/ContactsPage";
import { HistoryPage } from "../pages/HistoryPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { QueuePage } from "../pages/QueuePage";
import { SettingsPage } from "../pages/SettingsPage";
import { AppLayout } from "./AppLayout";

// Screen map from docs/04-web-app.md. Remaining screens are added in later PRs.
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <QueuePage /> },
      { path: "/history", element: <HistoryPage /> },
      { path: "/contacts", element: <ContactsPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
