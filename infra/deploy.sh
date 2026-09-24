#!/usr/bin/env bash
#
# 서버에서 도는 배포 스크립트.
#
#   cd ~/ktc4-pusan-1 && git fetch origin develop \
#     && git show origin/develop:infra/deploy.sh | bash -s develop
#
# CD 워크플로가 SSM 으로 이 형태를 그대로 부르고, 손으로도 같은 명령을 돌릴 수
# 있다. 배포 절차를 워크플로 YAML 안에 늘어놓지 않는 이유가 그거다 — 손으로
# 재현할 수 없는 배포는 실패했을 때 원인을 못 가린다.
#
# 디스크의 파일(`bash infra/deploy.sh develop`)이 아니라 배포할 ref 에서 꺼내
# 파이프로 넣는 이유는 둘이다. 서버에 파일이 없어도 돌아야 하고 (첫 CD 가
# 그래서 exit 127 로 죽었다), 아래 checkout 이 실행 중인 스크립트 파일을
# 갈아끼우면 bash 가 남은 줄을 엉뚱하게 읽는다.
#
# ⚠️ SSM 은 root 로 실행한다. 레포와 docker 는 ubuntu 소유라 sudo -u ubuntu 로
#    넘겨서 부른다 (아래 CD 워크플로 참고).

set -euo pipefail

REF="${1:-develop}"
# 경로는 스크립트 위치에서 끌어낸다 — 홈 디렉터리 이름을 박아 두면 레포를
# 옮기거나 다른 사용자로 돌릴 때 조용히 엉뚱한 곳을 본다.
# stdin 으로 흘려 넣으면(`ssh host bash -s < deploy.sh`) BASH_SOURCE 가 비므로
# 그때는 REPO_DIR 이나 기본 경로로 떨어진다.
if [ -f "${BASH_SOURCE[0]:-}" ]; then
	INFRA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	REPO="$(dirname "$INFRA")"
else
	REPO="${REPO_DIR:-$HOME/ktc4-pusan-1}"
	INFRA="$REPO/infra"
fi

log() { printf '\n▶ %s\n' "$*"; }

log "레포 갱신 → $REF"
cd "$REPO"
git fetch origin "$REF"

# livekit.yaml 변경을 미리 잡아 둔다. 단일 파일 바인드 마운트라 up -d 가
# 반영하지 않는다 (아래 Caddy 쪽 설명과 같은 이유다).
LK_CONFIG_CHANGED=$(git diff --name-only HEAD "origin/$REF" -- infra/livekit/ | wc -l)

# compose 가 바뀌면 바뀐 서비스를 up -d 가 재생성한다. 어느 서비스인지까지
# 가리려 했는데 믿을 방법이 없었다 — 이미지 태그 줄만 grep 하면 `logging:` 처럼
# 다른 키가 바뀐 경우를 놓치고(그 줄은 diff 에서 문맥 줄이다), `--dry-run` 은
# container_name 이 있으면 "Recreate" 대신 "Creating" 을 찍어 못 잡는다.
# 그래서 서비스를 안 가리고 경고한다. 덜 정확하지만 놓치지는 않는다.
COMPOSE_CHANGED=$(git diff --name-only HEAD "origin/$REF" -- infra/docker-compose.yml | wc -l)
# 로컬 브랜치에 병합하지 않고 detach 로 옮긴다.
#
# 전에는 `git merge --ff-only origin/$REF` 였다. develop 이 체크아웃된 서버에서
# 기능 브랜치를 한 번 배포했더니 그 커밋이 로컬 develop 에 fast-forward 로 얹혀
# origin/develop 과 갈라졌고, 그 뒤로는 모든 배포가 "Not possible to
# fast-forward" 에서 멈췄다. detach 면 로컬 브랜치가 움직이지 않으니 어떤 ref
# 를 배포해도 서버가 원격과 갈라지지 않는다.
#
# 서버에서 손으로 고친 추적 파일이 있으면 checkout 이 거부한다 — ff-only 가
# 지켜 주던 "서버의 수정을 조용히 덮어쓰지 않는다"는 성질은 그대로다.
git checkout --detach --quiet "origin/$REF"
echo "HEAD: $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"

cd "$INFRA"

# 서버에 뜬 컨테이너가 어느 커밋인지 이미지에 남긴다.
#
# 우리는 Registry 를 쓰지 않고 서버에서 빌드하므로 이미지에 버전 태그가 없다.
# 그러면 "지금 도는 게 어느 커밋이냐" 를 배포 로그를 뒤져야 알 수 있고, 장애
# 대응에서 그게 제일 먼저 필요한 정보다. compose 가 이 값을 빌드 인자와 라벨로
# 넘긴다 (`docker inspect`).
GIT_SHA=$(git -C "$REPO" rev-parse --short HEAD)
export GIT_SHA
echo "GIT_SHA: $GIT_SHA"

if [ "$COMPOSE_CHANGED" -gt 0 ]; then
	cat <<-'WARN'

		  ⚠️  docker-compose.yml 이 바뀌었습니다.
		      바뀐 서비스는 `up -d` 가 재생성합니다. livekit 이나 caddy 가 거기
		      들어가면 진행 중인 통화가 끊깁니다 (시그널링 /rtc* 이 caddy 를 지납니다).
		      통화가 없는 시간대인지 확인하고 배포하세요.
	WARN
