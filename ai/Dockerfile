# LiveKit STT agent server. It registers with the LiveKit container over a
# WebSocket and needs no public application port; 8081 is its private health
# endpoint.
#
# Base and uv pinned by digest; Dependabot bumps them (#134). uv comes in as a
# `FROM ... AS uv` stage because Dependabot only reads FROM lines, not
# `COPY --from=<image>`.
FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# Cache third-party dependencies separately from the application package.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Which commit built this image. There is no registry and so no tag; the
# label is how the deployed version is read back. After the source COPY so
# a new SHA does not rebuild the dependency layers.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8081

CMD ["python", "-m", "irya_ai.worker", "start"]
