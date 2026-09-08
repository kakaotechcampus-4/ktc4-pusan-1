### Request

**Path parameter**

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 입장할 Session ID | string | false | ses_123 |

**Request Body**

```json
{
  "role": "CANDIDATE"
}
```

### Response

| key | 설명 | value 타입 | Nullable | 예시 |
| --- | --- | --- | --- | --- |
| sessionId | 입장한 Session ID | string | false | ses_123 |
| livekitUrl | LiveKit 서버 접속 URL | string | false | wss://example.livekit.cloud |
| token | LiveKit Room 입장용 Access Token | string | false | eyJ... |
| roomName | 매핑된 LiveKit Room 이름 | string | false | interview_ses_123 |

**Example**

```json
{
  "sessionId": "ses_123",
  "livekitUrl": "wss://example.livekit.cloud",
  "token": "eyJ...",
  "roomName": "interview_ses_123"
}
```

### Status

| status | response content |
| --- | --- |
| 200 | 입장 정보 발급 성공 |
| 404 | Session을 찾을 수 없음 |
| 409 | 이미 종료된 Session 등 현재 상태에서 입장할 수 없음 |

<aside>
💡

현재 로그인/인증 제외 기준에서는 `role`을 요청값으로 받습니다. 인증 도입 후에는 서버가 참가자 역할을 판단하도록 변경할 수 있습니다.

</aside>

---

## FE 참고

### 🚨 `role` 을 클라이언트가 선언하는 구조입니다

지원자가 `{"role": "INTERVIEWER"}` 를 보내면 **면접관 토큰을 그대로 발급받습니다.**
그러면 지원자 화면에 면접관 전용 AI 추천 질문이 노출되고, 방 종료·강퇴 권한도 함께 넘어갑니다.

aside 에 인지하고 계신 것으로 보이지만, issue #9 의 완료 조건과 정면으로 충돌합니다.

> 토큰의 역할·권한은 요청 파라미터가 아니라 코드에 저장된 값으로만 결정된다
> 지원자 토큰으로는 방 종료·참가자 강퇴가 되지 않는다

인증 도입 전이라도, **`03-sessions-create` 에서 역할별 링크를 두 개 발급**하면
요청 본문 없이 해결됩니다 (면접관용 / 지원자용 sessionId 또는 토큰).
데모에서 실제로 드러날 수 있는 부분이라 우선순위를 올려주시면 좋겠습니다.

### 확인 필요

1. **에러 응답 본문 형식이 없습니다.** Status 표에는 설명만 있고 본문 스키마가 없습니다.
   FE 는 아래 형태를 기대하고 있습니다.

   ```json
   { "error": { "code": "SESSION_NOT_FOUND", "message": "..." } }
   ```

   본문이 없으면 FE 는 HTTP status 로만 분기해야 하는데, **409 하나에 "이미 종료" 와
   "정원 초과" 가 겹칩니다.** 두 경우의 안내 문구가 달라야 합니다.

2. **정원 초과가 명세에 없습니다.** 3번째 참가자가 들어오면 어떻게 되나요?
   `join` 에서 막나요, LiveKit 입장 단계에서 막히나요?

3. **전사·추천 질문 WebSocket URL 이 없습니다.** 명세 8개 어디에도 이 경로가 없습니다 (AI #7).
   이게 없으면 `TranscriptPanel` · `SuggestionPanel` 두 화면이 목 데이터로만 동작합니다.
   BE 담당인지 AI 담당인지도 정해지지 않았습니다.

4. **join 을 두 번 부르면 같은 사람으로 인식되나요?** 새로고침 · 재접속 · 토큰 만료가 모두 재호출로 이어집니다.
   같은 사람으로 안 보면 정원 2명을 혼자 채우게 됩니다.

5. **토큰 TTL** 은 얼마인가요? 기기 점검에 시간이 걸린 뒤 접속하므로 여유가 필요합니다.

### FE 가 맞추겠습니다

응답 필드를 `livekitUrl` · `token` · `roomName` 으로 받도록 수정하겠습니다.
(현재 코드는 `media.roomUrl` · `media.token` 을 기대합니다.)
