# Built from the repo root so the uv workspace (shared lockfile + common package) is available.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml common/
COPY agent-service/pyproject.toml agent-service/
COPY simulator/pyproject.toml simulator/
COPY mcp-servers/pyproject.toml mcp-servers/
COPY evals/pyproject.toml evals/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package oncall-mcp

COPY common/ common/
COPY mcp-servers/ mcp-servers/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package oncall-mcp

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8101 8102 8103 8104
CMD ["uvicorn", "oncall_mcp.app:app", "--host", "0.0.0.0", "--port", "8101"]
