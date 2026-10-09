import { describe, expect, it } from "vitest";
import { cardsToLayout, layoutToCards } from "./CanvasPage";

describe("canvas layout mapping", () => {
  it("round-trips cards through the grid layout", () => {
    const cards = [
      { view: "a", x: 0, y: 0, w: 6, h: 8 },
      { view: "b", x: 6, y: 0, w: 6, h: 4 },
    ];
    const layout = cardsToLayout(cards);
    expect(layout[0]).toMatchObject({
      i: "a",
      x: 0,
      y: 0,
      w: 6,
      h: 8,
      minW: 3,
      minH: 3,
    });
    expect(layoutToCards(layout)).toEqual(cards);
  });
});
