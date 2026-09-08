# 면접 생성

| | |
| --- | --- |
| Method | `POST` |
| URL | `/api/v1/interviews` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | 면접관이 새로운 면접 정보를 생성 |
| 기타 | Session 및 LiveKit Room은 별도 Session 생성 단계에서 처리 |


### Request

**Path parameter**

없음


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
| 201 |  |
| 400 |  |
| 401 |  |


---

## FE 참고

### 확인 필요

- 요청 본문에 무엇이 들어가나요? (지원자 이름 · 직무 · 기업 컨텍스트 등)
- 생성 직후 `interviewId` 를 응답으로 주나요, `Location` 헤더로 주나요?
- 인증이 필요한가요? 현재 FE 는 모든 요청에 `Authorization: Bearer <localStorage.accessToken>` 을 붙이지만 로그인 화면이 없습니다.
