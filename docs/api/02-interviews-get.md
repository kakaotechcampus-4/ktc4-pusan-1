# 면접 조회

| | |
| --- | --- |
| Method | `GET` |
| URL | `/api/v1/interviews/{interviewId}` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | 생성된 면접의 기본 정보를 조회 |


### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | 면접 ID | string | false | itv_123 |


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
| 404 |  |


---

## FE 참고

### 확인 필요

- "기본 정보" 의 필드 구성이 무엇인가요?
- FE 면접 화면이 지원자 이름을 표시합니다. 이 응답에 포함되나요, 아니면 `join` 응답에 들어가나요?
