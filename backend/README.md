# IRYA Backend

## Requirements

- Python 3.12
- uv

## Install

```bash
uv sync
```

## Environment

```bash
cp .env.example .env
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

## 데모 데이터 (검토 화면)

AI 분석이 붙기 전에도 검토 화면을 끝까지 그릴 수 있게, FE 목(`demoReview.ts`)의 지원자 5명을 끝난 면접으로 넣습니다 (#163). 데모 계정으로 먼저 한 번 로그인해 사용자를 만든 뒤, 그 사용자 id(`usr_…`)로 돌립니다. 다시 돌려도 중복되지 않습니다.

```bash
# 서버
docker compose exec backend python -m app.seed_demo --owner usr_xxx
# 로컬 — DB 가 있어야 한다. 인메모리로 띄운 BE 에는 넣을 길이 없다
DATABASE_URL=postgresql://irya:test@localhost:55432/irya uv run python -m app.seed_demo --owner usr_xxx
```

분석 내용은 `app/demo_review.json` 한 벌을 다섯 명이 함께 씁니다. 계산 규칙 테스트도 같은 파일을 읽습니다.

## CI 와 같은 검사 돌리기

아래 다섯이 `be-ci` 가 도는 순서입니다. **`pytest` 만 돌리면 CI 에서 떨어집니다.**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run python -m scripts.dump_openapi && git diff --exit-code ../docs/api/openapi.json
```

마지막 줄은 `docs/api/openapi.json` 이 현재 코드가 내보내는 스펙과 같은지 봅니다. 라우트나 스키마를 건드리면 덤프를 다시 떠서 **같이 커밋해야 합니다.** 서버가 내주는 문서와 저장소에 든 문서가 갈라지지 않게 하려는 장치입니다.

```bash
uv run python -m scripts.dump_openapi
git add ../docs/api/openapi.json
```

## 저장소 계약 테스트

`tests/test_store_contract.py` 는 같은 테스트를 인메모리와 PostgreSQL 두 구현에 돌립니다. 인메모리는 객체를 참조로 돌려주고 DB 는 매번 새로 만들어 주기 때문에, 규약을 글로만 적어 두면 두 구현이 갈라집니다.

**PostgreSQL 쪽은 `TEST_DATABASE_URL` 이 있을 때만 돕니다.** 없으면 조용히 건너뜁니다. 기본값이 건너뛰기인 것은 DB 없이도 `pytest` 가 돌게 하려는 의도이고, CI 도 같은 이유로 건너뜁니다.

실제로 돌려 보려면 DB 를 띄우고 주소를 넘깁니다.

```bash
docker run --rm -d -p 55432:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_USER=irya -e POSTGRES_DB=irya \
  postgres:17-alpine

TEST_DATABASE_URL=postgresql://irya:test@localhost:55432/irya uv run pytest
```

배포 환경과 같은 PostgreSQL 17 을 씁니다. 저장 계층을 고쳤다면 올리기 전에 이걸 한 번 돌려 보는 편이 좋습니다.

## Format

```bash
uv run ruff format .
```
