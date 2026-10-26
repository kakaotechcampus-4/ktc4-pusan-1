# IRYA Frontend

면접관용 화상면접 웹 프론트엔드.

## Quick Start

```bash
npm install
cp .env.example .env
npm run dev
```

http://localhost:5173 이 열립니다.

> 백엔드 없이도 전체 흐름이 돕니다. **`/host` 에서 면접을 만들고 링크를 복사해 다른 탭에서 열면**
> 면접관과 지원자 화면을 동시에 볼 수 있습니다. 자세한 순서는 [시연 방법](#시연-방법)을 참고하세요.
> 기기 점검 단계에서 **카메라·마이크 권한을 요청합니다.**

## Requirements

- Node.js 22.12 이상 — `.nvmrc` 에 고정되어 있습니다
- npm

## Scripts

| 명령                   | 하는 일                    |
| ---------------------- | -------------------------- |
| `npm run dev`          | 개발 서버 (127.0.0.1:5173) |
| `npm run build`        | 타입 체크 후 프로덕션 빌드 |
| `npm run preview`      | 빌드 결과 미리보기         |
| `npm run typecheck`    | 타입 체크만                |
| `npm run lint`         | ESLint                     |
| `npm run format`       | Prettier 적용              |
| `npm run format:check` | Prettier 검사 (CI 와 동일) |

PR 을 올리면 CI 가 `lint` · `format:check` · `typecheck` · `build` 를 같은 순서로 검사합니다.

다른 기기에서 접속해야 할 때는 `npm run dev -- --host` 로 LAN 에 노출합니다.

## Environment

```bash
cp .env.example .env
```

| 변수            | 필수   | 설명                                                           |
| --------------- | ------ | -------------------------------------------------------------- |
| `VITE_API_BASE` | 아니오 | API base URL. 미설정 시 `src/api/client.ts` 의 기본값을 씁니다 |

### LiveKit 키는 여기에 두지 않습니다

`LIVEKIT_API_SECRET` 이 프론트엔드 번들에 들어가면 **누구나 임의의 방에 입장하는 토큰을 만들 수 있습니다.** Vite 는 `VITE_` 로 시작하는 변수를 그대로 번들에 넣습니다.

입장 토큰은 서버가 서명해서 내려줍니다.

```
POST /api/v1/sessions/{sessionId}/join
  → LiveKit 접속 정보 (roomUrl, token)
```

FE 는 받은 `media.token` 을 `room.connect()` 에 넘기기만 합니다. LiveKit 키는 `backend/.env` 와 `ai/.env` 에 있습니다.

## Stack

|            |                |     |
| ---------- | -------------- | --- |
| 빌드       | Vite           | 8   |
| 프레임워크 | React          | 19  |
| 언어       | TypeScript     | 5.9 |
| 스타일     | Tailwind CSS   | 4   |
| 상태       | zustand        | 5   |
| 미디어     | livekit-client | 2   |

TypeScript 는 7.0 이 나와 있지만 **5.9 로 고정**합니다. `typescript-eslint` 의 peer 범위가 `<6.1.0` 이라 7.0 에서는 린트가 동작하지 않습니다.

`@livekit/components-react` 는 설치하지 않았습니다. 도입 여부가 [#9](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/9) 의 FE 협의 항목입니다.

## Structure

```
src/
├── api/                      HTTP 클라이언트, 면접 API
│   ├── client.ts             fetch 래퍼, ApiError
│   └── interview.ts          start / end / ask
├── components/interview/
│   ├── InterviewRoomView.tsx 면접 화면 표현부 (연결을 모름)
│   ├── LocalPreview.tsx      자기 영상 + 마이크 레벨 미터
│   ├── TranscriptPanel.tsx   자동 기록
│   ├── SuggestionPanel.tsx   이어서 물어볼 질문
│   └── SpeakerBadge.tsx      말하는 중 표시
├── hooks/
│   ├── usePermissionCheck.ts 카메라·마이크 권한, 캡처 상수
│   └── useInterviewRoom.ts   LiveKit 연결, 트랙 발행·구독, 전사 WebSocket
├── lib/                      공용 유틸
├── pages/
│   └── InterviewRoom.tsx     면접 화면 연결부 (훅 + View)
├── stores/
│   └── interviewStore.ts     zustand 화면 상태
└── types/                    도메인 타입
```

면접 화면을 **표현부(`InterviewRoomView`)와 연결부(`pages/InterviewRoom`)로 분리**했습니다. 서버 없이도 화면만 따로 띄워 확인할 수 있게 하기 위해서입니다.

## 화면

| 경로                                     | 화면                                | 로그인 |
| ---------------------------------------- | ----------------------------------- | ------ |
| `/`                                      | 로그인 전 랜딩 · 로그인 후 대시보드 | 선택   |
| `/login` · `/oauth/kakao/callback`       | 카카오 로그인                       | —      |
| `/terms` · `/privacy`                    | 이용약관 · 개인정보처리방침         | —      |
| `/settings/context`                      | 기업 설정                           | 필요   |
| `/interviews/new`                        | 면접 만들기 — 이력서 · 초대 링크    | 필요   |
| `/candidates`                            | 지원자 목록                         | 필요   |
| `/interview/:sessionId`                  | 지원자 입장 → 기기 점검 → 면접      | —      |
| `/interview/:sessionId?role=interviewer` | 면접관 입장                         | 필요   |
| `/interview/:sessionId/summary`          | 면접 종료 후 요약                   | 필요   |
| `/review/:interviewId`                   | 면접 기록 — 녹화 · 타임라인 · 검토  | 필요   |

## 로컬 실행

목 API 는 없습니다(#232 에서 걷어냄). 화면을 보려면 BE 를 띄웁니다.

```bash
# 1. PostgreSQL (backend/README.md)
docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test -e POSTGRES_USER=irya -e POSTGRES_DB=irya postgres:17-alpine

# 2. BE
cd backend && DATABASE_URL=postgresql://irya:test@localhost:55432/irya uv run uvicorn app.main:app --reload

# 3. FE
cd frontend && npm run dev
```

http://localhost:5173 에서 카카오로 로그인한 뒤, 검토할 면접이 필요하면 데모 데이터를 넣습니다.
`--owner` 는 로그인한 사용자 id(`GET /api/v1/auth/me` 의 `id`)입니다.

```bash
cd backend && DATABASE_URL=postgresql://irya:test@localhost:55432/irya uv run python -m app.seed_demo --owner usr_xxx
```

## 알려진 이슈

**번들 크기** — 진입 화면은 243 kB (gzip 78 kB) 입니다. `livekit-client` 가 520 kB 로 큰데,
카메라·마이크를 쓰는 화면(`DeviceCheckPage` · `InterviewRoom`)만 `lazy()` 로 분리해서
진입·요약 화면에서는 받지 않습니다. 빌드 시 뜨는 500 kB 경고는 분리된 그 청크에 대한 것이라
의도된 상태입니다.

**dev 서버 바인딩** — Vite 기본값은 IPv6(`[::1]`)에만 바인딩해서 `127.0.0.1` 로 접근하는 클라이언트가 붙지 못합니다. `vite.config.ts` 에서 `host: '127.0.0.1'` 로 고정해뒀습니다.
