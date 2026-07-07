// Numeric formatting per docs/05 §"Color & typography": 4-dp mm always, inch
// 5-dp when toggled. API sends Decimal fields as JSON strings (pydantic v2), so
// these accept string | number and coerce.

type Num = string | number | null | undefined;

function toNumber(value: Num): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Millimeters, 4 decimals. Returns "—" for null. */
export function mm(value: Num): string {
  const n = toNumber(value);
  return n === null ? "—" : n.toFixed(4);
}

/** Inches, 5 decimals. Returns "—" for null. */
export function inch(value: Num): string {
  const n = toNumber(value);
  return n === null ? "—" : n.toFixed(5);
}

/** Convert a millimeter value to inches, 5 decimals. Returns "—" for null. */
export function mmToInch(value: Num): string {
  const n = toNumber(value);
  return n === null ? "—" : (n / 25.4).toFixed(5);
}

/** Compact "time since" label for a poll/change timestamp (R11: always show
 *  how fresh a mirror value is). Returns "—" for null. */
export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** Compact one-line tool spec, e.g. "6.3500mm 4F carbide, tialn". */
export function compactSpec(t: {
  diameter_mm: Num;
  flute_count: number | null;
  substrate: string | null;
  coating: string | null;
}): string {
  const parts = [`${mm(t.diameter_mm)}mm`];
  if (t.flute_count != null) parts.push(`${t.flute_count}F`);
  if (t.substrate) parts.push(t.substrate);
  const base = parts.join(" ");
  return t.coating ? `${base}, ${t.coating}` : base;
}
