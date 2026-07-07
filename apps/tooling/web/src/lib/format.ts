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
