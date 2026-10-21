export function readToken(hash: string): string | null {
  return readParam(hash, "token");
}

export function readSession(hash: string): string | null {
  return readParam(hash, "session");
}

export function sessionHash(token: string, session: string | null): string {
  const params = new URLSearchParams({ token });
  if (session !== null) params.set("session", session);
  return `#${params.toString()}`;
}

function readParam(hash: string, name: string): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get(name);
  return value === null || value === "" ? null : value;
}
