import type { JsonObject } from "@/shared/json";

interface Card {
  last: JsonObject;
  restore: (state: JsonObject) => void;
}

export function sharedKeys(state: JsonObject): JsonObject {
  return Object.fromEntries(
    Object.entries(state).filter(([key]) => key.startsWith("shared:")),
  );
}

/** Fans `shared:` view-state keys out across the cards of one canvas. */
export class SharedStateHub {
  private readonly cards = new Map<string, Card>();

  register(
    cardId: string,
    initial: JsonObject,
    restore: (state: JsonObject) => void,
  ): () => void {
    this.cards.set(cardId, { last: initial, restore });
    return () => {
      this.cards.delete(cardId);
    };
  }

  report(cardId: string, state: JsonObject): void {
    const card = this.cards.get(cardId);
    if (card !== undefined) card.last = state;
    const shared = sharedKeys(state);
    if (Object.keys(shared).length === 0) return;
    for (const [id, other] of this.cards) {
      if (id === cardId) continue;
      other.last = { ...other.last, ...shared };
      other.restore(other.last);
    }
  }
}
