import { createContext, useContext } from "react";

import { notConnectedSource, type DataSource } from "./source";

// Loaders get the data source as a parameter; components that need it directly
// (for real-time subscriptions) read it from this context.
export const DataSourceContext = createContext<DataSource>(notConnectedSource);

export function useDataSource(): DataSource {
  return useContext(DataSourceContext);
}
