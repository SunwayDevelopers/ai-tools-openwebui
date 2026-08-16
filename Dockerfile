# syntax=docker/dockerfile:1
#
# schat — CPU-only, x86_64, external model APIs. Deliberately minimal.
#
# This replaces upstream open-webui's Dockerfile, which builds every configuration from one
# file (CUDA/CPU, bundled Ollama, a slim variant, OpenShift arbitrary-UID, ARM cross-build)
# via USE_* build args and shell conditionals. Our CI passes only BUILD_HASH, so every one
# of those switches sat at its default and only one path was ever taken. They are gone.
#
# TRADEOFF, know this before merging upstream: `git merge upstream/main` will conflict on
# this file, every time. When it does, do NOT take upstream's version wholesale — re-read
# their Dockerfile for real fixes (e.g. the torch<=2.9.1 SIGILL pin below came from
# upstream #21349) and port them here by hand.
#
# Build:  docker build --build-arg BUILD_HASH=$(git rev-parse HEAD) -t schat .
# Deploy: linux/amd64 only. The runtime stage has no --platform pin, so building on Apple
#         Silicon without --platform=linux/amd64 yields an arm64 image that dies in the
#         cluster with `exec format error`.

ARG BUILD_HASH=dev-build


######## Frontend ########
FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS build
ARG BUILD_HASH

# Heap bump: the default limit OOMs during `vite build`.
ENV NODE_OPTIONS="--max-old-space-size=4096"
WORKDIR /app

COPY package.json package-lock.json ./
# Cache mount for npm's download cache, so a lockfile change re-links from cache instead
# of re-fetching every tarball.
RUN --mount=type=cache,target=/root/.npm npm ci --force

# ONLY the build's actual inputs — not `COPY . .`. With the whole context, editing any
# backend/*.py file (or merely committing, since .git is in the context) invalidated this
# layer and forced a full frontend rebuild. Keep this list current when adding a
# root-level config file that the build reads.
COPY svelte.config.js vite.config.ts tsconfig.json postcss.config.js tailwind.config.js ./
COPY scripts ./scripts
COPY src ./src
COPY static ./static
COPY CHANGELOG.md ./CHANGELOG.md

ENV APP_BUILD_HASH=${BUILD_HASH}
# = prepare-pyodide.js (fetches pyodide + PyPI wheels into static/pyodide) then vite build.
RUN npm run build


######## Backend ########
FROM python:3.11-slim-bookworm
ARG BUILD_HASH

ENV PYTHONUNBUFFERED=1 \
    ENV=prod \
    PORT=8080 \
    DOCKER=true \
    WEBUI_BUILD_VERSION=${BUILD_HASH}

# Telemetry off.
ENV SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false

# Load-bearing, do not drop as "unused": config.py branches on this exact literal
# (`if OLLAMA_BASE_URL == '/ollama'`, config.py:317) and its comment names the Dockerfile as
# the source. Unsetting it takes a different branch and resolves to localhost:11434 instead.
# We do not run Ollama, so neither is reachable — but keep the documented path.
ENV OLLAMA_BASE_URL="/ollama"

# Prevents 0-byte file corruption when building under QEMU emulation — which is what
# `--platform=linux/amd64` on an Apple Silicon laptop does.
ENV UV_LINK_MODE=copy

# Model cache locations. These are read at RUNTIME to find the weights baked in below —
# changing a path here means also changing where the download step puts them.
ENV WHISPER_MODEL="base" \
    WHISPER_MODEL_DIR="/app/backend/data/cache/whisper/models" \
    RAG_EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2" \
    AUXILIARY_EMBEDDING_MODEL="TaylorAI/bge-micro-v2" \
    SENTENCE_TRANSFORMERS_HOME="/app/backend/data/cache/embedding/models" \
    HF_HOME="/app/backend/data/cache/embedding/models" \
    TIKTOKEN_ENCODING_NAME="cl100k_base" \
    TIKTOKEN_CACHE_DIR="/app/backend/data/cache/tiktoken"

