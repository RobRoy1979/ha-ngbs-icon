# Toolchain image for linting and testing. Home Assistant 2026.9 requires Python 3.14.
FROM python:3.14-slim

ENV HOME=/tmp \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install the toolchain first so the layer is cached while the code changes.
COPY requirements_dev.txt ./
COPY lib/pyngbsicon/pyproject.toml ./lib/pyngbsicon/pyproject.toml
COPY lib/pyngbsicon/README.md lib/pyngbsicon/LICENSE ./lib/pyngbsicon/
RUN mkdir -p lib/pyngbsicon/src/pyngbsicon \
    && printf '"""Placeholder for the editable install; replaced by the bind mount."""\n__version__ = "0.0.0"\n' > lib/pyngbsicon/src/pyngbsicon/__init__.py \
    && pip install -r requirements_dev.txt

CMD ["make", "check"]
