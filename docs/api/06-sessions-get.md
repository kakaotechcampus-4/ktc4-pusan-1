# Session 상태 조회

| | |
| --- | --- |
| Method | `GET` |
| URL | `/api/v1/sessions/{sessionId}` |
| 사용자 | 면접관 · 지원자 |
| 그룹 | 면접 |
| 설명 | 현재 화상면접 Session의 진행 상태를 조회 |
| 기타 | 새로고침·재접속 시 상태 복구 용도 |


### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | Session ID | string | false | ses_123 |


**Request Body**

```json
없음 (GET)
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
| 403 |  |
| 404 |  |


---

## FE 참고

### 확인 필요

- `status` 값의 목록이 무엇인가요? FE 는 잠정으로 `created` / `in-progress` / `ended` 를 가정했습니다.
- **이 응답에도 `role` 이 오나요?** 새로고침 후 어떤 화면으로 복구할지 정하려면 필요합니다.
- 상대 참가자가 들어와 있는지도 알 수 있나요? (대기 화면 복구용)
