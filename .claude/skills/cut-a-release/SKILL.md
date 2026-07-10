---
name: cut-a-release
description: Use when cutting a release or bumping the version of mal-mcp — bumps the two version files that must stay in sync, runs tests, refreshes the lockfile, and commits with the repo convention.
---

# Cut a release

The version lives in **two files that must match**. `uv.lock` also pins the project's own
version, so it changes on every bump. `ui/package.json` is intentionally decoupled — leave it.

## Steps

1. **Pick the new semver** (e.g. `0.4.4`). Look at recent `git log --oneline` for scope.
2. **Bump both version files to the same value:**
   - `pyproject.toml` → `version = "x.y.z"`
   - `src/mal_mcp/__init__.py` → `__version__ = "x.y.z"`
3. **Run the tests:** `uv run pytest` — must pass before committing.
4. **Refresh the lockfile:** `uv sync` (or `uv lock`) so `uv.lock` re-pins `x.y.z`.
5. **Commit** with the repo convention — a scoped, imperative subject with the version:
   - `Area: short summary (x.y.z)`  (e.g. `Schedule: keep 7 weekdays on one row (0.4.3)`)
   - or `Release x.y.z: short summary`
   Commit straight to `main` (linear history — no branch/PR/tag).

## Do not

- **Do not** bump `ui/package.json` — it is decoupled on purpose.
- There is **no** CHANGELOG, git tags, or CI release step to update.
- Do not leave `pyproject.toml` and `__init__.py` out of sync — that is the classic footgun here.
