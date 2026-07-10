/** Navigation + host-action context shared by every view. */

import { createContext, useContext } from "react";
import type { McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import type { Kind } from "../mcp/types";

export interface Nav {
  /** Fetch a detail payload (get_anime_detail / get_manga_detail) and show it. */
  openDetail: (kind: Kind, id: number, fromTitle?: string) => void;
  back: () => void;
  canGoBack: boolean;
  /** Raw tool call (list edits, load-more, dashboard enrichment). */
  callTool: <T = unknown>(name: string, args: Record<string, unknown>) => Promise<T>;
  /** Tell the model what the user did (fire-and-forget). */
  noteToModel: (text: string) => void;
  openOnMal: (kind: Kind, id: number) => void;
  requestFullscreen: () => void;
  hostCtx: McpUiHostContext | null;
}

export const NavContext = createContext<Nav>({
  openDetail: () => undefined,
  back: () => undefined,
  canGoBack: false,
  callTool: async () => {
    throw new Error("not connected");
  },
  noteToModel: () => undefined,
  openOnMal: () => undefined,
  requestFullscreen: () => undefined,
  hostCtx: null,
});

export function useNav(): Nav {
  return useContext(NavContext);
}
