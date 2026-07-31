# syntax=docker/dockerfile:1
# Initialize device type args
# use build args in the docker build command with --build-arg="BUILDARG=true"
ARG USE_CUDA=false
ARG USE_OLLAMA=false
ARG USE_SLIM=false
ARG USE_PERMISSION_HARDENING=false
# Tested with cu117 for CUDA 11 and cu121 for CUDA 12 (default)
ARG USE_CUDA_VER=cu128
# any sentence transformer model; models to use can be found at https://huggingface.co/models?library=sentence-transformers
# Leaderboard: https://huggingface.co/spaces/mteb/leaderboard 
# for better performance and multilangauge support use "intfloat/multilingual-e5-large" (~2.5GB) or "intfloat/multilingual-e5-base" (~1.5GB)
# IMPORTANT: If you change the embedding model (sentence-transformers/all-MiniLM-L6-v2) and vice versa, you aren't able to use RAG Chat with your previous documents loaded in the WebUI! You need to re-embed them.
ARG USE_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ARG USE_RERANKING_MODEL=""
ARG USE_AUXILIARY_EMBEDDING_MODEL=TaylorAI/bge-micro-v2

# Tiktoken encoding name; models to use can be found at https://huggingface.co/models?library=tiktoken
ARG USE_TIKTOKEN_ENCODING_NAME="cl100k_base"

ARG BUILD_HASH=dev-build
# Override at your own risk - non-root configurations are untested
ARG UID=0
ARG GID=0

######## WebUI frontend ########
FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS build
ARG BUILD_HASH

# Set Node.js options (heap limit Allocation failed - JavaScript heap out of memory)
ENV NODE_OPTIONS="--max-old-space-size=4096"

WORKDIR /app

# to store git revision in build
RUN apk add --no-cache git

COPY package.json package-lock.json ./
# Cache mount for npm's download cache: a lockfile change then re-links from cache
# instead of re-fetching every tarball from the registry.
RUN --mount=type=cache,target=/root/.npm npm ci --force

# Copy ONLY what `npm run build` actually reads, rather than `COPY . .`.
#
# This is the layer that hurt: with the whole build context, editing any backend/*.py
# file — or even just committing, since .git is part of the context — invalidated this
# COPY and forced a full `npm run pyodide:fetch && vite build`. Now a backend-only change
# leaves the entire frontend stage cached.
#
# Keep this list in sync when adding a root-level config file the build reads.
COPY svelte.config.js vite.config.ts tsconfig.json postcss.config.js tailwind.config.js ./
COPY scripts ./scripts
COPY src ./src
COPY static ./static
COPY CHANGELOG.md ./CHANGELOG.md

ENV APP_BUILD_HASH=${BUILD_HASH}
# `build` = prepare-pyodide.js (downloads pyodide + PyPI wheels into static/pyodide) then
# vite build. Not cache-mounted: the script writes its downloads straight into
# static/pyodide, which has to end up in the build output, so there is no separate cache
# directory to reuse. It is skipped entirely whenever this layer stays cached.
RUN npm run build

######## WebUI backend ########
FROM python:3.11-slim-bookworm AS base

# Use args
ARG USE_CUDA
ARG USE_OLLAMA
ARG USE_CUDA_VER
ARG USE_SLIM
ARG USE_PERMISSION_HARDENING
ARG USE_EMBEDDING_MODEL
ARG USE_RERANKING_MODEL
ARG USE_AUXILIARY_EMBEDDING_MODEL
ARG UID
ARG GID

# Python settings
ENV PYTHONUNBUFFERED=1

## Basis ##
ENV ENV=prod \
    PORT=8080 \
    # pass build args to the build
    USE_OLLAMA_DOCKER=${USE_OLLAMA} \
    USE_CUDA_DOCKER=${USE_CUDA} \
    USE_SLIM_DOCKER=${USE_SLIM} \
    USE_CUDA_DOCKER_VER=${USE_CUDA_VER} \
    USE_EMBEDDING_MODEL_DOCKER=${USE_EMBEDDING_MODEL} \
    USE_RERANKING_MODEL_DOCKER=${USE_RERANKING_MODEL} \
    USE_AUXILIARY_EMBEDDING_MODEL_DOCKER=${USE_AUXILIARY_EMBEDDING_MODEL}

## Basis URL Config ##
ENV OLLAMA_BASE_URL="/ollama" \
    OPENAI_API_BASE_URL=""

## API Key and Security Config ##
ENV OPENAI_API_KEY="" \
    WEBUI_SECRET_KEY="" \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false

#### Other models #########################################################
## whisper TTS model settings ##
ENV WHISPER_MODEL="base" \
    WHISPER_MODEL_DIR="/app/backend/data/cache/whisper/models"

## RAG Embedding model settings ##
ENV RAG_EMBEDDING_MODEL="$USE_EMBEDDING_MODEL_DOCKER" \
    RAG_RERANKING_MODEL="$USE_RERANKING_MODEL_DOCKER" \
    AUXILIARY_EMBEDDING_MODEL="$USE_AUXILIARY_EMBEDDING_MODEL_DOCKER" \
    SENTENCE_TRANSFORMERS_HOME="/app/backend/data/cache/embedding/models"

## Tiktoken model settings ##
ENV TIKTOKEN_ENCODING_NAME="cl100k_base" \
    TIKTOKEN_CACHE_DIR="/app/backend/data/cache/tiktoken"

## Hugging Face download cache ##
ENV HF_HOME="/app/backend/data/cache/embedding/models"

## Torch Extensions ##
# ENV TORCH_EXTENSIONS_DIR="/.cache/torch_extensions"

#### Other models ##########################################################

WORKDIR /app/backend

