import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { createRoutes } from "../app/routes";
import type { DataSource } from "../data/source";

export function renderApp(path: string, source: DataSource) {
  const router = createMemoryRouter(createRoutes(source), { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}
