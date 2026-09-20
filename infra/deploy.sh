#!/usr/bin/env bash
#
# 서버에서 도는 배포 스크립트.
#
#   ~/ktc4-pusan-1/infra/deploy.sh [ref]
#
# CD 워크플로가 SSM 으로 이걸 부르고, 손으로도 같은 명령을 돌릴 수 있다.
# 배포 절차를 워크플로 YAML 안에 늘어놓지 않는 이유가 그거다 — 손으로 재현할
# 수 없는 배포는 실패했을 때 원인을 못 가린다.
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

# LiveKit 변경을 미리 잡아 둔다. 둘 다 조용히 지나가는 종류라 로그에 드러낸다.
#   livekit.yaml  단일 파일 바인드 마운트라 up -d 가 반영하지 않는다 (아래 참고)
#   이미지 태그   up -d 가 자동으로 재생성한다 → 진행 중인 통화가 끊긴다
LK_CONFIG_CHANGED=$(git diff --name-only HEAD "origin/$REF" -- infra/livekit/ | wc -l)
LK_IMAGE_CHANGED=$(git diff HEAD "origin/$REF" -- infra/docker-compose.yml \
	| grep -c '^[+-].*livekit/livekit-server:' || true)
# --ff-only: 서버에서 로컬 커밋이 생겼거나 히스토리가 갈라졌으면 여기서 멈춘다.
# 자동으로 merge 커밋을 만들면 서버 상태가 레포와 조용히 달라진다.
git merge --ff-only "origin/$REF"
echo "HEAD: $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"

cd "$INFRA"

if [ "$LK_IMAGE_CHANGED" -gt 0 ]; then
	cat <<-'WARN'

		  ⚠️  LiveKit 이미지 태그가 바뀌었습니다.
		      아래 `up -d` 가 LiveKit 을 재생성하고, 진행 중인 통화가 전부 끊깁니다.
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
# Caddyfile 은 단일 파일 바인드 마운트라, git 이 파일을 갈아끼우면 inode 가
# 바뀌어 컨테이너의 마운트가 옛 파일에 남는다. compose 는 "스펙이 안 바뀌었다"고
# 판단해 컨테이너를 건드리지 않고, caddy reload 도 소용없다 — 컨테이너가 보는
# 파일 자체가 옛것이다. 조용히 실패하는 종류라 매 배포마다 확인 대신 그냥 돌린다.
#
# restart 는 컨테이너 시작 시점에 마운트를 다시 풀어서 이걸 해결한다.
# (livekit 은 일부러 빼 둔다 — 재시작하면 진행 중인 통화가 끊긴다.
#  livekit.yaml 을 바꿨을 때만 손으로 돌린다.)
log "Caddy 설정 재적용"
docker compose restart caddy

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
