export function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function formatPct(value: unknown, digits = 1): string {
  const number = asNumber(value);
  return number === null ? "N/A" : `${number.toFixed(digits)}%`;
}

export function formatSignedPct(value: unknown, digits = 1): string {
  const number = asNumber(value);
  if (number === null) return "N/A";
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}%`;
}

export function formatRatio(value: unknown, digits = 2): string {
  const number = asNumber(value);
  return number === null ? "N/A" : number.toFixed(digits);
}

export function formatWeight(value: unknown): string {
  const number = asNumber(value);
  return number === null ? "N/A" : `${(number * 100).toFixed(1)}%`;
}

export function formatCurrency(value: unknown): string {
  const number = asNumber(value);
  return number === null
    ? "N/A"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2
      }).format(number);
}

export function formatLargeNumber(value: unknown): string {
  const number = asNumber(value);
  if (number === null) return "N/A";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(number);
}

export function pickArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
}

export function pickRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function sentenceCase(value: unknown): string {
  return String(value ?? "N/A")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
