# Built from the repo root so the uv workspace (shared lockfile + common package) is available.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Install dependencies first (cached layer), then the workspace sources.
COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml common/
COPY agent-service/pyproject.toml agent-service/
COPY simulator/pyproject.toml simulator/
COPY mcp-servers/pyproject.toml mcp-servers/
COPY evals/pyproject.toml evals/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package rootsignal-agent

COPY common/ common/
COPY agent-service/ agent-service/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package rootsignal-agent

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["rootsignal-agent"]
