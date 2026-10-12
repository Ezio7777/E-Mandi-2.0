export const formatINR = (n: number, opts: Intl.NumberFormatOptions = {}) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0, ...opts }).format(n);

export const formatPerKg = (n: number) => `₹${n % 1 === 0 ? n : n.toFixed(2)}/kg`;
/** Indian grouping, at most `max` decimals, no trailing zeros: 27.333333333333332 → "27.33", 5400 → "5,400". */
export const formatNumber = (n: number, max = 2) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: max }).format(Number.isFinite(n) ? n : 0);

export const formatKg = (n: number) => `${new Intl.NumberFormat("en-IN").format(n)} kg`;
export const formatPercent = (ratio: number, digits = 0) => `${(ratio * 100).toFixed(digits)}%`;

export function formatDate(iso: string, withTime = false) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", year: "numeric", ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(d);
}

/** Full Indian grouping below one lakh (en-IN compact prints "1.3T" for thousands, which reads as trillion). */
export const compactNumber = (n: number) =>
  n < 100_000 ? new Intl.NumberFormat("en-IN").format(n) : new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);

/** ₹1.8Cr style, for tight spaces (stat cards on phones). */
export const formatINRCompact = (n: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", notation: "compact", maximumFractionDigits: 1 }).format(n);
