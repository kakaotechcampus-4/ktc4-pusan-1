# Backend production 이미지.
#
#   docker build -t irya-backend .
#
# uv 는 바이너리 하나라 공식 이미지에서 복사해 온다. 빌더 스테이지를 따로 두는
# multi-stage 는 쓰지 않는다 — 여기서 걷어낼 게 uv 바이너리(약 30MB) 뿐이라
# 스테이지를 나누는 값이 비용보다 크지 않다. 컴파일러가 필요한 의존성이
# 생기면 그때 나눈다.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

WORKDIR /app

# PATH: uv 가 만드는 기본 .venv 를 앞에 둔다. `uv run` 없이 uvicorn 을 바로 불러
#       PID 1 이 uvicorn 이 되게 하려는 것이다.
# UV_COMPILE_BYTECODE: 빌드 때 한 번 컴파일해 두면 첫 요청 지연이 줄어든다.
# UV_LINK_MODE: 캐시 마운트를 안 쓰므로 하드링크 경고만 난다. copy 로 고정한다.
# UV_PYTHON_DOWNLOADS: uv 는 managed Python 을 선호한다. 이미지에 이미 3.12 가
#       있으므로 인터프리터를 새로 내려받지 않도록 막는다.
ENV PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# 의존성 레이어를 소스와 분리한다. app/ 만 바뀌면 uv sync 를 다시 돌지 않는다.
COPY pyproject.toml uv.lock ./
# --locked: uv.lock 과 pyproject.toml 이 어긋나면 잠금을 갱신하지 않고 실패한다.
# --no-dev: pytest·ruff·pyright 는 production 이미지에 넣지 않는다.
RUN uv sync --locked --no-dev

# tests/ · scripts/ 는 복사하지 않는다. 런타임에 쓰이지 않고 CI 에서만 돈다.
COPY app ./app

# root 로 돌릴 이유가 없다. .venv 는 root 소유인 채로 읽기만 하면 된다.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
