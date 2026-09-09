# 면접 컨텍스트 분석 MVP

작성 기준: 2026-09-08. **BE/AI 연동 계약 제안이며 팀 합의 전이다.**
백엔드가 전사 한 건을 전달한 상황에서 독립적으로 실행하는 분석 모듈이다.

- 작업 근거: [9/8 회의록](https://app.notion.com/p/9-8-3db6470e1c8583179410810820457966)의 stub/mock 데이터 기반 면접 context 분석 Agent MVP.
- 관련 작업: [요약 #6](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/6), [STT #7](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/7).
- 이번 구현 선택: GPT API 사용, 기본 `gpt-4o-mini`, 설정 또는 실행 인자로 `gpt-4o` 선택.
- 제품 원칙: [테크스펙](https://app.notion.com/p/a566470e1c8582e8a143813844a5d374). AI는 발언을 정리하고 근거를 연결한다. 평가·점수·순위·합격 판단을 생성하지 않는다.

## 처리 범위

```text
백엔드가 전달한 Transcript 스냅샷
  → 입력 검증·발화 ID별 최종 수정본 선택·seq 순 정렬
  → 연속된 면접관 발화 + 뒤따르는 지원자 발화를 Q&A로 묶기
  → GPT에 발화 ID·화자·본문 전달 → 요약 항목·인용 반환
  → 인용·화자·수치 검사 → 통과한 항목에 원문 시각 부착
  → Q&A + 요약 + 근거 + 처리 상태 반환
```

샘플 입력 완료 후 1회 분석한다. 내부에는 세션 저장소나 스트리밍 상태가 없다.
STT 중간 결과의 갱신마다 GPT를 호출하지 않는다. 이후 STT 연동 시 호출 시점은
BE/AI가 합의해야 한다. 재호출은 해당 스냅샷의 전체 결과를 다시 만든다.

## 입력 계약

실행 가능한 입력: [sample_interview.json](../tests/fixtures/sample_interview.json).
최상위 객체는 `TranscriptSnapshot`이며 별도의 HTTP 경로나 응답 봉투를 가정하지 않는다.
JSON 필드는 camelCase를 기본으로 쓰고 Python에서는 같은 이름의 snake_case도 받는다.

| 필드 | 의미 |
| --- | --- |
| `sessionId` | 빈 문자열이 아닌 세션 식별자 |
| `stage` | `LIVE`(기본값) 또는 `REALIGNED`; 누락 시 보수적으로 잠정본으로 표시 |
| `utterances` | 발화 배열, 빈 배열 허용 |
| `utteranceId` | 발화 식별자; 동일 발화의 수정본은 동일 ID |
| `trackId`, `speaker` | 트랙 ID와 `INTERVIEWER` 또는 `CANDIDATE` 역할 |
| `seq` | 세션 안에서 발화를 정렬하는 순번 |
| `content` | **전체 발화 문자열**; 토큰 델타 아님 |
| `startMs`, `endMs` | 세션 시작 기준 상대 밀리초; 0 이상, 끝 ≥ 시작 |
| `passType` | `INTERIM` 또는 `FINAL`; 배치 전사 단계와 다른 개념 |

동일 ID가 여러 번 있으면 배열에서 **마지막 `passType: FINAL` 전체 문자열**을 쓴다.
그 뒤에 INTERIM이 도착해도 확정본을 덮지 않는다. 같은 ID의 세션·트랙·화자·seq·
시작 시각은 변경할 수 없다. 본문·종료 시각·pass 상태는 정정할 수 있다.
BE가 수정 순서를 보장해야 하며,
순서가 없는 이벤트를 안전하게 병합하는 규칙은 이번 범위에 없다.

라이브 STT의 `passType: FINAL`은 발화가 끝났다는 뜻이다. `stage: LIVE`인 이상
분석에는 `PROVISIONAL_TRANSCRIPT` 경고가 붙는다. 녹화 기반 정렬이 끝난 확정본은
BE가 명시적으로 `stage: REALIGNED`로 전달한다. 모델이 상태를 결정하지 않는다.

Q&A ID는 첫 확정 질문의 `utteranceId`에서 파생한다. live → realigned에서도 같은
논리 발화 ID가 유지된다는 전제이며, 발화 경계가 합쳐지거나 나뉘는 경우의 정책은
[#7](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/7)에서 확인 중이다.

## 출력 계약

| 필드 | 의미 |
| --- | --- |
| `sessionId`, `transcriptStage` | 입력 식별자와 전사 단계 |
| `status` | `completed`, `partial`, `failed`, `empty` |
| `qaPairs` | 질문·답변 원문, 각각의 발화 ID 배열, 시작/종료 밀리초 |
| `unpairedUtteranceIds` | 앞선 면접관 질문 없이 등장한 지원자 발화 ID; 누락하지 않고 별도 보존 |
| `summaryResult` | 성공 시 요약 객체; 실패·분석할 지원자 발화 없음이면 `null` |
| `summaryResult.points` | `text`와 `evidence[]`로 구성된 요약 항목 |
| `evidence` | 원문 `quote`, `utteranceId`, `speaker`, 발화 구간의 시작/종료 밀리초 |
| `summaryResult.summary`, `keyPoints` | 검증을 통과한 `points`에서 파생한 표시용 텍스트 |
| `sourceUtteranceIds` | 실제 인용한 발화만 중복 제거; 전사 전체 ID를 근거처럼 넣지 않음 |
| `model` | SDK 응답의 실제 모델 ID, 오프라인은 `extractive-baseline` |
| `rejectedPointCount` | 검증에서 제외한 요약 항목 수 |
| `warnings`, `error`, `elapsedMs` | 경고, 안전한 오류 코드·재시도 가능 여부, 전체 분석 소요 시간 |

시각은 **인용을 포함한 발화 전체 구간**이다. 단어 수준 시각이나 영상 seek 정확도를
보장하지 않는다. 미응답 질문은 답변을 빈 문자열·빈 ID 배열로 반환한다.
질문 없이 등장한 지원자 발화도 GPT 입력에는 포함한다.

## 백엔드에서 호출

```python
from openai import AsyncOpenAI

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.config import Settings
from irya_ai.openai_summary import OpenAISummarizer
from irya_ai.schemas import TranscriptSnapshot


async def analyze_backend_payload(payload: dict) -> dict:
    transcript = TranscriptSnapshot.model_validate(payload)
    settings = Settings()
    if not settings.openai_api_key.get_secret_value().strip():
        raise ValueError("OPENAI_API_KEY_MISSING")
    async with AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url="https://api.openai.com/v1",
        timeout=settings.analysis_timeout_seconds,
        max_retries=0,
    ) as client:
        agent = ContextAnalysisAgent(
            OpenAISummarizer(client, model=settings.openai_model),
            timeout_seconds=settings.analysis_timeout_seconds,
        )
        result = await agent.analyze(transcript)
    return result.model_dump(mode="json", by_alias=True)
```

이 예시는 AI 패키지가 설치된 Python 프로세스에서 호출하는 함수이다.
별도 프로세스로 배포할 때의 REST·큐·WebSocket 계약은 아직 구현하지 않았다.
서버 연동 시 입력 오류를 요청 오류로 매핑하고, 분석 실패를 미디어 종료로
연결하지 않아야 한다. 분석 모듈 자체에는 통화·녹화 제어 코드가 없다.

## GPT 응답과 근거 검증

OpenAI Responses의 [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)를
이용한다. 프롬프트는 면접 발화를 명령이 아닌 데이터로 취급하고,
지원자 발언에 근거한 요약만 요청한다. 모델은 요약문·발화 ID·인용만 생성한다.
세션 ID, 화자, 시각은 입력에서 가져온다. 요청에는 `store=False`를 설정한다.
이 옵션이 모든 종류의 공급자 로그 보관을 없앤다는 뜻은 아니다.

다음 경우 **요약 항목 전체를 제외**한다.

- 내용이나 인용이 비어 있음.
- 존재하지 않는 발화 ID, 중간 전사만 있는 발화, 면접관 발화를 인용함.
- NFC 정규화·연속 공백 축소 후에도 `quote`가 해당 원문에 부분 문자열로 존재하지 않음.
- 요약문 수치가 해당 항목의 인용문에 없음.

일부만 통과하면 `partial`, 모두 제외되거나 유효 항목이 없으면 `failed`로
반환한다. 실패 시 Q&A는 남기고 성공한 요약처럼 대체 값을 만들지 않는다.

## 실패 처리

| 상황 | 상태 또는 오류 코드 | 재시도 |
| --- | --- | --- |
| 확정된 지원자 발화 없음 | `empty` | 새 발화가 들어온 뒤 |
| 제한 시간 초과 | `LLM_TIMEOUT` | 가능 |
| 429 응답 | `LLM_RATE_LIMITED` | 한도 확인 후 |
| 연결 실패 | `LLM_UNAVAILABLE` | 가능 |
| HTTP 오류 | `LLM_API_ERROR` | 5xx만 가능 |
| JSON·스키마 오류 | `LLM_INVALID_OUTPUT` | 자동 재시도 안 함 |
| 미완료 출력·거절/구조화 결과 없음 | `LLM_INCOMPLETE_OUTPUT` / `LLM_NO_STRUCTURED_OUTPUT` | 자동 재시도 안 함 |
| 근거 있는 요약 항목 없음 | `NO_GROUNDED_SUMMARY` | 입력·프롬프트 확인 |

자동 재시도는 하지 않으며 분석 전체 제한 시간은 기본 30초다. 공급자의 원본 오류
본문과 API 키를 결과에 넣지 않는다. 호출자의 작업 취소는 그대로 전파한다.
CLI 종료 코드는 성공·빈 입력 `0`, 분석 실패·일부 항목 제외 `1`, 입력·설정 오류 `2`다.
`partial`에서도 JSON에는 통과한 항목이 포함된다.

## 검증 및 현재 한계

- `pytest`는 가상 대화, 수정본·중간본, 중복 ID, Q&A 분할, 세션 격리, 인용·수치 검증,
  시간 초과, HTTP 오류, 거절, 미완료·잘못된 응답, CLI를 검증한다.
- OpenAI 연결 테스트는 **실제 SDK + HTTP MockTransport**를 사용한다. 요청 직렬화와
  응답 파싱을 확인하지만 GPT의 실제 품질·계정 접근·성능을 증명하지 않는다.
- 오프라인 실행은 지원자 발화를 원문 그대로 추출한다. 요약 품질 측정이 아니다.
- 기계적인 인용 검증은 요약의 의미가 인용으로 뒷받침되는지까지 증명하지 못한다.
  숫자가 같아도 의미가 다를 수 있고, 수치 표기가 달라지면 과도하게 제외할 수 있다.
- Q&A는 화자 전환과 짧은 맞장구 휴리스틱을 사용한다. 실제 발화에서 새 질문과
  맞장구를 완전히 구별한다고 보장하지 않는다.
- GPT 실호출은 프로젝트 로컬 키 설정 후 위 README 명령으로 별도 확인해야 한다.
- FE/BE/STT 실제 연동, 라이브 갱신, JD/지원서 검색, 후속 질문, 리포트·Timeline UI,
  녹화·영구 저장·배포는 이번 MVP에 포함하지 않았다.

## 팀 리뷰에서 정할 것

1. 입력 필드명과 시간 기준, 스냅샷 또는 델타 방식, 수정 순서와 배치 확정본 표시.
2. 분석을 호출할 시점과 Q&A 분할의 맞장구·중복발화 처리.
3. 결과 전달 경로, `partial` 표시 방식, 실패 재시도 주체.
4. 실제 샘플의 핵심 정보 유지·의미 왜곡·모델별 지연 측정.

#6의 팀 리뷰·합의 완료 조건은 코드 테스트만으로 완료 처리하지 않는다.
