### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 종료할 Session ID | string | false | ses_123 |

**Request Body**

```json
{}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |
| status | 변경된 Session 상태 | string | false | ENDED |
| endedAt | 면접 종료 시각 | datetime | false | 2026-09-08T23:00:00Z |

**Example**

```json
{
  "sessionId": "ses_123",
  "status": "ENDED",
  "endedAt": "2026-09-08T23:00:00Z"
}
```

### Status

| status | response content |
| --- | --- |
| 200 | 면접 종료 성공 |
| 404 | Session을 찾을 수 없음 |
| 409 | 현재 상태에서 종료할 수 없음 |

---

## FE 참고

### 확인 필요

- **"참가자 disconnect 와 면접 종료는 별개" 라면, 면접관이 브라우저를 그냥 닫으면 세션이 계속 살아 있나요?**
  타임아웃 자동 종료가 있나요? 없으면 `WAITING` / `INTERVIEWING` 상태의 세션이 계속 쌓입니다.
- **지원자도 종료할 수 있나요, 나가기만 되나요?** 권한 구분이 필요합니다.
- **녹화(Egress) 중지가 여기에 묶이나요?** 면접관이 먼저 끊어도 지원자가 남아 있으면 녹화가 계속 돕니다.
- FE 는 종료 후 면접 기록(S3)으로 이동합니다. **후처리 상태(예: `reviewStatus`)가 없어서
  기록이 준비됐는지 판단할 수 없습니다.** S3 이 이번 스코프가 아니라면 지금은 넘어가도 됩니다.
