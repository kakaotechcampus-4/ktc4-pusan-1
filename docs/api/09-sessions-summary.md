# 면접 요약 (제안)

> ⚠️ **아직 명세에 없는 엔드포인트입니다.** 이슈 [#6](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/6)
> (대화 컨텍스트 요약)의 결과를 FE 가 받으려면 통로가 필요해서, 프론트에서 먼저 제안합니다.
> 출력 형식은 #6 에서 정의될 예정이므로 아래 `content` 는 최소 구조입니다.

| | |
| --- | --- |
| Method | `GET` |
| URL | `/api/v1/sessions/{sessionId}/summary` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | 종료된 면접의 요약을 조회 |

## 왜 WebSocket 이 아닌가

요약은 **면접이 끝난 뒤에** 봅니다 (2026-09-09 팀 결정). 실시간으로 밀어줄 필요가 없어
전사(#7)와 달리 HTTP 조회 하나면 됩니다.

다만 LLM 요약은 즉시 나오지 않으므로 **생성 중 상태**가 필요합니다.
FE 는 `PROCESSING` 인 동안 2초 간격으로 다시 조회합니다.

### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 요약을 조회할 Session ID | string | false | ses_123 |

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |
| status | 요약 생성 상태 | string | false | READY |
| content | 요약 본문. `status` 가 `READY` 일 때만 채워짐 | object | true | 아래 참고 |
| content.overview | 면접 전체 요약 | string | false | 지원자는 3년차 백엔드… |
| content.keyPoints | 핵심 내용 | string[] | false | ["실시간 파이프라인 경험", …] |
| durationSec | 면접 진행 시간(초) | number | false | 1820 |

`status` 값: `PROCESSING` · `READY` · `FAILED`

**Example**

```json
{
  "sessionId": "ses_123",
  "status": "READY",
  "content": {
    "overview": "지원자는 3년차 백엔드 개발자로, 실시간 스트리밍 파이프라인 경험을 중심으로 답변했습니다.",
    "keyPoints": [
      "실시간 스트리밍 파이프라인 담당 경험 — 초당 2만 건 처리",
      "성능 수치의 근거는 언급되지 않음"
    ]
  },
  "durationSec": 1820
}
```

생성 중일 때:

```json
{ "sessionId": "ses_123", "status": "PROCESSING", "content": null, "durationSec": 0 }
```

### Status

| status | response content |
| --- | --- |
| 200 | 조회 성공 (생성 중 포함) |
| 403 | 열람 권한 없음 — 지원자는 요약을 볼 수 없음 |
| 404 | Session 을 찾을 수 없음 |

---

## FE 참고

### 확인 필요

- **요약을 누가 볼 수 있나요?** FE 는 면접관만 볼 수 있다고 가정하고, 지원자가 나가면 처음 화면으로 보냅니다.
- **`content` 형식** — #6 의 "요약 출력 형식" 이 정해지면 그대로 맞추겠습니다. 지금 구조는 제안입니다.
- **생성 실패 시** `FAILED` 로 오나요, 아니면 5xx 인가요?
- 요약 생성은 **언제 시작되나요?** `end` 호출 시점인지, 별도 트리거가 있는지.

### 현재 FE 구현

`pages/InterviewSummaryPage.tsx` 가 `PROCESSING` 인 동안 2초 간격으로 재조회하고,
`READY` 가 되면 `overview` 와 `keyPoints` 를 그립니다. 목 서버가 두 번은 `PROCESSING`,
세 번째부터 `READY` 를 돌려주도록 되어 있어 대기 화면도 확인할 수 있습니다.
