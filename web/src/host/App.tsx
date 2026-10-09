import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { readToken } from "./api/auth";
import { ApiClient } from "./api/client";
import { ApiProvider } from "./api/context";
import { TokenMissing } from "./components/TokenMissing";
import { SessionPage } from "./containers/SessionPage";

export function App() {
  const [token] = useState(() => readToken(window.location.hash));
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1 } } }),
  );
  const [client] = useState(() =>
    token === null ? null : new ApiClient(token),
  );
  if (client === null) return <TokenMissing />;
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <SessionPage />
      </ApiProvider>
    </QueryClientProvider>
  );
}
