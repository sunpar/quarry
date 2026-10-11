import type { JsonObject } from "@/shared/json";

interface Card {
  shared: JsonObject;
  merge: (shared: JsonObject) => void;
}

export function sharedKeys(state: JsonObject): JsonObject {
  return Object.fromEntries(
    Object.entries(state).filter(([key]) => key.startsWith("shared:")),
  );
}

/**
 * Fans `shared:` view-state keys out across the cards of one canvas. A report sends only the
 * keys its card changed, and each other card merges them into its own current state, so an
 * edit another card has not reported yet survives.
 */
export class SharedStateHub {
  private readonly cards = new Map<string, Card>();

  register(
    cardId: string,
    initial: JsonObject,
    merge: (shared: JsonObject) => void,
  ): () => void {
    this.cards.set(cardId, { shared: sharedKeys(initial), merge });
    return () => {
      this.cards.delete(cardId);
    };
  }

  report(cardId: string, state: JsonObject): void {
    const card = this.cards.get(cardId);
    const shared = sharedKeys(state);
    const changed = Object.fromEntries(
      Object.entries(shared).filter(
        ([key, value]) =>
          JSON.stringify(card?.shared[key]) !== JSON.stringify(value),
      ),
    );
    if (card !== undefined) card.shared = shared;
    if (Object.keys(changed).length === 0) return;
    for (const [id, other] of this.cards) {
      if (id === cardId) continue;
      other.shared = { ...other.shared, ...changed };
      other.merge(changed);
    }
  }
}
