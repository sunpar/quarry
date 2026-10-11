import type { JsonObject } from "@/shared/json";

export function sharedKeys(state: JsonObject): JsonObject {
  return Object.fromEntries(
    Object.entries(state).filter(([key]) => key.startsWith("shared:")),
  );
}

/**
 * Fans `shared:` view-state keys out across the cards of one canvas. Each card gets only the
 * changed keys and merges them into its own current state, so an edit it has not reported yet
 * survives.
 */
export class SharedStateHub {
  private readonly cards = new Map<string, (shared: JsonObject) => void>();

  register(cardId: string, merge: (shared: JsonObject) => void): () => void {
    this.cards.set(cardId, merge);
    return () => {
      this.cards.delete(cardId);
    };
  }

  report(cardId: string, state: JsonObject): void {
    const shared = sharedKeys(state);
    if (Object.keys(shared).length === 0) return;
    for (const [id, merge] of this.cards) if (id !== cardId) merge(shared);
  }
}