WORKDIR /app/backend

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git build-essential pandoc gcc netcat-openbsd curl jq \
    libmariadb-dev python3-dev \
    ffmpeg libsm6 libxext6 zstd \
    && rm -rf /var/lib/apt/lists/*

COPY ./backend/requirements.txt ./requirements.txt

# --- Python dependencies ---
# No `--no-cache-dir`: the pip/uv caches live in cache mounts, which never become part of
# an image layer — so keeping them populated costs zero image size and saves re-downloading
# ~2-3GB of torch wheels whenever requirements.txt changes.
# torch is pinned <=2.9.1 per upstream #21349 (2.10.0 aarch64 wheels SIGILL on ARM).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    pip3 install uv; \
    pip3 install 'torch<=2.9.1' torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu; \
    uv pip install --system -r requirements.txt

# --- Bake the ML models in ---
# Staged through a cache mount, then copied into the image: a cache mount's contents are
# never part of a layer, so downloading straight into /app/backend/data/cache would leave
# the image with no weights. Staging means a requirements.txt change stops re-pulling
# ~260MB of models over the network.
#
# nltk is intentionally NOT staged — it resolves its data path at runtime from a list of
# default locations, and relocating it risks a runtime lookup failure to save ~10MB.
RUN --mount=type=cache,target=/opt/model-stage,sharing=locked \
    set -eux; \
    export SENTENCE_TRANSFORMERS_HOME=/opt/model-stage/embedding/models \
    HF_HOME=/opt/model-stage/embedding/models \
    WHISPER_MODEL_DIR=/opt/model-stage/whisper/models \
    TIKTOKEN_CACHE_DIR=/opt/model-stage/tiktoken; \
    python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['RAG_EMBEDDING_MODEL'], device='cpu')"; \
    python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['AUXILIARY_EMBEDDING_MODEL'], device='cpu')"; \
    python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8', download_root=os.environ['WHISPER_MODEL_DIR'])"; \
    python -c "import os; import tiktoken; tiktoken.get_encoding(os.environ['TIKTOKEN_ENCODING_NAME'])"; \
    python -c "import nltk; nltk.download('punkt_tab')"; \
    mkdir -p /app/backend/data/cache; \
    cp -a /opt/model-stage/. /app/backend/data/cache/

# Sunway: the container runs as a NON-ROOT user (security review M6). UID 1000, primary
# group 0.
#
# Group 0 rather than a matching group 1000 is deliberate. The pod may run under an
# arbitrary UID — the chart sets runAsUser, but an admission controller or a future
# OpenShift-style policy can override it — and an arbitrary UID always lands in group 0.
# Pairing that with `chmod -R g=u` below means the app can write its tree whatever UID it
# is finally given, so the image does not depend on the chart and the chart getting the
# number right.
#
# HOME is set explicitly because it stops being /root, and several libraries derive cache
# paths from it. Anything writing under $HOME must exist and be group-writable, or the
# first write fails at runtime rather than at build time.
ENV HOME=/home/schat
RUN useradd -u 1000 -g 0 -d "$HOME" -m -s /usr/sbin/nologin schat

# Opt chromadb's telemetry out before it can generate an id. Under $HOME, not /root —
# the app can no longer read or write /root.
RUN mkdir -p "$HOME/.cache/chroma" && \
    echo -n 00000000-0000-0000-0000-000000000000 > "$HOME/.cache/chroma/telemetry_user_id"

# Frontend build output. package.json is read at runtime for the version string.
COPY --from=build /app/build /app/build
COPY --from=build /app/CHANGELOG.md /app/CHANGELOG.md
COPY --from=build /app/package.json /app/package.json

# Last, so a backend code change rebuilds only this layer.
COPY ./backend .

# Hand the whole tree to group 0 with the owner's permissions (security review M6). Two
# separate things need this, and missing either one is a runtime crash, not a warning:
#
#   /app/backend/data  — DATA_DIR. The chart mounts the PVC on a subPath (UPLOAD_DIR) only,
#                        so the REST of this tree stays image content and must be writable
#                        in place: the baked embedding / whisper / tiktoken caches live here.
#   /app/backend       — start.sh writes `.webui_secret_key` here when WEBUI_SECRET_KEY is
#                        unset. The chart always sets it, so this should never fire — but if
#                        it ever does, failing on a permission error would be a confusing way
#                        to find out.
#
# `g=u` copies the owner bits to the group, and `find -type d` adds the setgid bit so files
# created at runtime inherit group 0 instead of the writer's primary group.
#
# ⚠ Group 0 is LOAD-BEARING, not cosmetic. Verified by running this image three ways:
#   uid 1000 gid 0      → all writes OK
#   uid 31337 gid 0     → all writes OK  (this is why group 0 rather than group 1000)
#   uid 31337 gid 31337 → EVERY write fails
# So "tidying" the chart's runAsGroup/fsGroup from 0 to 1000 breaks the pod. They must stay 0.
RUN chown -R 1000:0 /app "$HOME" && \
    chmod -R g=u /app "$HOME" && \
    find /app -type d -exec chmod g+s {} +

USER 1000

EXPOSE 8080

HEALTHCHECK CMD curl --silent --fail http://localhost:${PORT:-8080}/health | jq -ne 'input.status == true' || exit 1

CMD [ "bash", "start.sh"]
