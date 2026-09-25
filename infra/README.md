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
    /api/* /health    /rtc*      나머지 전부
          │             │             │
     ┌────┴────┐  ┌─────┴─────┐  /home/ubuntu/fe
     │ backend │  │  livekit  │  (호스트 디렉터리를 읽기 전용 마운트)
     └────┬────┘  └───────────┘
          │            :7881/tcp  :7882/udp  ← 미디어는 Caddy 를 거치지 않음
     ┌────┴────┐
     │   db    │  PostgreSQL 17
     └─────────┘
```

밖에서 닿는 포트는 `80` · `443` · `7881/tcp` · `7882/udp` 뿐입니다. `backend:8000` · `livekit:7880` · `db:5432` 는 퍼블리싱하지 않고 compose 네트워크 안에서 서비스 이름으로만 부릅니다.

## 배포가 도는 방식

`develop` 에 push 하면 자동으로 돕니다.

```
push develop
  → .github/workflows/cd.yml
  → aws ssm send-command (22번 포트를 열지 않아 SSH 대신 SSM 입니다)
  → 서버에서 infra/deploy.sh 실행
```

`deploy.sh` 가 하는 일은 순서대로 이렇습니다.

1. `git fetch` 후 `origin/<ref>` 로 fast-forward
2. LiveKit 설정·이미지 태그가 바뀌었는지 미리 확인해 경고를 찍는다
3. `docker compose build` — 먼저 빌드만 한다. 실패해도 돌던 컨테이너는 그대로다
4. `docker compose up -d --remove-orphans`
5. `docker compose restart caddy`
6. `docker compose ps` 로 상태를 찍고, `/health` 가 200 을 줄 때까지 최대 60초 기다린다

**배포 절차를 워크플로 YAML 이 아니라 스크립트에 둔 이유**는 손으로 재현할 수 있어야 하기 때문입니다. 실패했을 때 GitHub Actions 로그만 보고 원인을 가릴 수 있는 배포는 많지 않습니다.

`cd.yml` 은 `send-command` 를 던지고 끝내지 않고 상태를 폴링합니다. 비동기 호출이라 폴링을 빼면 **서버가 실패해도 워크플로는 초록불**이 됩니다.

## 손으로 배포하기

```bash
cd ~/ktc4-pusan-1/infra
./deploy.sh develop
```

CD 가 부르는 것과 같은 명령입니다.

## 롤백

Actions 탭의 **CD → Run workflow** 에서 `ref` 에 되돌릴 커밋이나 태그를 넣습니다. 기본 브랜치가 `develop` 이라 버튼이 보입니다.

서버에서 직접 할 수도 있습니다.

```bash
cd ~/ktc4-pusan-1/infra
./deploy.sh <커밋 SHA>
```

## FE 는 CD 밖입니다

`caddy` 가 호스트의 `/home/ubuntu/fe` 를 읽기 전용으로 마운트해 그대로 내보냅니다. **저장소에도 컨테이너에도 FE 빌드 결과가 들어 있지 않습니다.**

그래서 FE 를 고치면 손으로 올려야 합니다. 자동화는 #103 에서 다룹니다.

```bash
cd frontend && npm run build
# dist/ 를 서버의 /home/ubuntu/fe 로 복사
```

## 비밀

`infra/.env` 에 한 곳에 모여 있고 **서버에만 있습니다.** 저장소에는 `.env.example` 의 빈 자리와 출처 설명만 들어갑니다.

값을 바꿀 때는 **SSM `send-command` 를 쓰지 마세요.** 파라미터가 평문으로 로그에 남습니다. 세션으로 들어가 직접 편집합니다.

값을 다 잃어버려도 전부 재발급할 수 있습니다. 어디서 나오는 값인지는 `.env.example` 에 적혀 있습니다.

## 밟기 쉬운 것들

### Caddyfile 은 `up -d` 로 반영되지 않습니다

단일 파일 바인드 마운트라, git 이 파일을 갈아끼우면 **inode 가 바뀌어 컨테이너의 마운트가 옛 파일에 남습니다.** compose 는 스펙이 안 바뀌었다고 판단해 컨테이너를 건드리지 않고, `caddy reload` 도 소용없습니다 — 컨테이너가 보는 파일 자체가 옛것입니다.

더 나쁜 경우는 파일이 아예 사라지는 것입니다.

```
cat: can't open '/etc/caddy/Caddyfile': No such file or directory
```

그래서 `deploy.sh` 가 매 배포마다 `docker compose restart caddy` 를 돌립니다. 시작 시점에 마운트를 다시 풀어야 해결됩니다.

### LiveKit 은 일부러 자동 재시작하지 않습니다

재시작하면 **진행 중인 통화가 전부 끊깁니다.** `infra/livekit/` 이 바뀌면 `deploy.sh` 가 경고만 찍고 넘어갑니다. 통화가 없을 때 직접 돌리세요.

```bash
cd ~/ktc4-pusan-1/infra && docker compose restart livekit
```

`docker-compose.yml` 의 LiveKit **이미지 태그**가 바뀌면 이야기가 다릅니다. 그때는 `up -d` 가 자동으로 재생성하므로 통화가 끊깁니다. 이쪽도 `deploy.sh` 가 미리 경고합니다.

공인 IP 가 바뀐 뒤에도 재시작이 필요합니다. `use_external_ip` 는 **기동 때 한 번만** STUN 으로 탐지해서, 재시작 전까지 옛 IP 를 계속 광고합니다. 화면은 뜨는데 미디어만 안 붙는 증상이 납니다.

### compose 의 `:?` 는 `ps` · `logs` · `down` 까지 막습니다

`${VAR:?}` 는 값이 없으면 기동을 막아 주지만, 그 보간이 **모든 compose 명령에서 일어납니다.** 값이 빠지면 컨테이너가 안 뜨는 것까지는 의도대로인데 서버에서 로그조차 못 봅니다. 수습할 방법이 없어집니다.

그래서 `:?` 는 없으면 애초에 아무것도 못 하는 값에만 씁니다.

```
:?  POSTGRES_PASSWORD · LIVEKIT_API_KEY · LIVEKIT_API_SECRET
:-  INTERNAL_API_KEY — 대신 APP_ENV=production 일 때 BE 가 기동을 거부합니다
```

### `/internal/v1` 은 Caddy 가 프록시하지 않습니다

`Caddyfile` 이 여는 것은 `/rtc*` · `/api/*` · `/health` 뿐이고 나머지는 전부 FE 로 떨어집니다. 그래서 밖에서 `/internal/v1` 을 부르면 401 이 아니라 **FE 페이지가 돌아옵니다.**

인터넷에 노출되지 않는다는 점에서는 의도한 그대로지만, 밖에서 인증을 확인할 수 없다는 뜻이기도 합니다. 같은 compose 네트워크 안에서만 검증됩니다.

`/twirp` 도 같은 이유로 일부러 열지 않습니다. 열면 방 생성·강제퇴장 API 가 인터넷에 노출됩니다.

## 상태 확인

```bash
cd ~/ktc4-pusan-1/infra
docker compose ps
docker compose logs --tail 50 backend
curl -s https://irya.cloud/health
```
