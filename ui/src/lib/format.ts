/** Formatting + per-title color helpers shared by every view. */

/** Stable hue from a title — "every title carries its own light". */
export function hueOf(title: string): number {
  let hash = 0;
  for (let i = 0; i < title.length; i++) {
    hash = (hash * 31 + title.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % 360;
}

/** Cover placeholder / ambient glow gradient derived from the title. */
export function titleGradient(title: string): string {
  const h = hueOf(title);
  return `linear-gradient(160deg,
    hsl(${h} 45% 24%) 0%,
    hsl(${(h + 40) % 360} 55% 14%) 100%)`;
}

export function titleGlow(title: string): string {
  return `hsl(${hueOf(title)} 70% 60% / 0.35)`;
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
  const icons: Record<string, string> = {
    winter: "❄",
    spring: "🌸",
    summer: "☀",
    fall: "🍂",
  };
  return `${icons[season] ?? ""} ${label(season)}`.trim();
}
