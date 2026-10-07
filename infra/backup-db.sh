#!/usr/bin/env bash
#
# DB 를 덤프해 S3 의 db/ 에 올린다 (#113). 서버 cron 이 매일 돌리고, 시연 ·
# 평가 직전에는 손으로 한 번 더 돌린다.
#
#   0 19 * * * $HOME/ktc4-pusan-1/infra/backup-db.sh >> $HOME/backup-db.log 2>&1
#
# 서버는 UTC 라 19시가 KST 새벽 4시다. 30일 지난 덤프는 S3 수명주기
# (infra/s3-lifecycle.json)가 지우므로 여기서 지우지 않는다.
#
# ⚠️ aws-cli 컨테이너의 --network host 를 빼지 않는다. 인스턴스 메타데이터의
#    홉 제한이 1 이라 bridge 네트워크 컨테이너는 인스턴스 역할 자격증명을
#    받지 못한다. 서버에는 aws CLI 가 깔려 있지 않다.

set -euo pipefail

BUCKET=ktc4-pusan-1-irya
AWS_CLI=amazon/aws-cli:2.37.9
INFRA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="irya-$(date -u +%Y%m%dT%H%MZ).dump"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cd "$INFRA"
# -Fc 는 이미 압축된 형식이라 gzip 을 따로 걸지 않는다. `< /dev/null` 은
# deploy.sh 와 같은 이유다 (exec 가 -T 여도 stdin 을 문다).
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
	< /dev/null > "$TMP/$NAME"

# pg_dump 가 실패하면 위에서 끝난다. 빈 파일이 조용히 쌓이는 것만 여기서 막는다.
[ -s "$TMP/$NAME" ] || { echo "빈 덤프라 올리지 않는다: $NAME" >&2; exit 1; }

docker run --rm --network host -v "$TMP:/dump:ro" "$AWS_CLI" \
	s3 cp "/dump/$NAME" "s3://$BUCKET/db/$NAME" --region ap-northeast-2 --only-show-errors
echo "올림: s3://$BUCKET/db/$NAME ($(wc -c < "$TMP/$NAME" | tr -d " ") bytes)"
