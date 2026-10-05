# 배포

이 디렉터리가 서버에서 도는 것 전부입니다. 컨테이너 구성(`docker-compose.yml`), 리버스 프록시(`Caddyfile`), 배포 스크립트(`deploy.sh`), LiveKit 설정(`livekit/`).

LiveKit 서버 자체의 설정과 포트 요구사항은 [`livekit/README.md`](./livekit/README.md) 에 따로 있습니다.

## 무엇이 어디서 도나

EC2 한 대에 컨테이너 넷입니다.

```
                     :80 :443
                        │
                   ┌────┴────┐
                   │  caddy  │  TLS 종료 · 라우팅 · FE 정적 파일
                   └────┬────┘
          ┌─────────────┼─────────────┐
          │             │             │
   /api/* /health     /rtc*      나머지 전부
   /docs* /redoc*       │             │
   /openapi.json        │             │
          │             │             │
     ┌────┴────┐  ┌─────┴─────┐  /home/ubuntu/fe
     │ backend │  │  livekit  │  (호스트 디렉터리를 읽기 전용 마운트)
     └────┬────┘  └───────────┘
          │            :7881/tcp  :7882/udp  ← 미디어는 Caddy 를 거치지 않음
     ┌────┴────┐
     │   db    │  PostgreSQL 17
     └─────────┘
```

밖에서 닿는 포트는 `80` · `443/tcp` · `443/udp`(HTTP/3) · `7881/tcp` · `7882/udp` 뿐입니다. `backend:8000` · `livekit:7880` · `db:5432` 는 퍼블리싱하지 않고 compose 네트워크 안에서 서비스 이름으로만 부릅니다.

## 배포가 도는 방식

`develop` 에 push 하면 자동으로 돕니다.

```
push develop
  → .github/workflows/cd.yml
  → aws ssm send-command (22번 포트를 열지 않아 SSH 대신 SSM 입니다)
  → 서버가 배포할 ref 에서 deploy.sh 를 꺼내 /tmp 에 쓰고 실행
```

`deploy.sh` 가 하는 일은 순서대로 이렇습니다.

1. `git fetch` 후 `git checkout --detach origin/<ref>`
2. LiveKit 설정과 compose 가 바뀌었는지 미리 확인해 경고를 찍는다
3. `docker compose build` — 먼저 빌드만 한다. 실패해도 돌던 컨테이너는 그대로다
4. `docker compose up -d --remove-orphans`
5. Caddy 는 **컨테이너가 든 설정이 레포와 다를 때만** 재시작한다
6. `docker compose ps` 로 상태를 찍고, `/health` 가 200 을 줄 때까지 최대 60초 기다린다

**배포 절차를 워크플로 YAML 이 아니라 스크립트에 둔 이유**는 손으로 재현할 수 있어야 하기 때문입니다. 실패했을 때 GitHub Actions 로그만 보고 원인을 가릴 수 있는 배포는 많지 않습니다.

`cd.yml` 은 `send-command` 를 던지고 끝내지 않고 상태를 폴링합니다. 비동기 호출이라 폴링을 빼면 **서버가 실패해도 워크플로는 초록불**이 됩니다.

### 서버는 detached HEAD 로 돕니다

`deploy.sh` 가 로컬 브랜치에 병합하지 않고 `origin/<ref>` 로 detach 합니다.

전에는 `git merge --ff-only` 였습니다. `develop` 이 체크아웃된 서버에 기능 브랜치를 한 번 배포했더니 그 커밋이 로컬 `develop` 에 얹혀 `origin/develop` 과 갈라졌고, **그 뒤로는 모든 배포가 「Not possible to fast-forward」에서 멈췄습니다.**

detach 면 로컬 브랜치가 움직이지 않아 어떤 ref 를 배포해도 서버가 원격과 갈라지지 않습니다. 서버에서 손으로 고친 추적 파일이 있으면 `checkout` 이 거부하므로, 「서버의 수정을 조용히 덮어쓰지 않는다」는 성질은 그대로입니다.

### 배포 스크립트는 서버 디스크에서 읽지 않습니다

`cd.yml` 이 배포할 ref 에서 꺼내 `/tmp/irya-deploy.sh` 에 쓰고 그 파일을 돌립니다. 서버에 그 파일이 없으면 CD 가 통째로 죽기 때문입니다 — **첫 실행이 `No such file or directory` 로 끝났습니다.** 스크립트를 서버에 가져다주는 게 그 스크립트 자신이라 서로를 기다리는 꼴이었습니다.

