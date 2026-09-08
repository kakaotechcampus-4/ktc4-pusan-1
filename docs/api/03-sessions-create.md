# 면접 Session 생성

| | |
| --- | --- |
| Method | `POST` |
| URL | `/api/v1/interviews/{interviewId}/sessions` |
| 사용자 | 면접관 |
| 그룹 | 면접 |
| 설명 | 생성된 면접에 실제 화상면접 Session을 생성하고 지원자 초대 링크를 발급 |


### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| interviewId | 면접 ID | string | false | itv_123 |


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
| 404 |  |
| 409 |  |


---

## FE 참고

### 확인 필요 (FE 에 가장 중요)

- **초대 링크를 완성된 URL 로 주시나요, `sessionId` 만 주시나요?**
  - 완성된 URL 이면 FE 는 그대로 복사 버튼에 씁니다.
  - `sessionId` 만이면 FE 가 조립해야 하는데, 그러면 프론트 도메인을 어디서 가져올지 정해야 합니다.
- 링크에 만료가 있나요? 있다면 만료 시각도 응답에 필요합니다.
- 면접관 자신의 입장 경로는 무엇인가요? 지원자만 링크를 받는다면, 면접관은 `sessionId` 를 어떻게 얻나요?

### 현재 FE 구현

초대 링크 경로는 `/sessions/:sessionId/join` 입니다.
