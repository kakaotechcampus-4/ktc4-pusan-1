# IRYA Frontend

면접관용 화상면접 웹 프론트엔드.

## Quick Start

```bash
npm install
cp .env.example .env
npm run dev
```

http://localhost:5173 이 열립니다.

> **면접 화면을 보려면 http://localhost:5173/?mock=interview 로 접속하세요.**
> 기본 화면에는 환경 확인 정보만 나옵니다. 이유는 [현재 상태](#현재-상태)를 참고하세요.
> 이 화면은 자기 영상 프리뷰 때문에 **카메라·마이크 권한을 요청합니다.**

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

PR 을 올리기 전에 `lint`, `format:check`, `typecheck`, `build` 네 개가 통과해야 합니다. CI 가 같은 순서로 돕니다.

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
├── mocks/                    ⚠️ 임시 — 아래 참고
├── pages/
│   └── InterviewRoom.tsx     면접 화면 연결부 (훅 + View)
├── stores/
│   └── interviewStore.ts     zustand 화면 상태
└── types/                    도메인 타입
```

면접 화면을 **표현부(`InterviewRoomView`)와 연결부(`pages/InterviewRoom`)로 분리**했습니다. 서버 없이도 화면만 따로 띄워 확인할 수 있게 하기 위해서입니다.

## 프로토타입 범위

멘토 검토용 프로토타입입니다. **서비스로 바로 쓸 수 있는 상태가 아니며, 의도적으로 뺀 것들이 있습니다.**

### 실제로 동작하는 것

|                         |                                                                       |
| ----------------------- | --------------------------------------------------------------------- |
| 카메라·마이크 권한 요청 | 실제 `getUserMedia`. 거부·기기 없음·점유 중을 각각 다른 화면으로 안내 |
| 기기 점검 화면          | 실제 로컬 영상 프리뷰 + 마이크 입력 레벨 미터                         |
| 면접 화면 PiP           | 기기 점검에서 얻은 **실제 카메라 트랙**                               |
| 역할별 화면 분기        | 면접관 / 지원자에게 다른 것을 보여줌                                  |
| 입장 실패 화면          | 유효하지 않은 링크 / 입장 불가                                        |

### 목 데이터인 것

|                  | 왜                                                       |
| ---------------- | -------------------------------------------------------- |
| 서버 응답 전체   | BE 미구현. `mocks/mockApi.ts` 가 명세와 같은 형태로 응답 |
| 상대방 영상·음성 | LiveKit 서버 미구성. 원격 영상 영역은 비어 있음          |
| 전사(자동 기록)  | **WebSocket 경로가 API 명세에 없음** (AI #7)             |
| 추천 질문        | 위와 같음                                                |

### 의도적으로 넣지 않은 것

- **인증·로그인** — 프로토타입 범위 밖. `role` 을 클라이언트가 선언하는 현재 구조는
  인증이 붙으면 서버 판단으로 바뀝니다 (`docs/api/04-sessions-join.md` 참고)
- **추천 질문 "물어봤음" 서버 기록** — 엔드포인트 미정. 지금은 화면에서만 표시
- **면접 기록(S3) · 기업 컨텍스트(S1) · 지원자 목록(S4)**

미확정 항목과 각각의 기본값은 [`docs/api/DEFERRED.md`](../docs/api/DEFERRED.md) 에 정리했습니다.

## API 커버리지

명세 8개 중 6개를 실제로 호출합니다.

| 엔드포인트                       | 쓰는 곳                                    |
| -------------------------------- | ------------------------------------------ |
| `POST /interviews`               | 면접 준비                                  |
| `GET /interviews/{id}`           | (정의만. 조회 전용 화면이 없음)            |
| `POST /interviews/{id}/sessions` | 면접 준비                                  |
| `POST /sessions/{id}/join`       | 입장                                       |
| `POST /sessions/{id}/start`      | 면접관 입장 시                             |
| `GET /sessions/{id}`             | (정의만. 재접속 복구는 `role` 부재로 보류) |
| `POST /sessions/{id}/end`        | 면접관 종료 시                             |
| `GET /health`                    | FE 무관                                    |

## 시연 방법

```bash
npm run dev
```

http://localhost:5173 에서 두 역할로 각각 들어가 볼 수 있습니다.

| 경로                                   | 화면                                  |
| -------------------------------------- | ------------------------------------- |
| `/`                                    | 진입점 (프로토타입 전용)              |
| `/interview/ses_demo?role=interviewer` | 면접관 — 전사 · 추천 질문 · 면접 종료 |
| `/interview/ses_demo`                  | 지원자 — 패널 없음 · 나가기           |
| `/interview/not-found`                 | 유효하지 않은 링크                    |
| `/interview/ended`                     | 입장 불가                             |
| `/mock/interview`                      | 면접 화면만 바로 보기                 |

목 API 는 개발 모드에서만 켜집니다. 실제 BE 에 붙이려면 `.env` 에 아래를 넣으세요.

```
VITE_USE_MOCK_API=false
VITE_API_BASE=http://localhost:8000
```

## `src/mocks/` 는 임시입니다

BE·AI 없이 화면을 확인하기 위한 코드입니다. API 는 붙이지 않고 zustand 스토어에 가짜 이벤트만 흘립니다.

- `mockApi.ts` — 명세와 같은 형태로 응답하는 목 API (`api/client.ts` 에서 분기)
- `interviewMock.ts` — 약 10초짜리 대화 대본
- `InterviewRoomPreview.tsx` — `InterviewRoomView` 를 목 상태로 렌더

**자기 화면(PiP)만 실제 카메라·마이크 트랙을 씁니다.** 그래서 `?mock=interview` 는 접속하면 권한을 요청합니다. `POST /interviews/{id}/start` 가 없어 `pages/InterviewRoom` 을 마운트할 수 없는 동안, #8 의 로컬 프리뷰를 확인할 유일한 진입점입니다. 지원자 영상·전사·추천 질문은 그대로 목입니다.

**BE·AI 연동 시 `src/mocks/` 디렉터리와 `api/client.ts` 의 `USE_MOCK_API` 분기를 함께 지웁니다.** 프로덕션 코드에는 목 관련 플래그가 없습니다.

## 알려진 이슈

**번들 크기** — 현재 720 kB (gzip 199 kB) 로 Vite 경고가 뜹니다. `livekit-client` 가 통째로 들어가서입니다. #5 에서 면접 화면을 라우팅에 붙일 때 `dynamic import()` 로 코드 스플리팅해야 합니다. 그러지 않으면 방 코드 입력 화면 하나 보려고 720 kB 를 받게 됩니다.

**dev 서버 바인딩** — Vite 기본값은 IPv6(`[::1]`)에만 바인딩해서 `127.0.0.1` 로 접근하는 클라이언트가 붙지 못합니다. `vite.config.ts` 에서 `host: '127.0.0.1'` 로 고정해뒀습니다.
