/** Fake host for `npm run dev` in a plain browser tab: tool calls resolve from fixtures. */

import type { ViewPayload } from "../mcp/types";
import { FIXTURES } from "./fixtures";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function devCallTool<T>(name: string, args: Record<string, unknown>): Promise<T> {
  await wait(650); // let skeletons/optimistic states show up
  if (name === "get_anime_detail" || name === "get_manga_detail") {
    return FIXTURES.detail as T;
  }
  if (name.startsWith("update_my_")) {
    return {
      anime_id: args.anime_id,
      manga_id: args.manga_id,
      my_list_status: {
        status: args.status ?? "watching",
        score: args.score ?? 0,
        num_episodes_watched: args.num_watched_episodes ?? 0,
        num_chapters_read: args.num_chapters_read ?? 0,
      },
    } as T;
  }
  if (name.startsWith("delete_my_")) {
    return { deleted: true } as T;
  }
  if (name === "get_user_stats") {
    return { view: "dashboard", stats: (FIXTURES.dashboard as { stats?: unknown }).stats } as T;
  }
  if (name === "get_my_profile") {
    return { view: "dashboard", profile: (FIXTURES.dashboard as { profile?: unknown }).profile } as T;
  }
  const paged = FIXTURES[name.includes("ranking") ? "ranking" : "search"];
  return paged as T;
}

export function devPayload(view: string): ViewPayload {
  return FIXTURES[view] ?? FIXTURES.search;
}
