### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | 조회할 면접 ID | string | false | int_123 |

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | 면접 ID | string | false | int_123 |
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
| 200 | 면접 조회 성공 |
| 404 | 면접을 찾을 수 없음 |

---

## FE 참고

### 확인 필요

- 응답이 `interviewId` · `interviewerId` · `createdAt` 뿐입니다.
  **면접 화면이 표시할 지원자 이름이 없습니다.** 여기에 추가되나요, 아니면 별도 경로인가요?
