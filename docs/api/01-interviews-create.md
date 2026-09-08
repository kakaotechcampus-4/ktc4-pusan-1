### Request

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewerId | 면접을 생성한 면접관 ID | string | false | user_123 |

**Example**

```json
{
  "interviewerId": "user_123"
}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | 생성된 면접 ID | string | false | int_123 |
| interviewerId | 면접관 ID | string | false | user_123 |
| createdAt | 면접 생성 시각 | datetime | false | 2026-09-08T22:10:00Z |

**Example**

```json
{
  "interviewId": "int_123",
  "interviewerId": "user_123",
  "createdAt": "2026-09-08T22:10:00Z"
}
```

### Status

| status | response content |
| --- | --- |
| 201 | 면접 생성 성공 |
| 422 | 요청값 검증 실패 |

---

## FE 참고

### 확인 필요

- **`interviewerId` 를 클라이언트가 보냅니다.** 인증이 없는 지금은 아무나 임의의 ID 로 면접을 만들 수 있습니다.
  `04-sessions-join` 의 `role` 과 같은 뿌리라, 인증 도입 시 함께 정리되어야 합니다.
- **지원자 정보가 없습니다.** 면접 화면 상단에 지원자 이름을 표시하는데, 이 응답에도 `02-interviews-get` 에도
  이름이 없습니다. 어디서 가져와야 하나요?
- 직무·기업 컨텍스트(S1)는 이번 스코프가 아닌 것으로 이해했습니다. 맞나요?
