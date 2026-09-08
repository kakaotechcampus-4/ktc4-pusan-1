# 면접 시작

| | |
| --- | --- |
| Method | `POST` |
| URL | `/api/v1/sessions/{sessionId}/start` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | Session을 면접 진행 상태로 변경하고 시작 시각을 기록 |


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

- **누가 언제 호출하나요?** 면접관이 버튼을 누르나요, 아니면 두 명이 다 들어오면 서버가 자동으로 전이시키나요?
- 여러 번 호출해도 상태 전이는 한 번만 일어나나요? (issue #9 완료 조건에 있던 항목입니다)
- 녹화(Egress) 시작이 여기에 묶이나요, Session 생성 시점인가요?
