export function TokenMissing() {
  return (
    <main className="mx-auto max-w-[560px] px-8 py-16">
      <h1 className="text-xl font-semibold">Open Quarry from its link</h1>
      <p className="mt-3 text-sm text-muted-foreground">
        The address needs the token printed by{" "}
        <code className="font-mono">quarry serve</code>. Copy the full link from
        the terminal, including the part after #.
      </p>
    </main>
  );
}
