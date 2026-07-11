/** Formatting + per-title color helpers shared by every view. */

/** Stable hue from a title — "every title carries its own light". */
export function hueOf(title: string): number {
  let hash = 0;
  for (let i = 0; i < title.length; i++) {
    hash = (hash * 31 + title.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % 360;
}

/** Cover placeholder gradient derived from the title — muted, dusty duotone so a
 *  missing/loading poster reads as a refined washi block, not a saturated navy. */
export function titleGradient(title: string): string {
  const h = hueOf(title);
  return `linear-gradient(160deg,
    hsl(${h} 22% 42%) 0%,
    hsl(${(h + 30) % 360} 26% 28%) 100%)`;
}

export function titleGlow(title: string): string {
  return `hsl(${hueOf(title)} 26% 40% / 0.24)`;
}

/** 1234567 -> "1.2M", 4321 -> "4.3k" */
export function compactNumber(value: number | null | undefined): string {
  if (value == null) return "–";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

/** "finished_airing" -> "Finished airing" */
export function label(value: string | null | undefined): string {
  if (!value) return "–";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** media_type in MAL vernacular: tv -> TV, ova -> OVA, ona -> ONA */
export function mediaType(value: string | null | undefined): string {
  if (!value) return "–";
  const upper = new Set(["tv", "ova", "ona"]);
  return upper.has(value) ? value.toUpperCase() : label(value);
}

export const ANIME_STATUSES = [
  "watching",
  "completed",
  "on_hold",
  "dropped",
  "plan_to_watch",
] as const;

export const MANGA_STATUSES = [
  "reading",
  "completed",
  "on_hold",
  "dropped",
  "plan_to_read",
] as const;

/** CSS color token for a personal list status. */
export function statusColor(status: string | null | undefined): string {
  switch (status) {
    case "watching":
    case "reading":
      return "var(--st-watching)";
    case "completed":
      return "var(--st-completed)";
    case "on_hold":
      return "var(--st-on_hold)";
    case "dropped":
      return "var(--st-dropped)";
    case "plan_to_watch":
    case "plan_to_read":
      return "var(--st-plan)";
    default:
      return "var(--text-dim)";
  }
}

export function seasonLabel(season: string): string {
  const kanji: Record<string, string> = {
    winter: "冬",
    spring: "春",
    summer: "夏",
    fall: "秋",
  };
  return `${kanji[season] ?? ""} ${label(season)}`.trim();
}
