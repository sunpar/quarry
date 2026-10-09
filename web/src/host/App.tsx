import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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
  // A pasted link with a new token must not keep the old one in memory; replaceState never fires this.
  useEffect(() => {
    const onHashChange = () => {
      if (readToken(window.location.hash) !== token) window.location.reload();
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [token]);
  if (token === null || client === null) return <TokenMissing />;
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <SessionPage token={token} />
      </ApiProvider>
    </QueryClientProvider>
  );
}
