# Health Check

| | |
| --- | --- |
| Method | `GET` |
| URL | `/health` |
| 사용자 | — |
| 그룹 | 시스템 |
| 설명 | 서버 상태 확인 |


### Request

**Path parameter**

없음


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


---

## FE 참고

### 참고

`/api/v1` prefix 가 붙지 않는 유일한 엔드포인트입니다.
그래서 FE 의 `VITE_API_BASE` 는 prefix 없이 **오리진만** 담습니다.

구현은 `backend/app/api/health.py` 에 이미 있습니다.
