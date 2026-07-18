---
name: cut-a-release
description: Use when cutting a release of myanimelist-mcp — bumps the single version source, runs tests, commits, and pushes the tag that triggers the PyPI publish workflow.
---

# Cut a release

The version has **one** source: `__version__` in `src/mal_mcp/__init__.py`. `pyproject.toml`
reads it via `[tool.hatch.version]`. Pushing a `vX.Y.Z` tag triggers
`.github/workflows/publish.yml`, which builds the UI, builds the wheel, and publishes to PyPI
via Trusted Publishing.

`ui/package.json` is intentionally decoupled — leave it.

## Steps

1. **Pick the new semver** (e.g. `0.5.1`). Look at recent `git log --oneline` for scope.
2. **Bump `src/mal_mcp/__init__.py`** → `__version__ = "x.y.z"`.
   `uv version` / `uv version --bump` **do not work here** — the version is dynamic, so uv
   refuses ("cannot get or set dynamic project versions"). Edit by hand.
3. **Refresh the editable install, then test:**
   ```bash
   uv sync --reinstall-package myanimelist-mcp   # REQUIRED after a bump
   uv run pytest
   ```
   uv does not rebuild the editable install's `dist-info` when only the dynamic-version source
   changes, so skipping the reinstall makes `test_distribution_version_matches_dunder` fail with
   the old version. That is a local artifact, not a real defect.
4. **Re-lock only if needed:** `uv lock` is required when the project name or dependencies
   change, not for a plain version bump (the lockfile's root entry carries no version).
5. **Commit** with the repo convention — a scoped, imperative subject with the version:
   - `Area: short summary (x.y.z)` (e.g. `Schedule: keep 7 weekdays on one row (0.4.3)`)
   - or `Release x.y.z: short summary`
6. **Tag and push:**
   ```bash
   git tag -a vx.y.z -m "vx.y.z"
   git push origin main --follow-tags
   gh run watch
   ```
   The workflow hard-fails if the tag does not match `__version__`, if the UI bundle is missing
   or is the placeholder, or if `twine check --strict` complains.

## Do not

- **Do not** bump `ui/package.json` — it is decoupled on purpose.
- **Do not** delete or re-point a published tag. PyPI versions are immutable, so a botched
  release needs the next patch version, never a re-tag.
- **Do not** upload by hand with twine. Trusted Publishing from the workflow is the only path;
  there is no API token anywhere, by design.
- There is still **no** CHANGELOG and no PRs — linear history on `main`.
