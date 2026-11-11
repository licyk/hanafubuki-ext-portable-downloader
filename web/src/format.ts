const UNITS = ["B", "KB", "MB", "GB", "TB"];

/** A byte count in binary units with at most one decimal (`1.5 GB`). */
export function formatBytes(bytes: number): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

export function formatSpeed(bytesPerSecond: number): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

export function formatPercent(fraction: number): string {
  return `${Math.floor(fraction * 100)}%`;
}

/** A build date as the list writes it (`20261109`) in ISO form; anything else as it is. */
export function formatBuildDate(date: string): string {
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(date);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : date;
}

/** The list's update time (ISO 8601) in the page's locale, or the text as it is. */
export function formatUpdateTime(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
