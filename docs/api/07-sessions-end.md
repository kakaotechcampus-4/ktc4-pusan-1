# 면접 종료

| | |
| --- | --- |
| Method | `POST` |
| URL | `/api/v1/sessions/{sessionId}/end` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | Session을 종료 상태로 변경하고 종료 시각을 기록 |
| 기타 | 참가자 disconnect와 면접 종료는 별개로 처리 |


### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |


**Request Body**

```json
{}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

**Example**

```json
{}
```

### Status

| status | response content |
| --- | --- |
| 200 |  |
| 404 |  |
| 409 |  |


---

## FE 참고

### 확인 필요

- "참가자 disconnect 와 면접 종료는 별개" 라면, **면접관이 브라우저를 그냥 닫으면 세션이 계속 살아 있나요?**
  타임아웃으로 자동 종료되나요?
- 지원자도 종료할 수 있나요, 나가기만 되나요?
- 녹화(Egress) 중지가 여기에 묶이나요? 면접관이 먼저 끊어도 지원자가 남아 있으면 녹화가 계속 돕니다.
- FE 는 종료 후 면접 기록(S3) 으로 이동합니다. `reviewStatus` 같은 후처리 상태가 응답에 있나요?
