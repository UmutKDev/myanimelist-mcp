/** Connection to the MCP Apps host: tool results in, tool calls out, theming. */

import { App, type McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import type { ViewPayload } from "./types";

export const app = new App({ name: "mal-app", version: "0.4.0" });

let connected = false;

export function isEmbedded(): boolean {
  return window.parent !== window;
}

/** Connect to the host and stream view payloads + host context to the shell. */
export async function start(
  onData: (payload: ViewPayload) => void,
  onHost: (ctx: McpUiHostContext) => void,
): Promise<void> {
  app.ontoolresult = (result) => {
    const sc = result.structuredContent as ViewPayload | undefined;
    if (sc && typeof sc === "object" && "view" in sc) onData(sc);
  };
  app.onhostcontextchanged = onHost;
  await app.connect();
  connected = true;
  const ctx = app.getHostContext();
  if (ctx) onHost(ctx);
}

/** Call any tool on the MAL server (host-mediated; no direct network). */
export async function callTool<T = unknown>(
  name: string,
  args: Record<string, unknown>,
): Promise<T> {
  const result = await app.callServerTool({ name, arguments: args });
  if (result.isError) {
    const text = result.content?.find((c) => c.type === "text");
    throw new Error(text && "text" in text ? String(text.text) : `${name} failed`);
  }
  return (result.structuredContent ?? {}) as T;
}

/** Tell the model what the user just did in the UI (fire-and-forget). */
export function noteToModel(text: string): void {
  if (!connected) return;
  void app
    .updateModelContext({ content: [{ type: "text", text }] })
    .catch(() => undefined);
}

/** Open the MAL page for an entry via the host (never a raw window.open). */
export function openOnMal(kind: "anime" | "manga", id: number): void {
  void app.openLink({ url: `https://myanimelist.net/${kind}/${id}` }).catch(() => undefined);
}

export async function toggleFullscreen(ctx: McpUiHostContext | null): Promise<boolean> {
  const modes = ctx?.availableDisplayModes ?? [];
  const current = ctx?.displayMode ?? "inline";
  const next = current === "fullscreen" ? "inline" : "fullscreen";
  if (!modes.includes(next)) return false;
  try {
    await app.requestDisplayMode({ mode: next });
    return true;
  } catch {
    return false;
  }
}

/** Host theme + CSS variables -> document root. */
export function applyHostContext(ctx: McpUiHostContext): void {
  const root = document.documentElement;
  if (ctx.theme) root.dataset.theme = ctx.theme;
  const vars = ctx.styles?.variables;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      if (typeof value === "string") root.style.setProperty(name, value);
    }
  }
  const insets = ctx.safeAreaInsets;
  if (insets) {
    root.style.setProperty("--safe-top", `${insets.top ?? 0}px`);
    root.style.setProperty("--safe-right", `${insets.right ?? 0}px`);
    root.style.setProperty("--safe-bottom", `${insets.bottom ?? 0}px`);
    root.style.setProperty("--safe-left", `${insets.left ?? 0}px`);
  }
}
