<p align="center">
  <img src="frontend/public/favicon.svg" width="72" alt="IRYA 로고">
</p>

# IRYA

**면접은 사람이, 정리는 AI가.**
면접관이 이력서 준비부터 실시간 화상면접, 면접 후 근거 검토와 리포트까지 한 흐름으로 처리하는 AI 기반 화상면접 지원 서비스입니다.

![React](https://img.shields.io/badge/React-19.2-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)
![LiveKit](https://img.shields.io/badge/LiveKit-self--hosted-1F1F1F)
![Docker Compose](https://img.shields.io/badge/Docker_Compose-EC2-2496ED?logo=docker&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-S3_CloudFront-FF9900?logo=amazonwebservices&logoColor=white)

| 서비스 | API 문서 | 발표자료 |
| --- | --- | --- |
| https://irya.cloud | https://irya.cloud/docs | https://irya.cloud/presentation |

## 무엇을 해결하나요

- 면접관은 통화 중에 질문하고, 듣고, 적고, 판단까지 동시에 해야 해서 정작 답변의 근거를 놓치기 쉽습니다.
- IRYA 는 면접 전에 이력서를 읽어 확인할 지점을 미리 뽑고, 면접 중에는 발화를 자막으로 받아 적으면서 꼬리질문을 제안하고, 면접 후에는 요약 항목마다 실제 발화 시점을 연결해 둡니다.
- 합격 여부는 판단하지 않습니다. AI 는 기록·구조화·근거 연결까지만 맡고, 채택과 최종 판단은 면접관이 합니다.

## 주요 기능

| 구간 | 기능 |
| --- | --- |
| **면접 전** | 이력서 PDF 업로드 → PREP 생성기가 사전 질문·요약을 가공 · 지원자 목록 관리(검토 상태 필터·정렬·CSV/XLSX 내보내기) · 지원자 동의 절차 · 카카오 로그인 |
| **면접 중** | LiveKit 1:1 화상통화 · 마이크 트랙 실시간 전사 → 면접관 화면 자막 · 전사 기반 꼬리질문 제안(면접관 화면에만 표시) · FINAL 전사 저장 |
| **면접 후** | 재전사 · REVIEW 폴러가 findings 생성 · 검토 화면에서 근거 확인·채택 · 검토 확정 잠금 · 면접관 메모 |
| **리포트** | AI 면접 리포트 생성 · 리포트 화면 · Markdown 파일 받기 · 브라우저 인쇄로 PDF 저장 |
| **영상** | 면접 녹화 저장 · CloudFront 서명 URL(3시간)로 재생 · 면접 삭제 |
| **접근성** | KWCAG 2.2 점검 반영 ([점검 보고서](docs/accessibility/kwcag-2026-10-report.md)) |

면접 한 건은 이렇게 흐릅니다.

```mermaid
flowchart LR
  subgraph before[면접 전]
    RES[이력서 PDF 업로드] --> PREP[PREP 작업]
    PREP --> QS[사전 질문 · 요약]
  end

  subgraph during[면접 중]
    CALL["LiveKit 1:1 통화"] --> CAP[실시간 자막<br/>임시값]
    CALL --> REC[트랙 녹화 → S3]
    CAP --> SUG[꼬리질문 제안<br/>면접관 화면에만]
    CAP --> FIN[FINAL 전사 저장]
  end

  subgraph after[면접 후]
    RT[재전사] --> RV[REVIEW 작업]
    RV --> FD[findings]
    FD --> CHK[근거 확인 · 채택 → 검토 확정]
    CHK --> RP[REPORT 작업]
    RP --> OUT[리포트 · Markdown · PDF]
  end

  QS --> CALL
  FIN --> RT
  REC --> OUT
```

STT 와 분석이 실패해도 통화와 녹화는 끊기지 않도록 미디어 경로를 분리해 두었습니다. 실시간 자막은 임시값이고, 면접 후 재전사 결과를 최종으로 봅니다.

## 화면

| 지원자 관리 | 면접실 (실시간 자막 · 꼬리질문) |
| --- | --- |
| <img src="frontend/docs/screenshots/candidate-management/list-desktop.png" width="440" alt="지원자 관리 목록"> | <img src="frontend/docs/screenshots/248-room/room-questions-desktop.png" width="440" alt="면접실 화면"> |
| **지원자 동의** | **면접 리포트** |
| <img src="frontend/docs/screenshots/248-room/consent-desktop.png" width="440" alt="지원자 동의 화면"> | <img src="frontend/docs/screenshots/240-report/report-desktop.png" width="440" alt="면접 리포트 화면"> |

위 화면은 로컬 검증 데이터로 촬영한 것입니다. 구간별 촬영본과 검증 기록은 [`frontend/docs/screenshots/`](frontend/docs/screenshots/) 아래 각 디렉터리의 README 에 있습니다.

## 시스템 구조

EC2 한 대에서 `docker compose` 로 8개 컨테이너를 띄웁니다. Caddy 가 TLS 를 종료하고 경로별로 라우팅하며, WebRTC 미디어는 Caddy 를 거치지 않고 LiveKit 에 직접 붙습니다.

```mermaid
flowchart LR
  subgraph client[브라우저]
    ITV[면접관]
    CAND[지원자]
  end

  subgraph ec2[EC2 · docker compose]
    CADDY[Caddy<br/>TLS · 라우팅]
    FE[FE 정적 파일]
    BE[backend<br/>FastAPI]
    LK[LiveKit SFU]
    AI[ai<br/>livekit-agents 워커]
    POLLER[ai-poller<br/>PREP · REVIEW · REPORT]
    EG[egress 녹화]
    VK[(Valkey)]
    DB[(PostgreSQL 17)]
  end

  subgraph ext[외부]
    STT[Deepgram / Elice Whisper]
    LLM[LLM 게이트웨이<br/>OpenAI 호환]
    S3[("S3 rec/ · fe/")]
    CF[CloudFront]
  end

  ITV & CAND -->|HTTPS| CADDY
  ITV & CAND -->|"WebRTC 미디어<br/>7881/tcp · 7882/udp"| LK
  CADDY -->|"/api/* /health /docs"| BE
  CADDY -->|"/rtc*"| LK
  CADDY -->|나머지| FE
  BE --> DB
  BE -->|방 · 토큰 · 꼬리질문 SendData · TrackEgress| LK
  LK -->|웹훅| BE
  AI -->|마이크 트랙 구독| LK
  AI -->|자막 text stream| ITV
  AI -->|FINAL 전사 · 꼬리질문| BE
  AI --> STT
  AI --> LLM
  POLLER <-->|"/internal/v1"| BE
  POLLER --> LLM
  LK -->|녹화 작업 큐| VK
  VK --> EG
  EG -->|트랙 파일| S3
  BE -->|합친 파일 · 서명 URL| S3
  S3 --> CF -->|3시간 서명 URL| ITV
```

| 컨테이너 | 이미지 | 역할 |
| --- | --- | --- |
| `caddy` | `caddy:2.10` | TLS 종료, `/api/*` `/health` `/docs*` `/openapi.json` → backend, `/rtc*` → livekit, 나머지는 FE 정적 파일 |
| `backend` | 자체 빌드 (Python 3.12) | REST API, LiveKit 방·토큰, 녹화 병합·서명 URL, 내부 작업 큐 |
| `ai` | 자체 빌드 (Python 3.12) | LiveKit 방에 들어가 마이크 트랙을 구독, 실시간 전사와 꼬리질문 |
| `ai-poller` | 자체 빌드 (Python 3.12) | PREP · REVIEW · REPORT 작업을 폴링해 LLM 으로 처리 |
| `livekit` | `livekit/livekit-server:v1.13.6` | WebRTC SFU (7880 시그널링, 7881/tcp · 7882/udp 미디어) |
| `egress` | `livekit/egress:v1.13.0` | 트랙 녹화를 S3 `rec/` 에 업로드 |
| `db` | `postgres:17-alpine` | 면접 기록 저장 |
| `redis` | `valkey/valkey:8.1.10-alpine` | egress 작업 큐 |

전체 구조도와 외부 의존성 표는 [`docs/architecture/README.md`](docs/architecture/README.md) 에 있습니다.

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Frontend | React 19.2 · TypeScript · Vite · React Router 7 · TanStack Query 5 · Zustand 5 · Tailwind CSS 4 (`@tailwindcss/vite`) · `livekit-client` 2.22 · `write-excel-file` · Node.js 22.12+ (`.nvmrc`) |
| Backend | Python 3.12 · FastAPI · Uvicorn · PostgreSQL 17 (`psycopg[binary,pool]` 3.2) · `livekit-api` · PyJWT · boto3 · pydantic-settings · uv |
| AI | Python 3.12 · `livekit-agents` 1.8 · `livekit-plugins-deepgram` · `livekit-plugins-silero` · OpenAI 호환 LLM 게이트웨이 · `av` · aiohttp · hatchling · CLI `irya-ai` |
| STT | Deepgram 과 Elice Whisper 두 경로 (`STT_PROVIDER` 로 선택) |
| 외부 API | 카카오 로그인 · Elice Helpy 문서 본문 추출 |
| Infra | EC2 · docker compose · Caddy · LiveKit (self-hosted) · LiveKit egress · Valkey 8.1 · S3 (`rec/` 녹화 · `fe/` FE 빌드) · CloudFront · 도메인 `irya.cloud` |
| 품질 도구 | FE: eslint · prettier · `node --test` / BE: ruff (E, F, I, UP, B · line-length 88) · pyright standard · pytest / AI: ruff · pytest |

## 빠른 시작

각 파트의 세부 실행 방법과 환경변수 목록은 해당 디렉터리의 README 에 있습니다. 아래는 최소 명령만 적었습니다.

**사전 준비** — Node.js 22.12+, Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (PostgreSQL 을 띄울 때)

```bash
# Frontend  → http://localhost:5173
cd frontend
npm install
cp .env.example .env      # VITE_API_BASE 등
npm run dev

# Backend   → http://localhost:8000/docs
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload

# AI 워커 · 폴러
cd ai
uv sync --locked
cp .env.example .env && chmod 600 .env   # LIVEKIT_*, STT_PROVIDER, DEEPGRAM_API_KEY, ELICE_API_KEY, LLM_*, BACKEND_* 등
uv run python -m irya_ai.worker dev
uv run irya-ai-poller
```

- Backend 는 `DATABASE_URL` 이 없으면 인메모리 저장소로 뜹니다. PostgreSQL 로 돌리려면 `docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test -e POSTGRES_USER=irya -e POSTGRES_DB=irya postgres:17-alpine` 뒤에 `DATABASE_URL=postgresql://irya:test@localhost:55432/irya` 를 붙여 실행합니다.
- 운영 배포(EC2 docker compose, `deploy.sh`, 롤백, DB 백업, CloudFront)는 [`infra/README.md`](infra/README.md) 를 따릅니다.
- 모든 비밀값은 `.env` 에만 두고 커밋하지 않습니다. 각 디렉터리의 `.env.example` 에는 이름과 용도만 있습니다.

| 파트 | README |
| --- | --- |
| Frontend | [`frontend/README.md`](frontend/README.md) |
| Backend | [`backend/README.md`](backend/README.md) |
| AI | [`ai/README.md`](ai/README.md) |
| Infra | [`infra/README.md`](infra/README.md) · [`infra/livekit/README.md`](infra/livekit/README.md) |

## 저장소 구조

```text
.
├── frontend/   React · Vite SPA — 대시보드, 지원자 관리, 면접실, 검토, 리포트, 발표자료(public/presentation)
├── backend/    FastAPI — REST API, LiveKit 연동, 녹화·서명 URL, /internal/v1 작업 큐
├── ai/         livekit-agents 워커(실시간 STT · 꼬리질문), ai-poller(PREP · REVIEW · REPORT), CLI irya-ai
├── docs/       architecture/ 구조도 · api/openapi.json (CI 가 최신 여부를 검사) · accessibility/ 접근성 점검 · operations/ 운영 사용 기록
├── infra/      docker-compose.yml · Caddyfile · livekit/ · deploy.sh · CloudFront 설정
├── scripts/    공통 스크립트 자리
└── .github/    workflows 8개 · 이슈/PR 템플릿 · CODEOWNERS · dependabot
```

## 개발 규칙

**브랜치** — `main`(안정) / `develop`(통합) / `feature|fix|refactor|chore|hotfix/*`(작업)

**PR** — 제목은 `type(domain): message`, domain 은 `fe` `be` `ai` `common`. 이슈 1개 = PR 1개. `develop` 에는 머지 커밋으로 합치고, `dev protection` 룰셋이 approve 1건을 요구합니다. `develop` → `main` 은 리뷰를 거친 PR 로 올립니다.

**CI/CD** — `.github/workflows/` (이 밖에 캠퍼스 공통 워크플로 3개가 `main` PR 에서 돕니다)

| 워크플로 | 하는 일 |
| --- | --- |
| `fe-ci.yml` | `npm ci` → lint · format:check · test · typecheck · build |
| `be-ci.yml` | ruff check · ruff format · pyright · pytest · `docs/api/openapi.json` 이 최신인지 검사 |
| `ai-ci.yml` | ruff check · ruff format · pytest |
| `infra-ci.yml` | `caddy validate` |
| `cd.yml` | `develop` 푸시 → FE 빌드를 S3 `fe/<sha>/` 에 업로드 → EC2 가 받아 `infra/deploy.sh` 실행 → `/health` · `/version.json` 확인 |

## 문서

| 문서 | 내용 |
| --- | --- |
| [`docs/architecture/README.md`](docs/architecture/README.md) | 전체 구조도(mermaid), 컨테이너 · 외부 의존성 표 |
| [`docs/api/openapi.json`](docs/api/openapi.json) | OpenAPI 스펙 — 운영 `/docs` · `/redoc` 에서도 봅니다 |
| [`ai/README.md`](ai/README.md) | AI 워커 · 폴러 · CLI 사용법, 환경변수 |
| [`ai/docs/stt-pipeline.md`](ai/docs/stt-pipeline.md) | STT 파이프라인 설계와 범위 |
| [`ai/docs/stt-review.md`](ai/docs/stt-review.md) | STT 리뷰 · 검증 기록 |
| [`backend/README.md`](backend/README.md) | Backend 실행 · CI 명령 |
| [`frontend/README.md`](frontend/README.md) | Frontend 실행 · 라우트 · 로컬 연동 |
| [`infra/README.md`](infra/README.md) | 배포 · 롤백 · 백업 · CloudFront |
| [`infra/livekit/README.md`](infra/livekit/README.md) | self-hosted LiveKit 설정 · 포트 |
| [`docs/accessibility/kwcag-2026-10-report.md`](docs/accessibility/kwcag-2026-10-report.md) | KWCAG 2.2 점검 결과와 수정 내역 |
| [`docs/operations/pilot-log.md`](docs/operations/pilot-log.md) | 운영 사용 기록 — 운영 DB 에서 읽기 전용으로 뽑은 면접 · 단계별 실측 |
| [`frontend/public/presentation/index.html`](frontend/public/presentation/index.html) | 발표자료 — 운영 `/presentation` |

## 팀

카카오테크캠퍼스 4기 부산 1팀

| 역할 | 이름 |
| --- | --- |
| FE · BE | 김정태, 박종진 |
| AI | 이정원, 장하연 |
