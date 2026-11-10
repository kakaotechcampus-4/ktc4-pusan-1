# 기여 가이드

기준 2026-11-10 · `develop` `c78c543`

지금 저장소가 실제로 돌아가는 방식과, 앞으로 이렇게 맞추자는 것을 같이 적었습니다. 어느 쪽인지 헷갈릴 만한 곳은 본문에서 구분해 두었습니다. 지금까지는 이 내용이 이슈·PR 템플릿과 워크플로 파일 안에만 흩어져 있어서 저장소를 처음 보는 사람이 모아 볼 곳이 없었습니다.

세부 규칙은 `docs/conventions/` 아래에 나눠 두었습니다.

| 문서 | 내용 |
| --- | --- |
| [docs/conventions/branches.md](docs/conventions/branches.md) | 브랜치 전략, 이름 규칙, 보호 규칙 |
| [docs/conventions/commits.md](docs/conventions/commits.md) | 커밋 메시지 형식과 scope |
| [docs/conventions/issues-and-prs.md](docs/conventions/issues-and-prs.md) | 이슈·PR 템플릿과 연결 규칙 |
| [docs/conventions/review.md](docs/conventions/review.md) | 리뷰 요청·응답 방식 |

## 한 사이클

1. 할 일을 **이슈로 먼저 올립니다.** 템플릿은 `기능`(`feature.md`)과 `버그`(`bug.md`) 두 개입니다.
2. `develop` 에서 `feature/<이슈번호>-<슬러그>` 브랜치를 땁니다.
3. 작업하고 `type(scope): 한국어 요약` 형식으로 커밋합니다.
4. `develop` 으로 PR 을 올립니다. 본문 맨 위 `Closes #<이슈번호>` 를 반드시 채웁니다.
5. **승인 1건**을 받아야 머지됩니다. 리뷰는 코멘트가 아니라 Approve / Request changes 로 제출해 주세요.
6. 머지 방식은 **merge commit 만** 열려 있습니다. Squash·Rebase 버튼은 눌리지 않습니다.

## 환경 변수와 비밀값

값은 어떤 형태로도 커밋하지 않습니다. 새 환경 변수가 필요하면 **이름과 용도만** PR 본문에 적고, 실제 값은 저장소 Secrets 에 넣거나 운영 담당에게 전달합니다. `.env.example` 류에도 자리표시자만 둡니다.

## CI

파트별로 경로가 갈려 있어서, 내 PR 에 어떤 검사가 도는지는 건드린 디렉터리로 결정됩니다.

| 워크플로 | 도는 조건 |
| --- | --- |
| `ai-ci.yml` | `ai/**` 변경 |
| `be-ci.yml` | `backend/**` 변경 |
| `fe-ci.yml` | `frontend/**` 변경 |
| `infra-ci.yml` | `infra/Caddyfile` 변경 |
| `cd.yml` | `develop` push 시 배포 |

`pull_request` 트리거의 base 는 `develop` 뿐 아니라 `feature/**`, `fix/**`, `chore/**`, `refactor/**`, `perf/**` 까지 걸려 있습니다. 스택 PR(앞선 feature 브랜치를 base 로 두는 PR)에 검사가 아예 안 돌던 문제 때문에 넓혀 둔 것입니다(`.github/workflows/ai-ci.yml:5-9` 주석).

루트 `docs/`, `CONTRIBUTING.md`, `README.md` 만 바꾸는 PR 에는 어떤 CI 도 돌지 않습니다. 그게 정상입니다. 반대로 `ai/docs/` 처럼 파트 디렉터리 안의 문서는 경로 필터에 걸려 해당 파트 CI 가 돕니다.

## 손대지 않는 파일

운영진 소유라서 수정·삭제하면 멘토 자동 지정과 Discord 알림이 깨집니다(`.github/CODEOWNERS:62-65`).

- `.github/workflows/assign-mentor.yml`
- `.github/workflows/notify-discord.yml`
- `.github/workflows/convention-check.yml`
- `.github/CODEOWNERS` 의 [운영진 영역] 4줄

반대로 **팀 자체 워크플로 추가와 이슈·PR 템플릿 수정은 명시적으로 허용**되어 있습니다. 위 4개만 피하면 됩니다.

## 저장소 기본값과 지금 운영이 다른 것

- **`main-protection` 은 삭제·강제푸시만 막습니다.** PR 필수도, CODEOWNERS 리뷰 필수도 걸려 있지 않습니다(`rulesets/21067787`). `CODEOWNERS` 파일 안 운영진 메모는 main ruleset 에 `require_code_owner_review` 가 함께 걸린다고 적고 있는데, 실제 조회값에는 그 규칙이 없습니다. 즉 CODEOWNERS 는 지금 **리뷰 요청 표시까지만** 하고 차단은 하지 않습니다.
- **필수 상태 검사가 없습니다.** CI 가 빨개도 승인 1건만 있으면 머지 버튼이 열립니다. 그래서 실질적인 게이트는 CI 가 아니라 리뷰입니다.
- **`convention-check.yml` 은 우리 PR 에 돌지 않습니다.** `on: pull_request … branches: [main]` 이라서 `develop → main` PR 에서만 뜨고, 규칙 본문도 외부 저장소(`kakaotechcampus-4/pr-pipeline`)에서 가져옵니다. 이 문서의 규칙은 그 워크플로가 검사해 주는 게 아니라 우리끼리 지키는 것입니다.

## 남겨 둔 것

- 과거 브랜치·커밋 이름은 아래 규칙과 다른 것이 섞여 있습니다. 소급해서 고치지 않고 **앞으로 올리는 것부터** 맞춥니다.
- 라벨은 GitHub 기본 라벨 + Dependabot 라벨뿐이고 파트·우선순위 라벨이 없습니다. 쓸지 말지 정하지 않았습니다.
