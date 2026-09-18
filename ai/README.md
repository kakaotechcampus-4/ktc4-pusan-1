# IRYA AI

PCM 청킹·Elice STT와 전사 기반 Q&A·근거·요약을 제공하는 파트입니다. LiveKit 입력과 BE/FE 전송은 아직 연결되지 않았습니다. 현재 구현·수명·측정 정의는 [STT 파이프라인](docs/stt-pipeline.md), 검증 범위는 [STT 리뷰 기록](docs/stt-review.md)을 참고하세요.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Elice STT 실행 시 서버 측 Elice API Key와 배포 주소
- 향후 LiveKit 입력 연결 시 LiveKit 서버 접속 정보
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
| `ELICE_STT_LANGUAGE` | 전사 언어. ISO 코드가 아니라 단어입니다 | `korean` |
| `ELICE_STT_TIMEOUT_SECONDS` | STT 요청 제한 시간(초), 0 초과 300 이하 | `60` |
| `CARTESIA_API_KEY` | 서버 측 Cartesia 스트리밍 STT API Key | 없음 |
| `CARTESIA_STT_MODEL` | 스트리밍 STT 모델 이름. `ink-whisper` 외에는 거부합니다 | `ink-whisper` |
| `CARTESIA_STT_LANGUAGE` | 스트리밍 전사 언어. Elice와 달리 ISO 코드입니다 | `ko` |

분석만 실행할 때는 LiveKit·Elice 접속 정보를 채울 필요가 없습니다.
Elice STT만 사용할 때는 LiveKit·OpenAI 키가 필요 없습니다. 리뷰 타임라인은 별도의
`LLM_BASE_URL`·`LLM_API_KEY`·`LLM_MODEL` 설정으로 Elice LLM을 호출합니다.
기존 `analyze` 명령의 `OPENAI_MODEL` 경로와 구분하며 `ELICE_LLM_MODEL`은 사용하지 않습니다.

Cartesia는 배치 HTTP가 아니라 WebSocket 스트리밍이라 Elice STT와 함께 쓰는 값이 아니라
둘 중 하나를 고르는 값입니다. `CARTESIA_STT_MODEL`은 `ink-whisper`만 받습니다.
`ink-2`는 영어 전용이라 한국어를 영어 음절로 옮기고 구간 시각을 전혀 돌려주지 않아,
그대로 받으면 면접 전체가 0초에 놓인 채 값은 숫자처럼 보입니다. 엔드포인트는 Cartesia의
공개 호스트라 `ELICE_STT_BASE_URL`과 달리 비공개 값이 아니고, 아래 `protect_host()`
장치의 대상도 아닙니다.

### 로그와 배포 주소

`httpx`는 요청 한 건마다 대상 URL을 INFO로, `httpcore`는 접속 호스트를 DEBUG로 남깁니다. 기본값인 `LOG_LEVEL=INFO`에서 그대로 두면 비공개인 `ELICE_STT_BASE_URL`이 애플리케이션 로그에 찍힙니다. `EliceSttClient`는 생성 시점에 자기 `base_url`의 호스트를 `irya_ai.stt.http_logging`에 등록해, 그 두 라이브러리의 기록에서 해당 호스트만 `<stt-deployment>`로 가립니다. `build_client()`로 만들든 직접 만든 `httpx.AsyncClient`를 넘기든 동일하며, 호출자가 로깅을 따로 설정할 필요는 없습니다. 메서드·경로·상태 코드와 다른 호스트의 로그는 건드리지 않습니다.

보호 범위는 등록한 호스트가 포함된 `httpx`·`httpcore` 메시지까지입니다. `protect_host()`는 다른 라이브러리나 애플리케이션 자체 로거에 필터를 설치하지 않으므로, 그런 로그는 해당 경로에서 별도로 가려야 합니다. 호스트 등록은 프로세스 동안 유지되며 `clear_protected_hosts()`는 요청 중 호출하지 않습니다. 키 값을 이 장치에 넘기지 않습니다. 기본 요청의 `Authorization` 값과 본문은 라이브러리가 기록하지 않지만, httpcore DEBUG에는 응답 헤더가 나타날 수 있습니다. 이 필터를 임의 헤더·경로·쿼리·사용자 정의 로그의 비밀값 제거 장치로 사용하지 않습니다.

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
├── schemas/           파이프라인 입출력 계약 (Pydantic)
│   ├── transcript.py  Track · Utterance · Word · TranscriptSnapshot
│   ├── context.py     Company · JobDescription · Competency · Rubric · Candidate · Resume · ResumeClaim
│   ├── analysis.py    QAPair · Finding · SuggestedQuestion · ReviewReport
│   ├── summary.py     SummaryPoint · SummaryResult · AnalysisResult
│   └── timeline.py    Moment · TimelineResult (리뷰 타임라인)
├── pipeline/          Q&A 구조화 · 근거 접지
├── stt/               PCM 청킹 · Elice HTTP · 세션 정렬 · 비동기 전사 스트림
├── analysis.py        Snapshot 한 건의 분석과 상태 처리
├── summarize.py       요약 인터페이스 · 오프라인 추출형 요약
├── openai_summary.py  OpenAI 구조화 요약
├── timeline.py        청크 병합 → Q&A → 검증된 Moment (리뷰 타임라인)
├── openai_timeline.py 프로젝트 LLM(Luna/Terra) 타임라인 초안
└── simulator/         대본 JSON을 STT 이벤트 스트림으로 재생
data/samples/          모의 면접 대본과 컨텍스트 샘플 (가공 데이터)
```

현재 STT 구현은 Elice Whisper를 시험합니다. 기존 요약은 OpenAI 경로를, 리뷰 타임라인은
별도의 Elice LLM 경로를 사용합니다. 이것을 팀의 최종 모델 선정으로 간주하지 않습니다.
분석 모듈은 `TranscriptSnapshot`을 받으며 STT `Utterance`를 수집·전달하는 통합 계층은 후속 작업입니다.

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
