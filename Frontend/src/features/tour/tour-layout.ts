export interface Box { top: number; left: number; width: number; height: number }
export interface Placement { x: number; y: number; mode: "below" | "above" | "right" | "left" | "docked" | "center" }

interface Options { gap?: number; margin?: number; bottomInset?: number }

/**
 * Pure placement for the tour card. Tries below, above, right, left of the target without
 * overlapping it. When the target is too tall for any of those (a whole form or a product grid),
 * the card docks: bottom-right on desktop, bottom-centre on phones (clear of the bottom nav).
 * With no target it centres.
 */
export function placeCard(
  target: Box | null,
  card: { w: number; h: number },
  view: { w: number; h: number },
  { gap = 14, margin = 12, bottomInset = 12 }: Options = {},
): Placement {
  const maxX = Math.max(view.w - card.w - margin, margin);
  const maxY = Math.max(view.h - card.h - bottomInset, margin);
  const clampX = (x: number) => Math.min(Math.max(x, margin), maxX);
  const clampY = (y: number) => Math.min(Math.max(y, margin), maxY);

  if (!target) return { x: clampX((view.w - card.w) / 2), y: clampY((view.h - card.h) / 2 - 24), mode: "center" };

  const tall = target.height > view.h * 0.6;
  if (!tall) {
    const cx = clampX(target.left + target.width / 2 - card.w / 2);
    const below = target.top + target.height + gap;
    if (below <= maxY) return { x: cx, y: below, mode: "below" };
    const above = target.top - gap - card.h;
    if (above >= margin) return { x: cx, y: above, mode: "above" };
    const cy = clampY(target.top + target.height / 2 - card.h / 2);
    const right = target.left + target.width + gap;
    if (right <= view.w - card.w - margin) return { x: right, y: cy, mode: "right" };
    const left = target.left - gap - card.w;
    if (left >= margin) return { x: left, y: cy, mode: "left" };
  }
  const desktop = view.w >= 768;
  return { x: desktop ? Math.max(view.w - card.w - 24, margin) : clampX((view.w - card.w) / 2), y: maxY, mode: "docked" };
}
