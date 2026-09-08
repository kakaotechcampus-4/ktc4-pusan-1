### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 조회할 Session ID | string | false | ses_123 |

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |
| interviewId | 연결된 면접 ID | string | false | int_123 |
| status | 현재 Session 상태 | string | false | INTERVIEWING |
| startedAt | 면접 시작 시각 | datetime | true | 2026-09-08T22:30:00Z |
| endedAt | 면접 종료 시각 | datetime | true | null |

**Example**

```json
{
  "sessionId": "ses_123",
  "interviewId": "int_123",
  "status": "INTERVIEWING",
  "startedAt": "2026-09-08T22:30:00Z",
  "endedAt": null
}
```

### Status

| status | response content |
| --- | --- |
| 200 | Session 조회 성공 |
| 404 | Session을 찾을 수 없음 |

---

## FE 참고

### 확인 필요 — 새로고침 복구가 아직 안 됩니다

이 API 의 용도가 "새로고침·재접속 시 상태 복구" 인데, 현재 응답만으로는 복구가 안 됩니다.

1. **`role` 이 없습니다.** 새로고침 후 면접관 화면과 지원자 화면 중 무엇을 그려야 할지 알 수 없습니다.
   (`04-sessions-join` 에서 role 을 요청으로 보내는 구조라, FE 가 직접 기억해두지 않으면 잃어버립니다.)
2. **상대 참가자가 들어와 있는지 알 수 없습니다.** 면접 화면은 상대 입장 전 대기 화면을 띄우는데,
   복구 시점에 그 판단을 할 수 없습니다.

`status` 가 `INTERVIEWING` 이어도 상대가 나가 있을 수 있어서, 상태만으로는 대체되지 않습니다.
