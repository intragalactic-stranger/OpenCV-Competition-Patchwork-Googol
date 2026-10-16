# Ward Engineer's Assistant for Amazon Bedrock AgentCore Runtime (linux/arm64, HTTP on :8080).
#   docker buildx build --platform linux/arm64 -f docker/agent.Dockerfile -t patchwork-agent .
FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY docs/README.md docs/README.md
RUN uv sync --frozen --no-dev --group aws --group agent --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --group aws --group agent

ENV PATH=/app/.venv/bin:$PATH
RUN python -c "import patchwork.agent.runtime, strands; print('ok')"
EXPOSE 8080
ENTRYPOINT ["python", "-m", "patchwork.agent.runtime"]
