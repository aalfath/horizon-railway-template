# Horizon (https://github.com/Thysrael/Horizon) for Railway.
# Upstream publishes no image and no release tags, so this builds upstream's
# own Dockerfile steps from a pinned commit on a digest-pinned Python base.
FROM python:3.11.18-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

# Upstream commit (main, 2026-11-22). Bump this to update Horizon.
ARG HORIZON_COMMIT=e17ea80ced84e575e89489f3905b75eabf7e249b

COPY --from=ghcr.io/astral-sh/uv:0.11.26@sha256:3d868e555f8f1dbc324afa005066cd11e1053fc4743b9808ca8025283e65efa5 /uv /usr/local/bin/uv

WORKDIR /app

ADD https://codeload.github.com/Thysrael/Horizon/tar.gz/${HORIZON_COMMIT} /tmp/horizon.tar.gz
RUN set -eu; \
    tar -xzf /tmp/horizon.tar.gz -C /tmp; \
    src="/tmp/Horizon-${HORIZON_COMMIT}"; \
    cp -r "$src/pyproject.toml" "$src/uv.lock" "$src/README.md" "$src/src" "$src/profiles" /app/; \
    mkdir -p /app/defaults; cp "$src/data/config.example.json" "$src/data/presets.json" /app/defaults/; \
    rm -r /tmp/horizon.tar.gz "$src"; \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy uv sync --frozen --no-dev --no-cache; \
    useradd --create-home --uid 10001 horizon; \
    mkdir -p /app/data /app/docs; chown -R horizon:horizon /app/data /app/docs; \
    echo "$HORIZON_COMMIT" > /app/HORIZON_COMMIT

COPY railway/ /app/railway/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HORIZON_DATA_DIR=/app/data

EXPOSE 8080

# Runs as root only to fix the volume's ownership, then drops to uid 10001.
ENTRYPOINT ["/bin/sh", "/app/railway/start.sh"]
