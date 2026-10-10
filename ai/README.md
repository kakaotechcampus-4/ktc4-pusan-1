# IRYA AI

LiveKit 마이크 트랙을 Elice Whisper로 실시간 전사해 면접관에게 표시하고, 전사 기반 Q&A·근거·요약을 제공하는 파트입니다. FINAL 전사는 워커에서 BE WebSocket으로 송신하고, 꼬리질문도 같은 워커가 만들어 BE로 보냅니다. 현재 구현·수명·측정 정의는 [STT 파이프라인](docs/stt-pipeline.md), 검증 범위는 [STT 리뷰 기록](docs/stt-review.md)을 참고하세요.

## FINAL 전사 BE 송신 (#157, #137)

워커는 자막과 별도로 FINAL 발화를 세션별 `TranscriptRunner`에 넣습니다.
큐 입력은 네트워크를 기다리지 않고, 배경 태스크가 기존 `TranscriptChannel`로
`WS /internal/v1/sessions/{sessionId}/transcripts`에 전송합니다. `participantId`는
사람의 LiveKit identity(INTERVIEWER/CANDIDATE)이고 `trackId`는 트랙 SID,
`seq`는 원래 발화의 세션 정렬 키입니다. INTERIM은 보내지 않습니다.

로컬은 `BACKEND_BASE_URL`·`BACKEND_API_KEY`를 설정합니다. 주소가 없으면 자막만
유지하고 송신을 끕니다. compose는 내부 BE 주소와 `INTERNAL_API_KEY`를 전달합니다.
큐와 채널 미ACK 버퍼는 각각 `TRANSCRIPT_MAX_PENDING`개로 제한합니다(기본 각 200).
초과·영구 거부는 누락 수, NACK은 거부 ID, 종료 시 미ACK는 개수로 기록합니다.
발화 본문과 키는 로그에 넣지 않습니다. 종료는 송신 큐에 최대 5초, 이후 채널의
ACK 대기 한도를 줍니다. 이는 마지막 STT 꼬리 발화 완료나 REVIEW 시작 장벽이 아닙니다.

