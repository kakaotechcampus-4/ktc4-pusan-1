# API 명세

각 문서는 아래 형식을 따릅니다 — Request(Path parameter · Body) / Response(표 · Example) / Status.

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

## 아직 명세에 없는 것

- **전사·추천 질문 WebSocket** — AI(#7)가 STT 결과와 추천 질문을 실시간으로 밀어주는 경로.
  현재 FE 의 `TranscriptPanel` · `SuggestionPanel` 두 화면이 붙을 곳이 없어 목 데이터로만 동작합니다.
  BE 담당인지 AI 담당인지도 정해지지 않았습니다.
- **추천 질문 "물어봤음" 기록** — 면접관이 추천 질문을 실제로 물어봤음을 서버에 알리는 엔드포인트.
  지금은 화면에서만 표시되고 새로고침하면 사라집니다.
- **인증** — FE 는 모든 요청에 `Authorization: Bearer <token>` 을 붙이지만 로그인 화면도 발급 경로도 없습니다.