ENV HOME=/root
# Create user and group if not root
RUN if [ $UID -ne 0 ]; then \
    if [ $GID -ne 0 ]; then \
    addgroup --gid $GID app; \
    fi; \
    adduser --uid $UID --gid $GID --home $HOME --disabled-password --no-create-home app; \
    fi

RUN mkdir -p $HOME/.cache/chroma
RUN echo -n 00000000-0000-0000-0000-000000000000 > $HOME/.cache/chroma/telemetry_user_id

# Make sure the user has access to the app and root directory
RUN chown -R $UID:$GID /app $HOME

# Install common system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git build-essential pandoc gcc netcat-openbsd curl jq \
    libmariadb-dev \
    python3-dev \
    ffmpeg libsm6 libxext6 zstd \
    && rm -rf /var/lib/apt/lists/*

# install python dependencies
COPY --chown=$UID:$GID ./backend/requirements.txt ./requirements.txt

# Set UV_LINK_MODE to copy to prevent 0-byte file corruption in QEMU arm64 cross-builds
ENV UV_LINK_MODE=copy

# --- Python dependencies -----------------------------------------------------------
# Split from the model downloads below so the two are separately readable, and both use
# BuildKit cache mounts. Note the deliberate absence of `--no-cache-dir`: the pip/uv
# caches now live in a cache mount, which is NOT part of any image layer, so keeping them
# populated costs nothing in image size and saves re-downloading ~2-3GB of torch wheels
# every time requirements.txt is touched.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    set -e; \
    pip3 install uv; \
    if [ "$USE_CUDA" = "true" ]; then \
    # fix: pin torch<=2.9.1 - torch 2.10.0 aarch64 wheels cause SIGILL on ARM devices (RPi 4 Cortex-A72) #21349
    pip3 install 'torch<=2.9.1' torchvision torchaudio --index-url https://download.pytorch.org/whl/$USE_CUDA_DOCKER_VER; \
    else \
    pip3 install 'torch<=2.9.1' torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu; \
    fi; \
    uv pip install --system -r requirements.txt

# --- Pre-baked models --------------------------------------------------------------
# Runs when USE_CUDA=true, or when USE_SLIM is not set — exactly the original condition.
# (The original's "downloaded on first use" comment in the CUDA branch was stale: that
# branch pre-downloaded all five just like the CPU one. Behaviour preserved as-is.)
#
# The downloads are staged into a cache mount and then copied into the image, because a
# cache mount's contents never become part of a layer: writing straight into
# /app/backend/data/cache would leave the models missing at runtime. Staging + copy means
# a requirements.txt change no longer re-downloads ~1GB of weights over the network.
#
# nltk is deliberately NOT staged — it resolves its data path at runtime from a set of
# default locations, and relocating it risks a runtime lookup failure for ~10MB of savings.
RUN --mount=type=cache,target=/opt/model-stage,sharing=locked \
    set -e; \
    if [ "$USE_CUDA" = "true" ] || [ "$USE_SLIM" != "true" ]; then \
    export SENTENCE_TRANSFORMERS_HOME=/opt/model-stage/embedding/models \
    HF_HOME=/opt/model-stage/embedding/models \
    WHISPER_MODEL_DIR=/opt/model-stage/whisper/models \
    TIKTOKEN_CACHE_DIR=/opt/model-stage/tiktoken; \
    python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['RAG_EMBEDDING_MODEL'], device='cpu')"; \
    python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ.get('AUXILIARY_EMBEDDING_MODEL', 'TaylorAI/bge-micro-v2'), device='cpu')"; \
    python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8', download_root=os.environ['WHISPER_MODEL_DIR'])"; \
    python -c "import os; import tiktoken; tiktoken.get_encoding(os.environ['TIKTOKEN_ENCODING_NAME'])"; \
    python -c "import nltk; nltk.download('punkt_tab')"; \
    mkdir -p /app/backend/data/cache; \
    cp -a /opt/model-stage/. /app/backend/data/cache/; \
    fi; \
    mkdir -p /app/backend/data; chown -R $UID:$GID /app/backend/data/; \
    rm -rf /var/lib/apt/lists/*;

# Install Ollama if requested
# RUN if [ "$USE_OLLAMA" = "true" ]; then \
#     date +%s > /tmp/ollama_build_hash && \
#     echo "Cache broken at timestamp: `cat /tmp/ollama_build_hash`" && \
#     curl -fsSL https://ollama.com/install.sh | sh && \
#     rm -rf /var/lib/apt/lists/*; \
#     fi

# copy embedding weight from build
# RUN mkdir -p /root/.cache/chroma/onnx_models/all-MiniLM-L6-v2
# COPY --from=build /app/onnx /root/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx

# copy built frontend files
COPY --chown=$UID:$GID --from=build /app/build /app/build
COPY --chown=$UID:$GID --from=build /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=$UID:$GID --from=build /app/package.json /app/package.json

# copy backend files
COPY --chown=$UID:$GID ./backend .

EXPOSE 8080

HEALTHCHECK CMD curl --silent --fail http://localhost:${PORT:-8080}/health | jq -ne 'input.status == true' || exit 1

# Minimal, atomic permission hardening for OpenShift (arbitrary UID):
# - Group 0 owns /app and /root
# - Directories are group-writable and have SGID so new files inherit GID 0
RUN if [ "$USE_PERMISSION_HARDENING" = "true" ]; then \
    set -eux; \
    chgrp -R 0 /app /root || true; \
    chmod -R g+rwX /app /root || true; \
    find /app -type d -exec chmod g+s {} + || true; \
    find /root -type d -exec chmod g+s {} + || true; \
    fi

USER $UID:$GID

ARG BUILD_HASH
ENV WEBUI_BUILD_VERSION=${BUILD_HASH}
ENV DOCKER=true

CMD [ "bash", "start.sh"]