현재 BE develop은 text·화자·상대 시각을 저장하고 ACK하지만 `seq`·`trackId`는
무시합니다. #137의 BE 보존·조회 확장, #125의 공통 원점, #151의 재시작 ID 유일성은
후속입니다. 워커 재배정·findings 생성은 여기에 없습니다. 꼬리질문 배선(#83)은 같은
fan-out에 붙어 있고 아래 워커 절에서 설명합니다.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Elice STT 실행 시 서버 측 Elice API Key와 배포 주소
- 실시간 전사 워커 실행 시 LiveKit 서버 접속 정보 (STT는 위 Elice 값을 그대로 씁니다)
- GPT 분석 실행 시 OpenAI API Key (오프라인 데모에는 불필요)

Python은 `ai/.python-version`의 3.12를 사용합니다. 로컬에 설치되어 있지 않으면 `uv`가 필요한 버전을 설치할 수 있습니다.

## Setup

`ai` 디렉터리에서 실행합니다.

```bash
uv sync --locked
cp .env.example .env
chmod 600 .env
```

이미 `.env`를 저장했다면 복사 명령으로 덮어쓰지 않습니다. `.env`는 편집기로 값을 입력하는 설정 파일이며 실행하는 파일이 아닙니다. 실제 API Key와 Secret은 커밋하지 않습니다.

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
| `ELICE_API_KEY` | 서버 측 Elice STT API Key | 없음 |
| `ELICE_STT_BASE_URL` | Elice STT 배포 주소. 비공개 값이라 커밋하지 않습니다 | 없음 |
| `ELICE_STT_MODEL` | STT 모델 이름 | `whisper-large-v3` |
| `ELICE_STT_LANGUAGE` | 전사 언어. ISO 639-1 코드입니다 (2026-10-06 배포 교체 전에는 단어 `korean`) | `ko` |
| `ELICE_STT_TIMEOUT_SECONDS` | STT 요청 제한 시간(초), 0 초과 300 이하 | `60` |
| `BACKEND_BASE_URL` | 백엔드 `/internal/v1` 주소. 비공개 값이라 커밋하지 않습니다 | 없음 |
| `BACKEND_API_KEY` | 백엔드 내부 API 인증 키. `Authorization: Bearer`로 전달하며, compose에서는 `INTERNAL_API_KEY`와 공유합니다. 비워 두면 인증 헤더를 보내지 않습니다 | 없음 |
| `BACKEND_TIMEOUT_SECONDS` | 백엔드 HTTP 요청 제한 시간(초), 0 초과 60 이하. 전사 WebSocket의 접속 제한 시간으로도 씁니다 | `10` |
| `TRANSCRIPT_ACK_TIMEOUT_SECONDS` | 전사 프레임 ACK 대기 시간(초), 0 초과 120 이하. **백엔드와 미합의한 잠정값** | `5` |
| `TRANSCRIPT_MAX_PENDING` | ACK를 못 받은 발화를 몇 개까지 들고 있을지, 0 초과 10000 이하. **백엔드와 미합의한 잠정값** | `200` |
| `TRANSCRIPT_RECONNECT_BACKOFF_SECONDS` | 전사 WebSocket 재연결 대기(초), 0 이상 30 이하. **백엔드와 미합의한 잠정값** | `0.5` |

분석만 실행할 때는 LiveKit·Elice 접속 정보를 채울 필요가 없습니다.
Elice STT만 사용할 때는 LiveKit·OpenAI 키가 필요 없습니다. 리뷰 타임라인은 별도의
`LLM_BASE_URL`·`LLM_API_KEY`·`LLM_MODEL` 설정으로 Elice LLM을 호출합니다.
기존 `analyze` 명령의 `OPENAI_MODEL` 경로와 구분하며 `ELICE_LLM_MODEL`은 사용하지 않습니다.

## LiveKit 실시간 전사 워커

AI 워커는 LiveKit 방에 프로그램 참가자로 자동 입장해 두 사람의 마이크 트랙을 직접
구독합니다. 프레임은 mono 16kHz PCM으로 `stt/stream.py`의 `TranscriptionStream`에
들어가 발화 경계에서 잘려 Elice Whisper로 전사되고, FINAL `Utterance`는
`irya.transcript.v1` text stream으로 **면접관에게만** 전송됩니다. 별도 AI HTTP 서버나
BE 음성 중계는 없습니다. STT 제공자는 2026-09-22 회의에서 프로젝트 기본 제공 모델인
Elice Whisper로 MVP를 만들기로 정한 것을 따릅니다.

```bash
# LiveKit·Elice 값을 ai/.env에 채운 뒤 로컬 개발 실행
uv run python -m irya_ai.worker dev

# 운영 모드
uv run python -m irya_ai.worker start
```

Docker 배포에서는 `infra/docker-compose.yml`의 `ai` 서비스가 같은 작업을 합니다.

릴리스된 발화는 `irya_ai.sinks.FanOutSink`를 거쳐 면접관 자막, FINAL 전사 송신,
꼬리질문 루프에 차례로 전달됩니다. 한 소비자가 실패하면 로그만 남고 다른 소비자와 트랙은 계속 갑니다.
꼬리질문 루프(`suggestion_runner.py`)는 `BACKEND_BASE_URL`이 있을 때만 켜지며, 세션당
큐 하나·태스크 하나가 발화를 `LiveSuggestionAgent`에 넣고 채택된 제안을
`POST /internal/v1/sessions/{sessionId}/suggestions`로 보냅니다. `BACKEND_API_KEY`는 BE의
`INTERNAL_API_KEY`와 같은 값이어야 합니다. 생성기는 `LLM_BASE_URL`·`LLM_API_KEY`가 모두
있으면 프로젝트 LLM, 아니면 추출형이고, 라운드 상한은 10초이며 전송 실패는 재전송하지
않습니다. LLM·BE 호출은 이 태스크 안에서만 일어나므로 오디오 경로는 모델을 기다리지
않습니다. BE는 받은 제안을 저장합니다(#85). 면접관 화면까지 보내는 경로는 아직 없습니다.

FE·BE 없이 확인하려면 `scripts/livekit_e2e.py`를 씁니다. LiveKit 개발 서버(`livekit/livekit-server --dev`)에
워커를 붙인 뒤, 스크립트가 빈 방을 먼저 만들고 지원자로 WAV(16kHz mono, 실제 한국어 음성)를
발행하며 면접관으로 text stream을 받아 결과 JSON을 냅니다. 실행 순서는 스크립트 독스트링에 있습니다.
Elice STT만은 실제 배포가 필요하고, 첫 요청은 배포의 콜드 스타트를 그대로 겪습니다.

`ELICE_STT_BASE_URL`이 비어 있으면 워커는 방에 남지 않고 떠납니다. 작업이 시작되면
접속과 나란히 무음 프로브로 `warm_up`을 한 번 보내 배포의 콜드 스타트를 첫 발화 앞으로
당기려 하며, 실패해도 전사는 계속됩니다.

LiveKit text stream에는 영구 저장이 없으므로 이 경로는 면접 중 자막 전용입니다.
녹화 기반 재전사·면접 종료 후 저장은 아직 연결되지 않았습니다. 요청 한 건이 실패하면
스트림이 그 세그먼트만 버리고 이어 가고, 워커 자체가 실패하면 `stream.degraded`만
보내며 LiveKit 통화와 녹화는 종료하지 않습니다.

자막의 `at`은 현재 방에서 처음 확인한 사람의 LiveKit 입장 시각을 기준으로 한 잠정
표시값입니다. 녹화 0프레임과의 offset 및 최종 seek 기준은 아직 팀 계약이 아니므로,
BE에는 이 잠정 원점을 기준으로 한 상대 시각을 전달합니다. 녹화 영상 탐색 기준과의 정합성은 후속 검증이 필요합니다.

### 로그와 배포 주소

`httpx`는 요청 한 건마다 대상 URL을 INFO로, `httpcore`는 접속 호스트를 DEBUG로 남깁니다. 기본값인 `LOG_LEVEL=INFO`에서 그대로 두면 비공개인 `ELICE_STT_BASE_URL`이 애플리케이션 로그에 찍힙니다. `EliceSttClient`는 생성 시점에 자기 `base_url`의 호스트를 `irya_ai.stt.http_logging`에 등록해, 그 두 라이브러리의 기록에서 해당 호스트만 `<redacted-host>`로 가립니다. `build_client()`로 만들든 직접 만든 `httpx.AsyncClient`를 넘기든 동일하며, 호출자가 로깅을 따로 설정할 필요는 없습니다. 메서드·경로·상태 코드와 다른 호스트의 로그는 건드리지 않습니다. `BackendClient`도 생성 시점에 같은 방식으로 `BACKEND_BASE_URL`의 호스트를 등록합니다. 전사 WebSocket은 `aiohttp`를 쓰는데, 이 라이브러리는 요청 한 건씩 남기지는 않지만 연결을 닫다 실패하거나 쿠키를 받을 때 같은 호스트를 기록합니다. 그래서 `irya_ai.transcripts.TranscriptChannel`도 생성 시점에 자기 URL의 호스트를 등록하고, `aiohttp`의 로거 여섯 개가 같은 필터를 받습니다.

보호 범위는 등록한 호스트가 포함된 `httpx`·`httpcore` 메시지까지입니다. `protect_host()`는 다른 라이브러리나 애플리케이션 자체 로거에 필터를 설치하지 않으므로, 그런 로그는 해당 경로에서 별도로 가려야 합니다. 호스트 등록은 프로세스 동안 유지되며 `clear_protected_hosts()`는 요청 중 호출하지 않습니다. 키 값을 이 장치에 넘기지 않습니다. 기본 요청의 `Authorization` 값과 본문은 라이브러리가 기록하지 않지만, httpcore DEBUG에는 응답 헤더가 나타날 수 있습니다. 이 필터를 임의 헤더·경로·쿼리·사용자 정의 로그의 비밀값 제거 장치로 사용하지 않습니다.

### 전사 연결 종료 코드

BE는 `1000`을 전사 송신 종료 신호로 사용합니다(#164). 워커의 실제 종료는
ACK 대기 후 `1000`으로 닫고, ACK 지연·정정·연결 교체에 따른 재접속은
`4001`로 닫습니다. 재접속을 면접 후 분석 시작 신호로 해석하지 않습니다.

## 면접 컨텍스트 분석 MVP

백엔드에서 **Transcript JSON 한 건을 전달받았다**고 가정하고 Q&A 구조화 →
GPT 요약 → 원문 인용 검증을 실행합니다. 현재 입력 형식은 BE/AI 리뷰 전 제안입니다.
실제 STT·미디어·HTTP 엔드포인트와 연결된 상태는 아닙니다.

```bash
# 네트워크·API 키 없이 구조와 근거 연결 확인 (원문 추출, GPT 요약 아님)
uv run irya-ai analyze tests/fixtures/sample_interview.json --backend extractive

# .env의 OPENAI_API_KEY 설정 후 GPT 요약
uv run irya-ai analyze tests/fixtures/sample_interview.json

# 모델 변경
uv run irya-ai analyze tests/fixtures/sample_interview.json --model gpt-4o
```

출력은 JSON입니다. 예제 입력은 가상 대화이며, 오프라인 실행 시 Q&A 2개와
지원자 발화 2개의 원문·시각이 나옵니다. `completed`는 해당 분석 실행이 끝났다는
뜻입니다. `transcriptStage: LIVE`는 여전히 잠정 전사이며, 내용의 사실성이나
제품 전체 연동 성공을 뜻하지 않습니다.

입력·출력 계약, BE 호출 예시, 오류 처리, 검증 범위는
[컨텍스트 분석 계약](docs/context-analysis.md)을 참고하세요. 멘토 리뷰용 검증 시나리오와
실제 GPT 확인 절차는 [테스트 케이스](docs/test-cases.md)에 정리했습니다.

## 면접 전 사전 가공 (#155, #137)

JD·인재상·이력서 본문으로 면접에서 확인할 역량(`Competency`)과 이력서 주장
(`ResumeClaim`)을 만듭니다. #137의 `PREP` 작업이 부를 본체이고, 결과는
`PUT /internal/v1/interviews/{interviewId}/prep`(#162) 본문에 그대로 실립니다.

```bash
uv run irya-ai prep data/samples/context_backend_junior.json                       # Luna
uv run irya-ai prep data/samples/context_backend_junior.json --backend extractive  # 기준선
```

- 모델이 쓰는 것은 역량의 이름·필수 여부·설명과 주장의 인용·항목뿐입니다. ID는
  코드가 내용 해시로 붙입니다(`clm_`·`cpt_` + 8자). 재가공해도 내용이 같으면 ID가 같습니다.
- 이력서 주장의 인용은 이력서 본문에 글자 그대로 있어야 합니다. 기준은 타임라인·
  꼬리질문과 같은 NFC + 공백 축약이고, 줄 앞의 글머리 기호만 뗍니다. 통과하지 못한
  주장은 통째로 버립니다. 역량에는 인용을 요구하지 않습니다.
- 역량 최대 6개(3개 미만이면 경고), 주장 최대 12개. 이력서가 없으면 주장 없이
  `completed`, 역량이 하나도 안 남으면 `failed`입니다.
- 입력은 JD·이력서 각각 12,000자에서 자르고 `INPUT_TRUNCATED` 경고를 남깁니다.
  게이트웨이의 비스트리밍 응답 상한에 맞춰 `max_completion_tokens`는 2,000입니다.
- 지원자 이름과 이력서 본문은 로그에 남기지 않습니다. 탈락 사유는 순번과 이유만 적습니다.
- 환경변수는 리뷰 타임라인과 같은 `LLM_BASE_URL`·`LLM_API_KEY`·`LLM_MODEL`입니다.
  실호출 결과는 [docs/prep-eval.md](docs/prep-eval.md)에 있습니다.

## 사전 가공 폴러 (#176, #137)

분석은 BE가 DB 행으로 남긴 할 일을 AI가 가져가 처리합니다(#137). `irya-ai-poller`는
`GET /internal/v1/jobs/pending`으로 가장 오래된 `PREP` 작업을 받아 그 세션의 컨텍스트
(`GET /internal/v1/sessions/{sessionId}/context`)를 읽고, 위의 사전 가공을 돌려
`PUT /internal/v1/interviews/{interviewId}/prep`에 넣습니다(#162).

```bash
uv run irya-ai-poller        # BACKEND_BASE_URL·BACKEND_API_KEY, LLM_* 필요
```

- **한 번에 한 작업.** BE의 할 일 조회는 작업을 잡아 두지 않아 결과를 넣기 전까지
  같은 작업을 계속 내줍니다. 그래서 한 작업을 끝까지 처리한 뒤 다시 묻습니다.
- **`requestedAt`을 그대로 돌려보냅니다.** 할 일 응답의 값을 PUT 본문에 붙이고,
  409(`PREP_OUTDATED`)면 그 결과는 버리고 다음 할 일로 갑니다(이력서 재업로드).
- **다시 될 수 있는 실패는 저장하지 않습니다.** `failed`는 BE에 FAILED로 남아 큐에서
  빠지므로, 모델 타임아웃·429처럼 `retryable`인 실패는 `PREP_RETRY_AFTER_SECONDS`
  (기본 30초) 동안 그 작업을 쉬었다가 다시 시도합니다. 반복될 실패(역량 0개, 거부)는
  바로 FAILED로 저장합니다. 컨텍스트를 읽을 수 없는 작업은 10분 동안 건너뛰고 BE의
  한도(기본 6분)가 먼저 FAILED로 넘깁니다.
- 컨텍스트 응답의 `utterances`는 떼고 `InterviewContext`로 읽습니다. `REVIEW` 작업은
  #164·#170이 붙기 전까지 건너뜁니다.
- 작업마다 `agent=`(모델 호출)와 `total=`(조회부터 저장까지) 소요를 INFO로 남깁니다.
  이력서 본문과 지원자 이름은 로그에 없습니다. LLM이 없으면 추출형 기준선으로 돌되
  경고를 남깁니다.
- compose에서는 `ai`와 같은 이미지를 쓰는 `ai-poller` 서비스로 뜹니다.

## 리뷰 타임라인 (면접 기록 화면)

STT가 청크마다 쌓아 둔 `Utterance` JSON을 면접 종료 후 한꺼번에 읽어, 면접 기록 화면(S3)의
타임라인 마커와 질문별 답변 한 줄 요약을 만듭니다. Q&A 묶기(`segment_qa`)와 인용 검증
(`locate_quote`)은 기존 코드를 그대로 쓰고, 모델은 `label`·`answer`·인용만 씁니다.
시각·질문 원문·ID는 코드가 `QAPair`에서 채우므로 모델이 마커를 옮기거나 질문을 바꿀 수 없습니다.

```bash
# 모델 없이 파이프라인 확인 (답변 첫 문장을 그대로 인용)
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json --backend extractive

# .env의 LLM_BASE_URL / LLM_API_KEY 설정 후 프로젝트 LLM(gpt-5.6-luna) 호출
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json

# FE `Moment` 형태(atSec)로만 출력
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json --frontend
```

입력은 `Utterance` JSON 배열, JSON Lines(`simulate --json` 출력), 또는 `TranscriptSnapshot`
파일입니다. 기본 출력 `moments[]`는 `momentId`·`atMs`·근거를 포함하는 AI 계약이며,
`--frontend` 출력은 FE `Moment`의 `id`·`atSec`·`label`·`question`·`answer` 형태로 변환합니다.
인용이 지원자 발화 원문에 없는 항목은 통째로 빠지며 `rejectedMomentCount`와 `rejections`에 남습니다.
Moment는 기본 최대 8개이며 `--max-moments`는 1~8 범위만 허용합니다. 질문이 더 많으면
답변이 긴 순으로 고릅니다. 근거를 확인한 항목이 5개 미만이면 경고를 남기고 실제 개수만 반환합니다.

프로젝트 LLM은 OpenAI 호환 게이트웨이(Elice ML API)이며 **지원 목록 밖 파라미터를 400으로
거절**합니다. 실호출 절차와 결과는 [타임라인 검증 기록](docs/timeline-eval.md)에 적습니다.

## Verify

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 구조

```
src/irya_ai/
├── config.py          환경변수 설정
├── cli.py             로컬 개발용 CLI (irya-ai)
├── worker.py          LiveKit 방 자동 입장과 트랙별 STT 작업 (irya-ai-worker)
├── schemas/           파이프라인 입출력 계약 (Pydantic)
│   ├── transcript.py  Track · Utterance · Word · TranscriptSnapshot
│   ├── context.py     Company · JobDescription · Competency · Rubric · Candidate · Resume · ResumeClaim
│   ├── analysis.py    QAPair · Finding · SuggestedQuestion · ReviewReport
│   ├── summary.py     SummaryPoint · SummaryResult · AnalysisResult
│   ├── timeline.py    Moment · TimelineResult (리뷰 타임라인)
│   ├── prep.py        PrepDraft · PrepResult (면접 전 사전 가공)
│   └── jobs.py        PendingJob (BE 할 일 큐)
├── pipeline/          Q&A 구조화 · 근거 접지
├── stt/               LiveKit 브리지 · PCM 청킹 · Elice HTTP · 세션 정렬 · 비동기 전사 스트림
├── analysis.py        Snapshot 한 건의 분석과 상태 처리
├── summarize.py       요약 인터페이스 · 오프라인 추출형 요약
├── openai_summary.py  OpenAI 구조화 요약
├── timeline.py        청크 병합 → Q&A → 검증된 Moment (리뷰 타임라인)
├── openai_timeline.py 프로젝트 LLM(Luna/Terra) 타임라인 초안
├── prep.py            JD·이력서 초안 검증 → Competency · ResumeClaim (면접 전 사전 가공)
├── openai_prep.py     프로젝트 LLM(Luna) 사전 가공 초안
├── prep_poller.py     BE 할 일 큐 → PrepAgent → 결과 저장 (irya-ai-poller)
├── backend.py         BE 내부 API(/internal/v1) HTTP 클라이언트
└── simulator/         대본 JSON을 STT 이벤트 스트림으로 재생
data/samples/          모의 면접 대본과 컨텍스트 샘플 (가공 데이터)
```

실시간 자막과 STT는 Elice Whisper입니다 (2026-09-22 회의: 프로젝트 기본 제공 모델로 MVP).
기존 요약은 OpenAI 경로를, 리뷰 타임라인은 별도의 Elice LLM 경로를 사용합니다.
분석 모듈은 `TranscriptSnapshot`을 받습니다. 워커의 `Utterance`를 꼬리질문 에이전트와 BE 전송에
잇는 배선은 `worker.py`에 있습니다(#83, #157).

2026-09-13 AI 회의에서 **전사 문장의 LLM 교정·재작성 후처리를 제외**하기로 했습니다.
Q&A 구조화·근거 검증·면접 요약은 별도 분석 범위로 유지하고 자막 표시 전에 기다리지 않습니다.
결정 범위와 지연 측정 기준은 [STT 파이프라인](docs/stt-pipeline.md#2026-09-13-ai-회의-결정-전사-교정-제외)을 따릅니다.

## 스키마

필드 이름은 TechSpec 데이터 모델(snake_case)을 따르고, JSON으로 내보낼 때는 camelCase alias를 씁니다. 두 형태 모두 읽을 수 있습니다.

```python
from irya_ai.schemas import Utterance

u = Utterance.model_validate(
    {
        "utteranceId": "utt_014",
        "sessionId": "ses_123",
        "trackId": "trk_candidate",
        "speaker": "CANDIDATE",
        "seq": 14,
        "startMs": 768000,
        "endMs": 772400,
        "content": "조회가 많은 상품 API 앞에 Redis를 뒀습니다.",
    }
)
u.start_ms  # 768000
u.model_dump(
    by_alias=True
)  # {"utteranceId": ..., "startMs": ..., "passType": "FINAL", ...}
```

### Utterance (STT → 분석 입력)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `utteranceId` | string | `utt_014` |
| `sessionId` | string | `ses_123`. API 명세의 Session ID |
| `trackId` | string | `trk_interviewer` / `trk_candidate` |
| `speaker` | `INTERVIEWER` \| `CANDIDATE` | 전사 출처. join 권한 `role`과 표기는 같지만 별도 개념 |
| `seq` | int | 세션 내 정렬 키. STT 매핑은 희소하므로 개수·연속 번호로 쓰지 않음 |
| `passType` | `INTERIM` \| `FINAL` | 청크의 중간/최종 응답. 인터뷰 전사 확정 단계와 별개 |
| `startMs`, `endMs` | int | 공통 세션 기준 상대 밀리초. 실제 t=0은 미확정이며 STT caller가 트랙 offset을 제공해야 함. 녹화 정렬이 없어 영상 seek 값으로 보장하지 않음 |
| `content` | string | 전사 텍스트 |
| `uncertain` | bool | STT가 확신하지 못한 발화 |
| `words` | Word[] | 단어별 타임스탬프 (선택) |
| `qaId`, `qaRole` | string? | Q&A 구조화 후 채워짐. STT는 비워둠 |

시뮬레이터는 같은 `utteranceId`의 INTERIM/FINAL을 만듭니다. 현재 Elice 경로는 청크별 FINAL만 생성하며 LIVE 스냅샷은 잠정본입니다. FINAL 수정본은 같은 ID의 전체 문자열을 교체합니다. 상세 규칙은 [분석 계약](docs/context-analysis.md)을 따릅니다.

### Finding (분석 출력)

`GAP` 타입을 제외한 모든 Finding은 `evidenceQuote`와 `evidenceUtteranceId`를 함께 가져야 합니다. `evidenceQuote`는 해당 발화 `content`의 부분 문자열이어야 하며, 전사에 없는 인용은 파이프라인에서 폐기합니다 (TechSpec DEV1).

## 시뮬레이터

실제 STT 없이 파이프라인을 개발·테스트하기 위해 대본 JSON을 `Utterance` 스트림으로 재생합니다.

```bash
uv run irya-ai validate data/samples/*.json
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json --interim
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json --realtime --speed 20
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json --json
```

```
# 백엔드 신입 모의 면접 1 - 캐시 설계와 협업 (ses_sample_01, 03:29.000)
  [00:00.000 - 00:05.200] INTERVIEWER utt_000 안녕하세요. 편하게 앉으시고, ...
~ [00:05.800 - 00:15.150] CANDIDATE   utt_001 안녕하세요, 정민호입니다. 컴퓨터공학을 ...
  [00:05.800 - 00:24.500] CANDIDATE   utt_001 안녕하세요, 정민호입니다. 컴퓨터공학을 전공했고 ...
```

`~`로 시작하는 줄이 `INTERIM`입니다. 겹치는 발화(끼어들기)는 도착 시각 순으로 섞여서 나옵니다.

코드에서 쓸 때:

```python
from irya_ai.simulator import TranscriptSimulator, load_script

sim = TranscriptSimulator(load_script("data/samples/transcript_backend_junior_01.json"))
for u in sim.events():  # 동기, 페이싱 없음
    ...
async for u in sim.stream(realtime=True, speed=10):  # 비동기, 타임스탬프대로 재생
    ...
sim.finals()  # FINAL만 seq 순으로
```

### 대본 형식

```json
{
  "sessionId": "ses_sample_01",
  "title": "백엔드 신입 모의 면접 1",
  "description": "어떤 케이스를 담았는지",
  "turns": [
    { "speaker": "INTERVIEWER", "startMs": 0,    "endMs": 5200,  "content": "..." },
    { "speaker": "CANDIDATE",   "startMs": 5800, "endMs": 24500, "content": "...", "uncertain": false }
  ]
}
```

`turns`는 `startMs` 오름차순이어야 하고, 끼어들기를 표현하기 위해 구간 겹침은 허용합니다.

### 샘플 데이터

| 파일 | 내용 |
| --- | --- |
| `context_backend_junior.json` | 회사·JD·역량 4개·평가기준·지원자·지원서 주장 4개 |
| `transcript_backend_junior_01.json` | 수치를 묻는 후속 질문이 필요한 답변, 지원서와 다른 설명(리드 → 실제로는 공동 작업) |
| `transcript_backend_junior_02.json` | 면접관 끼어들기(구간 겹침), `uncertain` 발화, 지원서 주장 중 언급이 전혀 없는 항목 |

모두 가공 데이터입니다. 실제 지원서나 면접 녹취는 이 폴더에 넣지 않습니다.

실제 GPT 품질 확인은 API Key가 필요한 수동 테스트이므로 자동 테스트 결과와
구분해서 기록합니다. STT 공급자, 모델, GPU 및 self-host 여부는 검증 후 별도로
선택합니다.