파일로 쓰고 돌리는 것이 중요합니다. **파이프로 넣으면(`| bash -s`) 스크립트가 중간에서 잘립니다.** 안쪽의 `docker compose exec -T` 가 stdin 을 먹어서 나머지를 읽어 가고, bash 는 EOF 를 만나 **0 으로 끝납니다.** 배포가 절반만 돌았는데 CD 는 초록불이 됩니다.

덤으로 배포되는 코드와 배포 절차의 버전이 항상 같이 갑니다.

### 어떤 커밋이 떠 있는지 확인하기

`deploy.sh` 가 서비스마다 **그 폴더를 마지막으로 바꾼 커밋**(`git log -1 -- backend`, `-- ai`)을 내보내고, compose 가 이미지 라벨에 박습니다.

```bash
docker inspect irya-backend --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
docker inspect irya-ai --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

코드가 그대로면 컨테이너도 그대로입니다 (#134, 베이스는 digest 고정). **`ai/` · `backend/` 나 베이스 digest 를 바꾸는 머지는 면접이 없는 시간에 합니다** — 다시 만들어진 워커는 진행 중인 방으로 돌아가지 않습니다.

「그대로」는 빌드 캐시에도 기댑니다. 서버의 빌드 캐시가 비면(`docker builder prune` 등) 코드가 그대로여도 다음 배포에서 한 번 다시 만들어집니다.

## 손으로 배포하기

```bash
cd ~/ktc4-pusan-1
git fetch origin develop
git show origin/develop:infra/deploy.sh > /tmp/irya-deploy.sh
bash /tmp/irya-deploy.sh develop
```

CD 가 부르는 것과 같은 형태입니다. **`./deploy.sh develop` 으로 디스크의 파일을 직접 돌리지 마세요.** 스크립트 안의 `checkout` 이 실행 중인 그 파일을 갈아끼웁니다. 파이프(`| bash -s`)도 안 됩니다 — 안쪽에서 stdin 을 읽는 명령이 남은 줄을 먹어서, 뒷부분이 실행되지 않은 채 종료 코드 0 이 나갑니다.

## 롤백

Actions 탭의 **CD → Run workflow** 에서 `ref` 에 되돌릴 **브랜치 이름**을 넣습니다. 기본 브랜치가 `develop` 이라 버튼이 보입니다.

**커밋 SHA 와 태그는 받지 못합니다.** `deploy.sh` 가 `origin/<ref>` 로 체크아웃하는데, 원격 추적 ref(`refs/remotes/origin/*`)는 브랜치를 fetch 할 때만 생깁니다. 태그도 SHA 도 `FETCH_HEAD` 에만 기록됩니다.

```
$ git fetch origin v1
 * tag  v1  -> FETCH_HEAD        ← refs/tags 에도 안 들어갑니다
```

되돌릴 커밋을 브랜치로 push 한 뒤 그 이름을 넣으세요.

```bash
git branch rollback-0927 <커밋 SHA>
git push origin rollback-0927
# → Actions 탭에서 ref 에 rollback-0927
```

서버에서 직접 할 수도 있습니다.

```bash
cd ~/ktc4-pusan-1
git fetch origin rollback-0927
git show origin/rollback-0927:infra/deploy.sh > /tmp/irya-deploy.sh
bash /tmp/irya-deploy.sh rollback-0927
```

### ⚠️ 되돌릴 수 있는 범위

**`#102` 이전 커밋으로는 롤백되지 않습니다.** 위 명령이 배포할 ref **에서** `deploy.sh` 를 꺼내 `/tmp` 에서 돌리는데, 그 시점의 스크립트는 경로를 `BASH_SOURCE` 로만 잡습니다. `/tmp` 에서 돌면 `REPO=/` 가 되어 `git fetch` 에서 죽습니다.

```
REPO=/
fatal: not a git repository (or any of the parent directories): .git
```

「배포되는 코드와 배포 절차의 버전이 항상 같이 간다」는 성질의 뒷면입니다. 옛 코드로 돌아가면 옛 절차도 같이 돌아갑니다.

당장 급하면 최신 스크립트에 옛 ref 를 넘기면 됩니다. Actions 버튼으로는 안 되고 서버에서만 됩니다.

```bash
git show origin/develop:infra/deploy.sh > /tmp/irya-deploy.sh
bash /tmp/irya-deploy.sh rollback-0927
```

## FE 는 CD 밖입니다

`caddy` 가 호스트의 `/home/ubuntu/fe` 를 읽기 전용으로 마운트해 그대로 내보냅니다. **저장소에도 이미지에도 FE 빌드 결과가 들어 있지 않습니다** — 컨테이너가 보는 파일은 호스트 디렉터리입니다.

그래서 FE 를 고치면 손으로 올려야 합니다. 자동화는 #103 에서 다룹니다.

```bash
cd frontend && npm run build
# dist/ 를 서버의 /home/ubuntu/fe 로 복사
```

⚠️ `cd.yml` 의 `paths` 에 `frontend/**` 가 있어서 **FE 만 바뀐 push 도 CD 를 돌립니다.** 그런데 FE 는 올라가지 않습니다 — caddy 가 서빙하지만 내용물이 `/home/ubuntu/fe` 라는 호스트 디렉터리에 있고, `deploy.sh` 는 거기를 건드리지 않습니다. 초록불을 「올라갔다」로 읽으면 안 됩니다.

AI 워커는 다릅니다. compose 의 `ai` 서비스(#84)가 `backend` 와 같이 서버에서 빌드되어 `up -d` 로 올라갑니다. 워커는 LiveKit 컨테이너에 등록만 하고 공개 포트가 없어서, 올라갔는지는 `docker compose logs ai` 의 `joined room=` · `microphone subscribed` 로그로 봅니다.

## DB 백업

`backup-db.sh` 가 매일 KST 새벽 4시에 `pg_dump` 를 떠서 S3 `ktc4-pusan-1-irya/db/` 에 올립니다. 30일 지난 덤프는 S3 수명주기(`s3-lifecycle.json`)가 지웁니다. cron 은 서버 `ubuntu` 사용자의 crontab 에 아래 한 줄로 걸어 둡니다 (`crontab -e`). 서버는 UTC 라 19시가 KST 새벽 4시입니다.

```
0 19 * * * $HOME/ktc4-pusan-1/infra/backup-db.sh >> $HOME/backup-db.log 2>&1
```

시연 · 평가 직전에는 손으로 한 번 더 돌립니다.

```bash
~/ktc4-pusan-1/infra/backup-db.sh
```

수명주기는 버킷에 하나뿐이라 걸 때마다 통째로 바뀝니다. 규칙을 더할 때는 `s3-lifecycle.json` 을 고치고 다시 겁니다.

```bash
aws s3api put-bucket-lifecycle-configuration --bucket ktc4-pusan-1-irya \
  --lifecycle-configuration file://infra/s3-lifecycle.json
```

### 복구

운영 DB 와 따로 빈 Postgres 를 띄워 거기에 풀어 봅니다. 서버에는 aws CLI 가 없어 컨테이너로 받고, `--network host` 를 빼면 인스턴스 역할 자격증명을 못 받습니다.

```bash
docker run --rm --network host -v "$PWD:/d" amazon/aws-cli:2.37.9 \
  s3 cp s3://ktc4-pusan-1-irya/db/<이름>.dump /d/ --region ap-northeast-2

docker run -d --name irya-restore -e POSTGRES_PASSWORD=x postgres:17-alpine
# -h 127.0.0.1 로 본다. 초기화 중의 임시 서버는 소켓으로만 받아서, 소켓으로 보면 재시작 전에 준비됐다고 나온다
until docker exec irya-restore pg_isready -h 127.0.0.1 -U postgres; do sleep 1; done
# 스키마 경고 몇 줄과 exit 1 이 나올 수 있다. 성공 여부는 아래 행 수로 판단한다
docker exec -i irya-restore pg_restore -U postgres -d postgres --no-owner --no-privileges < <이름>.dump
docker exec irya-restore psql -U postgres -Atc 'select count(*) from interview' -c 'select count(*) from session'
docker rm -f irya-restore
```

## 비밀

`infra/.env` 에 한 곳에 모여 있고 **서버에만 있습니다.** 저장소에는 `.env.example` 의 빈 자리와 출처 설명만 들어갑니다.

값을 바꿀 때는 **SSM `send-command` 를 쓰지 마세요.** 파라미터가 평문으로 로그에 남습니다. 세션으로 들어가 직접 편집합니다.

값을 다 잃어버려도 전부 재발급할 수 있습니다. 어디서 나오는 값인지는 `.env.example` 에 적혀 있습니다.

## 밟기 쉬운 것들

### Caddyfile 은 `up -d` 로 반영되지 않습니다

단일 파일 바인드 마운트라, git 이 파일을 갈아끼우면 **inode 가 바뀌어 컨테이너의 마운트가 끊깁니다.** compose 는 스펙이 안 바뀌었다고 판단해 컨테이너를 건드리지 않고, `caddy reload` 도 소용없습니다 — 컨테이너가 보는 파일이 더 이상 디스크의 그 파일이 아닙니다.

실제로 확인해 보면 컨테이너 안에서 파일이 아예 사라져 있습니다.

```
cat: can't open '/etc/caddy/Caddyfile': No such file or directory
```

그래서 `deploy.sh` 가 **컨테이너 안의 파일과 레포의 파일을 해시로 비교**해서, 다를 때만 재시작합니다. 시작 시점에 마운트를 다시 풀어야 해결되기 때문입니다.

```bash
running_config=$(docker compose exec -T caddy sha256sum /etc/caddy/Caddyfile < /dev/null ...)
ondisk_config=$(sha256sum Caddyfile ...)
```

`git diff` 로 판단하지 않는 이유는 재시도 구멍 때문입니다. 배포가 빌드에서 실패하면 HEAD 는 이미 움직여 있어서, 다시 돌릴 때 `git diff` 가 「안 바뀌었다」고 답합니다. 컨테이너 상태를 직접 보면 몇 번을 다시 돌려도 같은 답이 나옵니다.

`exec` 에 `< /dev/null` 이 붙은 것도 이유가 있습니다. 이 스크립트를 **파이프로 실행하면** 붙이지 않은 `exec` 가 **남은 줄을 stdin 으로 먹습니다.** CD 는 파일로 실행하므로 해당하지 않지만, 손으로 파이프를 태우는 경우가 있어 여기서도 막아 둡니다.

### LiveKit 은 일부러 자동 재시작하지 않습니다

재시작하면 **진행 중인 통화가 전부 끊깁니다.** `infra/livekit/` 이 바뀌면 `deploy.sh` 가 경고만 찍고 넘어갑니다. 통화가 없을 때 직접 돌리세요.

```bash
cd ~/ktc4-pusan-1/infra && docker compose restart livekit
```

`docker-compose.yml` 이 **어디든** 바뀌면 이야기가 다릅니다. `up -d` 가 바뀐 서비스를 재생성하므로, 거기에 livekit 이나 caddy 가 들어가면 통화가 끊깁니다. `deploy.sh` 는 이미지 태그만 보는 게 아니라 **파일이 바뀌었는지**만 보고 경고합니다.

공인 IP 가 바뀐 뒤에도 재시작이 필요합니다. `use_external_ip` 는 **기동 때 한 번만** STUN 으로 탐지해서, 재시작 전까지 옛 IP 를 계속 광고합니다. 화면은 뜨는데 미디어만 안 붙는 증상이 납니다.

### compose 의 `:?` 는 `ps` · `logs` · `down` 까지 막습니다

`${VAR:?}` 는 값이 없으면 기동을 막아 주지만, 그 보간이 **모든 compose 명령에서 일어납니다.** 값이 빠지면 컨테이너가 안 뜨는 것까지는 의도대로인데 서버에서 로그조차 못 봅니다. 수습할 방법이 없어집니다.

그래서 `:?` 는 없으면 애초에 아무것도 못 하는 값에만 씁니다.

```
:?  POSTGRES_PASSWORD · LIVEKIT_API_KEY · LIVEKIT_API_SECRET
:-  INTERNAL_API_KEY — 대신 APP_ENV=production 일 때 BE 가 기동을 거부합니다
```

### `/internal/v1` 은 Caddy 가 프록시하지 않습니다

`Caddyfile` 이 여는 것은 `/rtc*` · `/api/*` · `/health` · `/docs*` · `/redoc*` · `/openapi.json` 뿐이고 나머지는 전부 FE 로 떨어집니다. 그래서 밖에서 `/internal/v1` 을 부르면 401 이 아니라 **FE 페이지가 돌아옵니다.**

인터넷에 노출되지 않는다는 점에서는 의도한 그대로지만, 밖에서 인증을 확인할 수 없다는 뜻이기도 합니다. 같은 compose 네트워크 안에서만 검증됩니다.

`/twirp` 도 같은 이유로 일부러 열지 않습니다. 열면 방 생성·강제퇴장 API 가 인터넷에 노출됩니다.

## 상태 확인

```bash
cd ~/ktc4-pusan-1/infra
docker compose ps
docker compose logs --tail 50 backend
curl -s https://irya.cloud/health
```

로그는 컨테이너마다 **10MB × 3개**로 돌려 씁니다. 기본값은 무제한이라 디스크가 찰 때까지 자랍니다.

배포 서버에서는 Swagger 가 열려 있습니다.

```
https://irya.cloud/docs
https://irya.cloud/redoc
https://irya.cloud/openapi.json
```

`openapi.json` 은 저장소의 `docs/api/openapi.json` 과 같아야 하고 `be-ci` 가 그것을 강제합니다. 그래서 따로 가리지 않습니다.
