---
name: rebuild-ui-bundle
description: Use when the ui/ React app changed and the bundled UI needs rebuilding, or when refreshing the docs screenshots.
---

# Rebuild the UI bundle

The React app in `ui/` builds to a single-file bundle at `src/mal_mcp/ui/dist/index.html`, which the
server serves as the `ui://mal-mcp/app.html` MCP Apps resource. The `dist/` dir is **gitignored** but
ships in the wheel via `[tool.hatch.build] artifacts` — so a stale/missing build only shows the
placeholder page ("UI bundle not built…"), it does not fail the server or pytest.

**Released wheels do not use your local build.** `.github/workflows/publish.yml` builds the bundle
from scratch on every tag and hard-fails if it is missing or is the placeholder. Rebuild locally to
*see* your changes; CI is what makes them ship. (CI pins Node 22; a newer local Node is fine.)

## Steps

1. `cd ui`
2. `npm ci` (first time, or after `package.json`/lockfile changes)
3. `npm run typecheck` — catch TS errors before building
4. `npm run build` — emits `src/mal_mcp/ui/dist/index.html`

## Notes

- The server caches the built HTML per process (`_dist_html()` in `ui/__init__.py`). Since the MCP
  client owns the server process, **restart the client** (or its MCP connection) to pick up a rebuild.
  A *miss* is not cached, so building while the process runs takes effect on the next read.
- **Preview** the app with the `mal-ui-dev` launch config (`.claude/launch.json`, Vite on port 5199,
  driven by fixtures in `ui/src/dev/fixtures.ts`).
- **Screenshots:** to refresh `docs/screenshots/*.png`, run the dev server and re-capture the views
  (dashboard, list, search, ranking, schedule, detail) from the fixtures.
