import { describe, expect, it } from "vitest";
import { placeCard, type Box } from "./tour-layout";

const view = { w: 1280, h: 800 };
const card = { w: 384, h: 220 };
const box = (top: number, left: number, width: number, height: number): Box => ({ top, left, width, height });
const overlaps = (a: Box, x: number, y: number) => x < a.left + a.width && x + card.w > a.left && y < a.top + a.height && y + card.h > a.top;

describe("placeCard", () => {
  it("places the card below a short target when there is room", () => {
    const t = box(100, 400, 300, 90);
    const p = placeCard(t, card, view);
    expect(p.mode).toBe("below");
    expect(p.y).toBeGreaterThan(t.top + t.height);
    expect(overlaps(t, p.x, p.y)).toBe(false);
  });

  it("flips above when the target is near the bottom", () => {
    const t = box(650, 400, 300, 90);
    const p = placeCard(t, card, view);
    expect(p.mode).toBe("above");
    expect(overlaps(t, p.x, p.y)).toBe(false);
  });

  it("uses the side when neither above nor below fits (target fills the height but not the width)", () => {
    const t = box(150, 100, 300, 480); // tall but under 60% of the viewport
    const p = placeCard(t, card, { w: 1280, h: 800 });
    expect(["right", "left"]).toContain(p.mode);
    expect(overlaps(t, p.x, p.y)).toBe(false);
  });

  it("docks bottom-right on desktop for a very tall target instead of floating over its middle", () => {
    const p = placeCard(box(80, 260, 900, 700), card, view);
    expect(p.mode).toBe("docked");
    expect(p.x).toBe(view.w - card.w - 24);
    expect(p.y + card.h).toBeLessThanOrEqual(view.h);
  });

  it("docks bottom-centre on phones, above the bottom nav", () => {
    const phone = { w: 390, h: 800 };
    const p = placeCard(box(80, 16, 358, 700), { w: 366, h: 230 }, phone, { bottomInset: 76 });
    expect(p.mode).toBe("docked");
    expect(p.y + 230).toBeLessThanOrEqual(800 - 76);
    expect(p.x).toBeGreaterThanOrEqual(12);
    expect(p.x + 366).toBeLessThanOrEqual(390 - 12);
  });

  it("keeps the card inside the viewport horizontally when the target hugs an edge", () => {
    const p = placeCard(box(100, 1200, 70, 40), card, view);
    expect(p.x + card.w).toBeLessThanOrEqual(view.w - 12);
    expect(placeCard(box(100, 0, 40, 40), card, view).x).toBeGreaterThanOrEqual(12);
  });

  it("centres when there is no target", () => {
    const p = placeCard(null, card, view);
    expect(p.mode).toBe("center");
    expect(Math.abs(p.x + card.w / 2 - view.w / 2)).toBeLessThan(1);
  });
});
