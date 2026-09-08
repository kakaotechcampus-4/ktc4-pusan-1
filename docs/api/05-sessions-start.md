### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 시작할 Session ID | string | false | ses_123 |

**Request Body**

```json
{}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |
| status | 변경된 Session 상태 | string | false | INTERVIEWING |
| startedAt | 면접 시작 시각 | datetime | false | 2026-09-08T22:30:00Z |

**Example**

```json
{
  "sessionId": "ses_123",
  "status": "INTERVIEWING",
  "startedAt": "2026-09-08T22:30:00Z"
}
```

### Status

| status | response content |
| --- | --- |
| 200 | 면접 시작 성공 |
| 404 | Session을 찾을 수 없음 |
| 409 | 현재 상태에서 시작할 수 없음 |

---

## FE 참고

### 확인 필요

- **누가 언제 호출하나요?** 면접관이 버튼을 누르나요, 두 명이 다 입장하면 서버가 자동 전이시키나요?
  FE 에 시작 버튼이 필요한지가 여기서 갈립니다.
- 여러 번 호출해도 상태 전이는 한 번만 일어나나요? (issue #9 완료 조건 항목)
- **녹화(Egress) 시작이 여기에 묶이나요?** 아니면 Session 생성 시점인가요?
