# Patchwork CPU training image (linux/arm64, Graviton; decision D-25: no GPU).
#   docker buildx build --platform linux/arm64 -f docker/train.Dockerfile -t patchwork-train .
FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 HF_HOME=/opt/hf
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY docs/README.md docs/README.md
RUN uv sync --frozen --no-dev --group aws --group train --no-install-project
ENV PATH=/app/.venv/bin:$PATH
# bake the ImageNet encoder so jobs do not depend on the Hugging Face Hub at run time
RUN python -c "from transformers import SegformerForSemanticSegmentation as S; S.from_pretrained('nvidia/mit-b0')" \
 && python -c "from torchvision.models import MobileNet_V3_Large_Weights as W; W.IMAGENET1K_V2.get_state_dict()"
COPY src ./src
COPY training ./training
# awscli after the final (exact) sync, otherwise uv removes it; used for `aws s3 sync` of datasets/checkpoints
RUN uv sync --frozen --no-dev --group aws --group train && uv pip install --python .venv awscli
RUN python -c "import awscli, torch, cv2; print(torch.__version__, cv2.__version__, torch.backends.mkldnn.is_available())"
ENTRYPOINT ["python", "-m"]
CMD ["training.train", "--help"]
