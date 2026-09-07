# IRYA AI

LiveKit 오디오 트랙을 실시간 STT와 후속 AI 파이프라인으로 연결하는 파트입니다.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- LiveKit 서버 접속 정보

Python은 `ai/.python-version`의 3.12를 사용합니다. 로컬에 설치되어 있지 않으면 `uv`가 필요한 버전을 설치할 수 있습니다.

## Setup

`ai` 디렉터리에서 실행합니다.

```bash
uv sync --locked
cp .env.example .env
```

`.env`에 로컬 또는 개발용 LiveKit 접속 정보를 입력합니다. 실제 API Key와 Secret은 커밋하지 않습니다.

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `APP_ENV` | 실행 환경 | `local` |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |
| `LIVEKIT_URL` | LiveKit WebSocket URL | `ws://localhost:7880` |
| `LIVEKIT_API_KEY` | LiveKit API Key | 없음 |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | 없음 |

## Verify

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Scope

이 환경은 LiveKit Agents 기반의 STT Agent와 AI 파이프라인이 공통으로 사용합니다. STT 공급자, 모델, GPU 및 self-host 여부는 검증 후 별도로 선택합니다.
