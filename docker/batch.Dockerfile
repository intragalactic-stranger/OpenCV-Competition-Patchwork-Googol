# Patchwork pipeline image (linux/arm64 for Graviton; builds on x86 through QEMU).
#   docker buildx build --platform linux/arm64 -f docker/batch.Dockerfile -t patchwork-batch .
FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app

# dependencies first (cached layer), then the project (editable, so ROOT-relative paths resolve to /app)
COPY pyproject.toml uv.lock ./
COPY docs/README.md docs/README.md
RUN uv sync --frozen --no-dev --group aws --no-install-project
COPY src ./src
COPY data/corridor ./data/corridor
RUN uv sync --frozen --no-dev --group aws

ENV PATH=/app/.venv/bin:$PATH
RUN python -c "import cv2, boto3; print(cv2.__version__)"
ENTRYPOINT ["python", "-m"]
CMD ["patchwork.pipeline.synth_job", "--help"]
