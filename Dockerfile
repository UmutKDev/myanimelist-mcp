# Build the MCP Apps UI into one self-contained HTML file first.
FROM node:22-slim AS ui-build

WORKDIR /build
COPY ui/package.json ui/package-lock.json ./ui/
RUN cd ui && npm ci --no-fund --no-audit
COPY ui ./ui
RUN cd ui && npm run build   # emits /build/src/mal_mcp/ui/dist/index.html

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/UmutKDev/myanimelist-mcp" \
      org.opencontainers.image.description="Stateless MyAnimeList MCP server (streamable-http) with an MCP Apps UI" \
      org.opencontainers.image.licenses="MIT"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8000

WORKDIR /app

# Install dependencies first so this layer is cached across source-only changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# README.md is needed here because hatchling builds the project (readme metadata).
COPY README.md ./
COPY src ./src
COPY --from=ui-build /build/src/mal_mcp/ui/dist ./src/mal_mcp/ui/dist
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# The venv stays root-owned (read+execute is enough); no recursive chown, which
# would duplicate the whole layer.
RUN useradd --create-home app
USER app

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "python", "-m", "mal_mcp.server"]
