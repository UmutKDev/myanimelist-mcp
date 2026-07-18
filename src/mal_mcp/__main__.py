"""Allow `python -m mal_mcp` alongside the `myanimelist-mcp` console script."""

from __future__ import annotations

from mal_mcp.server import main

if __name__ == "__main__":
    main()
