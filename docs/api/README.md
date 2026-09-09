# API 명세

각 문서는 Request(Path parameter · Body) / Response(표 · Example) / Status 형식을 따릅니다.

`## FE 참고` 아래는 **프론트엔드가 확인을 요청하는 항목**입니다. 명세 본문이 아니므로
확정된 뒤에는 지워도 됩니다.

| 기능 | Method | URL | 사용자 | 그룹 |
| --- | --- | --- | --- | --- |
| [면접 생성](01-interviews-create.md) | `POST` | `/api/v1/interviews` | 면접관 | 면접 |
| [면접 조회](02-interviews-get.md) | `GET` | `/api/v1/interviews/{interviewId}` | 면접관 | 면접 |
| [면접 Session 생성](03-sessions-create.md) | `POST` | `/api/v1/interviews/{interviewId}/sessions` | 면접관 | 면접 |
| [면접 입장](04-sessions-join.md) | `POST` | `/api/v1/sessions/{sessionId}/join` | 면접관 · 지원자 | 진입 |
| [면접 시작](05-sessions-start.md) | `POST` | `/api/v1/sessions/{sessionId}/start` | 면접관 | 면접 |
| [Session 상태 조회](06-sessions-get.md) | `GET` | `/api/v1/sessions/{sessionId}` | 면접관 · 지원자 | 면접 |
| [면접 종료](07-sessions-end.md) | `POST` | `/api/v1/sessions/{sessionId}/end` | 면접관 | 면접 |
| [Health Check](08-health.md) | `GET` | `/health` | — | 시스템 |
| [면접 요약](09-sessions-summary.md) ⚠️ 제안 | `GET` | `/api/v1/sessions/{sessionId}/summary` | 면접관 | 면접 |

> 확정이 급하지 않은 항목은 [나중에 정해도 되는 것](DEFERRED.md) 에 따로 모아뒀습니다.

## Session 상태

문서에서 확인된 값입니다.

| 값 | 시점 |
| --- | --- |
| `WAITING` | Session 생성 직후 |
| `INTERVIEWING` | 면접 시작 후 |
| `ENDED` | 면접 종료 후 |

## 공통 — 에러 응답 형식 (미정)

각 문서의 Status 표에는 상태 코드와 설명만 있고 **에러 본문 스키마가 없습니다.**
FE 는 아래 형태를 기대하고 화면을 분기합니다.

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session을 찾을 수 없습니다."
  }
}
```

본문이 없으면 HTTP status 만으로 분기해야 하는데, 현재 명세에서는
**`409` 하나에 "이미 종료된 Session" 과 "정원 초과" 가 겹칩니다.** 두 경우의 안내 문구가 달라야 하므로
`code` 가 필요합니다.

| code (제안) | status | 화면 문구 |
| --- | --- | --- |
| `SESSION_NOT_FOUND` | 404 | 유효하지 않은 링크입니다 |
| `SESSION_ENDED` | 409 | 이미 종료된 면접입니다 |
| `ROOM_FULL` | 409 | 이미 두 명이 입장해 있습니다 |

## 아직 명세에 없는 것

- **전사·추천 질문 WebSocket** — AI(#7)가 STT 결과와 추천 질문을 실시간으로 밀어주는 경로.
  8개 엔드포인트 어디에도 없습니다. FE 의 `TranscriptPanel` · `SuggestionPanel` 두 화면이
  붙을 곳이 없어 목 데이터로만 동작합니다. BE 담당인지 AI 담당인지도 정해지지 않았습니다.
- **면접 요약 조회** — 이슈 #6 의 결과를 받을 통로. FE 가 [09-sessions-summary.md](09-sessions-summary.md) 로 제안했습니다.
  요약은 면접 종료 후에 보므로 WebSocket 이 아니라 HTTP 조회면 됩니다.
- **추천 질문 "물어봤음" 기록** — 면접관이 추천 질문을 실제로 물어봤음을 서버에 알리는 엔드포인트.
  지금은 화면에서만 표시되고 새로고침하면 사라집니다.
- **인증** — 현재 `interviewerId`(면접 생성)와 `role`(입장)을 클라이언트가 그대로 보냅니다.
  인증이 붙기 전까지는 위조가 가능합니다. 자세한 내용은 [면접 입장](04-sessions-join.md) 문서를 참고하세요.