fi

if [ "$LK_CONFIG_CHANGED" -gt 0 ]; then
	cat <<-'WARN'

		  ⚠️  infra/livekit/ 설정이 바뀌었는데 이 스크립트는 반영하지 않습니다.
		      LiveKit 재시작은 진행 중인 통화를 끊으므로 일부러 자동화하지 않았습니다.
		      통화가 없을 때 아래를 직접 실행하세요.

		        cd ~/ktc4-pusan-1/infra && docker compose restart livekit
	WARN
fi

log "이미지 빌드"
# 먼저 빌드만 한다. 실패해도 돌고 있는 컨테이너는 그대로다.
docker compose build

log "컨테이너 갱신"
docker compose up -d --remove-orphans

# ⚠️ 설정 파일은 위 up 이 보지 않는다.
#
# Caddyfile 은 단일 파일 바인드 마운트다. git checkout 은 파일을 제자리에서
# 고치지 않고 **갈아끼우므로**(inode 교체) 컨테이너의 마운트가 끊긴다. 확인해
# 보면 컨테이너 안에서 파일이 아예 사라진다.
#
#     $ docker compose exec caddy cat /etc/caddy/Caddyfile
#     cat: can't open '/etc/caddy/Caddyfile': No such file or directory
#
# Caddy 는 기동할 때 읽어 둔 설정으로 계속 돌기 때문에 당장 깨지지는 않지만,
# 새 설정이 영영 반영되지 않고 reload 도 못 한다. compose 는 "스펙이 안 바뀌었다"
# 고 판단해 컨테이너를 건드리지 않는다. restart 가 마운트를 다시 풀어 해결한다.
#
# ⚠️ 필요할 때만 돌린다. 전에는 매 배포마다 돌렸는데, **LiveKit 시그널링
# (`/rtc*`)도 Caddy 를 지난다.** 그래서 AI 나 BE 만 바뀐 배포에도 진행 중인
# 면접의 시그널링이 끊겼다. livekit 을 일부러 빼 둔 이유가 caddy 에도 있었다.
#
# "이번 배포에서 Caddyfile 이 바뀌었나" 를 git diff 로 보지 않는다. 배포가 빌드
# 에서 실패하면 HEAD 는 이미 옮겨져 있어서, 다시 돌릴 때 diff 가 비고 바뀐 설정이
# 영영 반영되지 않는다. 대신 **컨테이너가 실제로 물고 있는 파일**과 비교한다 —
# 지금 상태를 직접 보므로 재시도에도, 손으로 돌린 배포에도 맞다.
#
# 마운트가 끊겼으면 읽기가 실패해 해시가 비고, 그래서 안 맞아 재시작한다.
# 컨테이너가 안 떠 있을 때도 같은 결과다 — 둘 다 안전한 방향이다.
# 위 `up -d` 가 caddy 를 다시 만들었으면 이미 새 파일이라 해시가 같고 건너뛴다.
# `< /dev/null` 은 필수다. `docker compose exec` 는 `-T` 를 줘도 stdin 을 물고
# 있어서, 이 스크립트가 파이프로 실행되면 남은 줄을 통째로 먹는다. CD 는 파일로
# 실행하도록 고쳤지만(`.github/workflows/cd.yml`), 손으로 파이프를 태우는 경우가
# 있으니 여기서도 막는다.
running_config=$(docker compose exec -T caddy sha256sum /etc/caddy/Caddyfile \
	< /dev/null 2>/dev/null | cut -d' ' -f1 || true)
ondisk_config=$(sha256sum Caddyfile | cut -d' ' -f1)
if [ "$running_config" != "$ondisk_config" ]; then
	log "Caddy 설정 재적용 (컨테이너가 든 파일이 레포와 다름)"
	docker compose restart caddy
else
	log "Caddy 재시작 건너뜀 (설정 동일)"
fi

log "상태 확인"
docker compose ps --format '  {{.Service}}  {{.Status}}'

log "헬스 체크"
# 컨테이너 안이 아니라 Caddy 를 거쳐 확인한다 — 라우팅까지 봐야 의미가 있다.
#
# --resolve 로 127.0.0.1 에 붙되 TLS 는 irya.cloud 이름으로 검증한다.
#   http://localhost  → Caddy 가 HTTPS 로 308 리다이렉트한다
#   https://localhost → SNI 가 localhost 라 Caddy 가 받지 않는다 (연결 실패)
# 이렇게 하면 밖으로 안 나가면서도 TLS·라우팅까지 실제 경로 그대로 지난다.
for i in $(seq 1 30); do
	code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
		--resolve irya.cloud:443:127.0.0.1 https://irya.cloud/health || true)
	if [ "$code" = "200" ]; then
		echo "  /health 200 (${i}회째)"
		exit 0
	fi
	sleep 2
done

echo "  /health 가 60초 안에 200 을 주지 않았습니다 (마지막: ${code:-none})"
echo "--- backend 로그 ---"
docker compose logs --tail 40 backend
exit 1
