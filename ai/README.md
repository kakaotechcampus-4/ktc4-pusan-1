# IRYA AI

LiveKit 오디오 트랙을 실시간 STT와 후속 AI 파이프라인으로 연결하는 파트입니다.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- 실제 STT 연결 시 LiveKit 서버 접속 정보
- GPT 분석 실행 시 OpenAI API Key (오프라인 데모에는 불필요)

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
| `OPENAI_API_KEY` | 서버 측 GPT API Key | 없음 |
| `OPENAI_MODEL` | `gpt-4o-mini` 또는 `gpt-4o` | `gpt-4o-mini` |
| `ANALYSIS_TIMEOUT_SECONDS` | 분석 제한 시간(초), 0 초과 120 이하 | `30` |

분석만 실행할 때는 LiveKit 접속 정보를 채울 필요가 없습니다.

## 면접 컨텍스트 분석 MVP

백엔드에서 **Transcript JSON 한 건을 전달받았다**고 가정하고 Q&A 구조화 →
GPT 요약 → 원문 인용 검증을 실행합니다. 현재 입력 형식은 BE/AI 리뷰 전 제안입니다.
실제 STT·미디어·HTTP 엔드포인트와 연결된 상태는 아닙니다.

```bash
# 네트워크·API 키 없이 구조와 근거 연결 확인 (원문 추출, GPT 요약 아님)
uv run python -m irya_ai tests/fixtures/sample_interview.json --backend extractive

# .env의 OPENAI_API_KEY 설정 후 GPT 요약
uv run python -m irya_ai tests/fixtures/sample_interview.json

# 모델 변경
uv run python -m irya_ai tests/fixtures/sample_interview.json --model gpt-4o
```

출력은 JSON입니다. 예제 입력은 가상 대화이며, 오프라인 실행 시 Q&A 2개와
지원자 발화 2개의 원문·시각이 나옵니다. `completed`는 해당 분석 실행이 끝났다는
뜻입니다. `transcript_stage: live`는 여전히 잠정 전사이며, 내용의 사실성이나
제품 전체 연동 성공을 뜻하지 않습니다.

입력·출력 계약, BE 호출 예시, 오류 처리, 검증 범위는
[컨텍스트 분석 계약](docs/context-analysis.md)을 참고하세요. 멘토 리뷰용 검증 시나리오와
실제 GPT 확인 절차는 [테스트 케이스](docs/test-cases.md)에 정리했습니다.

## Verify

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

2026-09-09 기준 자동 테스트는 54개입니다. 실제 GPT 품질 확인은 API Key가 필요한
수동 테스트이므로 자동 테스트 결과와 구분해서 기록합니다.

## Scope

이 환경은 LiveKit Agents 기반의 STT Agent와 AI 파이프라인이 공통으로 사용합니다. STT 공급자, 모델, GPU 및 self-host 여부는 검증 후 별도로 선택합니다.

## Package

| 모듈 | 역할 |
| --- | --- |
| `irya_ai.config` | 환경변수 설정 로딩 |
| `irya_ai.transcript` | 면접 Transcript 데이터 계약. 필드·시간 단위·병합 규칙은 #6·#7 리뷰 전까지 제안 상태 |
| `irya_ai.qa` | 화자 전환 기반 Q&A 묶기, 미응답 질문·연결되지 않은 발화 보존 |
| `irya_ai.summarize` | 요약 인터페이스·원문 인용 검증·오프라인 원문 추출 |
| `irya_ai.openai_summary` | GPT-4o mini/4o의 구조화된 요약 응답 처리 |
| `irya_ai.analysis` | 백엔드 입력 한 건의 분석 및 실패 시 Q&A 보존 |
| `irya_ai.evaluation` | 요약 검증용 표면 검사 — 핵심 정보 유지·비근거 수치 탐지 |

`tests/fixtures/`의 대화는 테스트용으로 지어낸 가상 데이터입니다. 실제 지원자·면접 데이터는 커밋하지 않습니다.
