# LiveKit STT agent server. It registers with the LiveKit container over a
# WebSocket and needs no public application port; 8081 is its private health
# endpoint.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

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

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8081

CMD ["python", "-m", "irya_ai.worker", "start"]
