### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | Session을 생성할 면접 ID | string | false | int_123 |

**Request Body**

```json
{}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 화상면접 Session ID | string | false | ses_123 |
| interviewId | 연결된 면접 ID | string | false | int_123 |
| status | Session 상태 | string | false | WAITING |
| inviteUrl | 지원자에게 전달할 면접 링크 | string | false | https://irya.com/interview/ses_123 |
| createdAt | Session 생성 시각 | datetime | false | 2026-09-08T22:20:00Z |

**Example**

```json
{
  "sessionId": "ses_123",
  "interviewId": "int_123",
  "status": "WAITING",
  "inviteUrl": "https://irya.com/interview/ses_123",
  "createdAt": "2026-09-08T22:20:00Z"
}
```

### Status

| status | response content |
| --- | --- |
| 201 | Session 생성 성공 |
| 404 | 면접을 찾을 수 없음 |

---

## FE 참고

### FE 가 맞추겠습니다

`inviteUrl` 의 경로가 `/interview/{sessionId}` 이므로 FE 라우트를 여기에 맞추겠습니다.
(현재 구현은 `/sessions/:sessionId/join` 이라 변경이 필요합니다.)

### 확인 필요

- **`inviteUrl` 의 도메인이 `https://irya.com` 으로 고정입니다.** 로컬 개발과 스테이징에서는 열리지 않습니다.
  환경변수로 주입하시나요, 아니면 FE 가 `sessionId` 로 직접 조립하는 편이 나을까요?
- **면접관 자신은 어떤 경로로 입장하나요?** `inviteUrl` 은 지원자용입니다.
  면접관은 이 응답의 `sessionId` 를 그대로 쓰면 되나요?
- `status` 값의 전체 목록이 궁금합니다. 지금까지 문서에서 확인된 값은
  `WAITING` · `INTERVIEWING` · `ENDED` 세 가지입니다. 이게 전부인가요?
