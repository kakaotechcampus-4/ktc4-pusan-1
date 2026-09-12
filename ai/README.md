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
| `ELICE_API_KEY` | 서버 측 Elice STT API Key | 없음 |
| `ELICE_STT_BASE_URL` | Elice STT 배포 주소. 비공개 값이라 커밋하지 않습니다 | 없음 |
| `ELICE_STT_MODEL` | STT 모델 이름 | `whisper-large-v3` |
| `ELICE_STT_LANGUAGE` | 전사 언어. ISO 코드가 아니라 단어입니다 | `korean` |
| `ELICE_STT_TIMEOUT_SECONDS` | STT 요청 제한 시간(초), 0 초과 300 이하 | `60` |

분석만 실행할 때는 LiveKit·Elice 접속 정보를 채울 필요가 없습니다.

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
│   └── summary.py     SummaryPoint · SummaryResult · AnalysisResult
├── pipeline/          Q&A 구조화 · 근거 접지
├── analysis.py        Snapshot 한 건의 분석과 상태 처리
├── summarize.py       요약 인터페이스 · 오프라인 추출형 요약
├── openai_summary.py  OpenAI 구조화 요약
└── simulator/         대본 JSON을 STT 이벤트 스트림으로 재생
data/samples/          모의 면접 대본과 컨텍스트 샘플 (가공 데이터)
```

STT 공급자와 LLM 공급자는 아직 고정하지 않았습니다. 우선 외부 API 방향으로 시도하되, 파이프라인은 `Utterance` 스트림만 입력으로 받으므로 STT 구현은 뒤에서 교체할 수 있습니다.

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
| `speaker` | `INTERVIEWER` \| `CANDIDATE` | API 명세 `join`의 `role`과 같은 값 |
| `seq` | int | 세션 내 발화 순번. 화자와 무관하게 증가 |
| `passType` | `INTERIM` \| `FINAL` | 잠정본 / 확정본 |
| `startMs`, `endMs` | int | 세션 녹화 시작 기준 밀리초. 영상 seek에 그대로 사용 |
| `content` | string | 전사 텍스트 |
| `uncertain` | bool | STT가 확신하지 못한 발화 |
| `words` | Word[] | 단어별 타임스탬프 (선택) |
| `qaId`, `qaRole` | string? | Q&A 구조화 후 채워짐. STT는 비워둠 |

`INTERIM`은 같은 `utteranceId`로 여러 번 오고 내용이 점점 길어집니다. `FINAL`이 오면 그 발화는 확정입니다.

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
