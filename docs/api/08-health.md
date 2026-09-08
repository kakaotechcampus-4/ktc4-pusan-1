### Request

Request Body 없음

### Response

**Example**

```json
{
  "status": "ok"
}
```

### Status

| status | response content |
| --- | --- |
| 200 | 서버 정상 동작 |

---

## FE 참고

`/api/v1` prefix 가 붙지 않는 유일한 엔드포인트입니다.
그래서 FE 의 `VITE_API_BASE` 는 prefix 없이 **오리진만** 담고, 경로는 각 호출부가 붙입니다.

구현은 `backend/app/api/health.py` 에 이미 있고 응답도 문서와 일치합니다.
