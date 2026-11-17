import type { ReactNode } from "react";

import { DataSourceContext } from "./context";
import type { DataSource } from "./source";

export function DataSourceProvider({ source, children }: { source: DataSource; children: ReactNode }) {
  return <DataSourceContext.Provider value={source}>{children}</DataSourceContext.Provider>;
}
