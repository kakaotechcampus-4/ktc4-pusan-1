# LiveKit Server (self-hosting)

LiveKit Cloud 대신 **기존 AWS EC2 한 대**에 LiveKit Server 를 직접 띄운다.
이 디렉터리는 **LiveKit Server 자체의 설정과 실행 요구사항**만 담는다.
compose · Caddy · 배포 절차는 [`../README.md`](../README.md) 에 있다.

## 1. LiveKit Server 의 역할

FE·BE·AI 사이에서 미디어를 중계하는 **SFU(Selective Forwarding Unit)** 다.

| 주체 | LiveKit 과의 관계 |
| --- | --- |
| Backend | 미디어 경로에 **들어가지 않는다**. `livekit-api` 로 RoomService(HTTP)를 불러 방을 만들고(`ensure_room`), 입장 토큰(JWT)을 서명해 내려준다. [`backend/app/services/media.py`](../../backend/app/services/media.py) |
| Frontend | `livekit-client` 로 `livekitUrl` + `token` 을 들고 **LiveKit 에 직접** 붙는다. |
| AI | `livekit-agents` 로 참가자 오디오 트랙을 구독해 STT 로 흘린다. |

즉 시그널링·미디어는 전부 LiveKit 이 처리하고, BE 는 **방 관리와 토큰 발급**만 한다.

## 2. 설정 파일

[`livekit.yaml`](./livekit.yaml) 하나다. 비밀은 들어 있지 않다.

| 키 | 값 | 이유 |
| --- | --- | --- |
| `port` | `7880` | signaling(WebSocket) + RoomService(HTTP API) 공용 포트. **외부에 직접 열지 않는다** — Caddy 가 443 에서 TLS 를 끊고 여기로 넘긴다. |
| `rtc.udp_port` | `7882` | WebRTC 미디어를 UDP 한 포트로 먹싱(mux). 포트 하나만 열면 돼서 Security Group·docker 매핑이 단순해진다. |
| `rtc.tcp_port` | `7881` | UDP 가 막힌 망을 위한 ICE/TCP 폴백. **LB·TLS 뒤에 두면 안 되고** 인스턴스에 직접 노출돼야 한다. TURN/TLS 의 대체재는 아니다 (아래 참조). |
| `rtc.use_external_ip` | `true` | EC2 같은 cloud/NAT 환경에서는 NIC 에 사설 IP 만 붙고 EIP 로 NAT 된다. STUN 으로 공인 IP 를 자동 탐지해 ICE 후보로 advertise 하기 위해 켠다. 끄면 사설 IP 가 후보로 나가 외부 클라이언트가 연결하지 못할 수 있다. |
| `logging.json` | `true` | 컨테이너 로그 수집 전제. |

`rtc.udp_port` 와 `rtc.port_range_start/end` 는 **같이 쓰지 않는다** (range 가 이긴다).
기본값은 range `50000-60000` 이라, 아무것도 안 적으면 SG 에 1만 개 포트를 열어야 한다.
동시 방이 늘어 한 포트로 부족해지면 `udp_port: 7882-7885` 처럼 vCPU 수만큼 넓히고
SG 도 같은 범위로 맞춘다.

들어 있지 않은 것과 그 이유:

- **`keys`** — 실제 값을 파일에 적지 않는다. 아래 §3 참고.
- **`redis`** — 단일 노드는 필요 없다. 노드를 2대 이상으로 늘릴 때, 그리고 Egress 를 붙일 때 추가한다.
- **`turn`** — 이번 Issue 범위에서 구현하지 않는다. 아래 "연결 경로와 한계" 참조.
- **`room`** 기본값 — 정원(`max_participants: 2`)은 BE 가 `CreateRoom` 으로 방마다 지정한다.
  서버 기본값에 중복으로 박으면 두 군데가 갈라진다.
- **Egress / Recording** — 아직 없다. #112 에서 다룬다.

### 연결 경로와 한계 (TURN 미구성)

클라이언트는 ICE 로 아래 순서를 시도한다.

1. **ICE/UDP `7882`** — 일반적인 네트워크에서 쓰이는 기본 경로다.
2. **ICE/TCP `7881`** — UDP 가 실패하면 폴백한다.

**ICE/TCP 7881 은 TURN/TLS 의 완전한 대체가 아니다.** 7881 은 LiveKit 노드에
직접 붙는 비표준 포트라, 아웃바운드를 `443` 등 일부 포트로만 허용하거나
TLS 가 아닌 트래픽을 검사·차단하는 망에서는 이 폴백도 막힌다.

따라서 **UDP 와 7881/TCP 가 모두 차단되는 제한적인 네트워크에서는 연결이 실패할 수 있다.**
TURN/TLS(443)는 이런 망에서 시그널링과 구분되지 않는 트래픽으로 미디어를 중계해 주지만,
내장 TURN 은 TLS 종료를 위해 `443` 이 필요하고 그 포트는 Caddy 가 쓰고 있다.

- 이번 Issue 범위에서는 **TURN 을 구현하지 않는다.**
- 실제로 해당 환경에서 연결 실패가 보고되면 그때 **TURN/TLS 도입을 검토한다**
  (Caddy 를 L4 로 돌리거나 별도 TURN 도메인·인증서를 붙이는 방식).

## 3. 환경변수 (컨테이너 런타임 주입)

| 변수 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- |
| `LIVEKIT_KEYS` | ✅ | `"<api-key>: <api-secret>"` | **콜론 뒤 공백 필수.** 없으면 파싱 실패. 여러 쌍이면 개행으로 구분한다. |
| `LIVEKIT_CONFIG` | — | YAML 본문 | `--config` 파일 대신 YAML 을 통째로 넘기는 방식. 우리는 파일 마운트를 쓰므로 안 쓴다. |
| `NODE_IP` | — | IP | `use_external_ip` 의 STUN 탐지가 실패할 때만. EC2 에서는 보통 불필요. |
| `UDP_PORT` | — | `7882` | yaml 값을 덮어쓸 때만. yaml 에 이미 있으므로 안 쓴다. |

livekit-server 는 **모든 설정 필드에 대해 환경변수 오버라이드를 자동 생성**한다.
규칙은 `LIVEKIT_` + yaml 경로를 대문자·`_` 로 바꾼 것이다.

| yaml | 환경변수 | CLI 플래그 |
| --- | --- | --- |
| `rtc.use_external_ip` | `LIVEKIT_RTC_USE_EXTERNAL_IP` | `--rtc.use_external_ip` |
| `rtc.udp_port` | `LIVEKIT_RTC_UDP_PORT` | `--rtc.udp_port` |
| `port` | `LIVEKIT_PORT` | `--port` |

전체 목록은 `livekit-server help-verbose` 로 확인한다.
환경이 달라서 값 하나만 바꿔야 할 때 yaml 을 포크하지 않아도 된다.

키 쌍 생성 (**로컬에서 생성해 SSM Parameter Store / GitHub Secrets 에 넣고, repo 에는 절대 커밋하지 않는다**):

```bash
docker run --rm livekit/livekit-server generate-keys
```

## 4. 필요한 포트

### AWS Security Group (인바운드)

| 포트 | 프로토콜 | 소스 | 용도 |
| --- | --- | --- | --- |
| 443 | TCP | 0.0.0.0/0 | Caddy — HTTPS + **WSS signaling** (FE·BE·AI 공통 진입점) |
| 80 | TCP | 0.0.0.0/0 | Caddy — ACME(Let's Encrypt) 인증서 발급 및 443 리다이렉트 |
| 7881 | TCP | 0.0.0.0/0 | **ICE/TCP 폴백.** UDP 실패 시 사용. Caddy 를 거치지 않는다 |
| 7882 | **UDP** | 0.0.0.0/0 | **WebRTC 미디어(주 경로).** Caddy 를 거치지 않는다 |

### 열지 않는 포트

| 포트 | 이유 |
| --- | --- |
| 7880 | signaling/API 원본. Caddy(같은 호스트)만 접근한다. 외부에 열면 **평문 ws:// 로 토큰이 오간다**. |
| 3478 / 5349 | 내장 TURN 을 이번 범위에서 구성하지 않는다 (§2). |
| 50000-60000 UDP | `udp_port` 먹싱을 쓰므로 불필요. |

> UDP 아웃바운드도 필요하다. SG 아웃바운드가 기본 all-allow 가 아니라면 UDP 를 막지 않았는지 확인한다.
> `use_external_ip` 의 STUN 탐지도 아웃바운드 UDP 3478 을 쓴다.

## 5. Caddy(시그널링) vs WebRTC(미디어) — 트래픽이 갈리는 지점

**둘은 서로 다른 경로로 흐른다.** 이걸 헷갈리면 "방에는 들어가지는데 화면이 안 보이는" 증상이 난다.

```
[브라우저]
   │
   ├─ ① HTTPS/WSS  :443 ──► [Caddy] ──► [LiveKit :7880]     시그널링 + RoomService API
   │       TLS 종료: Caddy                                   (SDP/ICE 교환, 방 입장, 참가자 이벤트)
   │
   └─ ② SRTP/DTLS  :7882/UDP ─────────► [LiveKit]           실제 오디오·비디오
           (막히면 :7881/TCP 폴백)                            Caddy 를 **거치지 않음**
```

| | ① signaling | ② media |
| --- | --- | --- |
| 프로토콜 | WebSocket over TLS (WSS) / HTTPS | SRTP · DTLS (UDP, 폴백 시 TCP) |
| 경로 | Caddy 리버스 프록시 경유 | 인스턴스 IP 로 직접 |
| 암호화 | Caddy 가 TLS 종료 | **이미 DTLS-SRTP 로 암호화됨** — 추가 TLS 불필요, 그래서 프록시에 넣을 이유가 없다 |
| 트래픽량 | 적음(제어 메시지) | 큼(연속 스트림) |
| 프록시 가능 여부 | ✅ | ❌ Caddy 는 L7 HTTP 프록시라 UDP 미디어를 다루지 않는다 |

Caddy 에 필요한 건 **①뿐**이다. WebSocket 업그레이드는 Caddy 의 `reverse_proxy` 가 기본 처리하므로 별도 지시어가 없다.

## 6. 실제 배포 구성

**이미지**

```
livekit/livekit-server:v1.13.6
```

(2026-08-26 릴리스. `backend/.env.example` 의 로컬 실행 예시와 같은 버전이다. `latest` 는 쓰지 않는다.)

**컨테이너 실행 요구사항**

| 항목 | 값 |
| --- | --- |
| command | `--config /etc/livekit.yaml` |
| 마운트 | `infra/livekit/livekit.yaml` → `/etc/livekit.yaml` (읽기 전용) |
| 환경변수 | `LIVEKIT_KEYS="<key>: <secret>"` — **compose 파일에 값을 적지 말고** `.env` / SSM 등 외부에서 주입 |
| restart | `unless-stopped` |

**필요한 네트워크 조건** (구현 방식은 Docker/Caddy 담당자가 결정)

| 포트 | 필요한 접근 |
| --- | --- |
| `7881/TCP` | 외부(클라이언트)에서 인스턴스로 직접 도달 |
| `7882/UDP` | 외부(클라이언트)에서 인스턴스로 직접 도달 |
| `7880/TCP` | Caddy 에서만 도달. 외부 노출 불필요 |

**port publishing 으로 갔다.** LiveKit 공식 production 문서는 host networking(`network_mode: host`)을
권장하지만, 우리는 `infra/docker-compose.yml` 에서 포트를 따로 연다.

```yaml
ports:
  - "7881:7881"      # ICE/TCP 폴백
  - "7882:7882/udp"  # 미디어
```

- **호스트와 컨테이너의 포트 번호를 같게** 맞춘다. LiveKit 이 광고하는 ICE 후보 포트는
  컨테이너 내부 포트라서, 번호가 다르면 클라이언트가 엉뚱한 곳으로 붙는다.
- `7880` 은 퍼블리싱하지 않는다. Caddy 가 같은 compose 네트워크에서 `livekit:7880` 으로
  부르므로 호스트에 열 이유가 없다. host networking 이었다면 호스트에 열려서 SG 로 막아야 했다.

**Caddy**

서브도메인을 따로 두지 않는다. **기존 도메인의 경로 하나(`/rtc*`)로 간다.**

```caddy
handle /rtc* {
	reverse_proxy livekit:7880
}
```

- SDK 가 쓰는 경로는 `/rtc/v1` 과 `/rtc/v1/validate` 라 `/rtc` 만 매칭하면 놓친다. `/rtc*` 여야 한다.
- WebSocket 업그레이드는 `reverse_proxy` 의 기본 동작이라 따로 적을 것이 없다.
- **`/twirp` 는 일부러 열지 않는다.** RoomService 관리 API 라 프록시하면 방 생성·강제퇴장이
  인터넷에 노출된다. BE 는 같은 compose 네트워크에서 `LIVEKIT_INTERNAL_URL` 로 직접 부르므로
  밖으로 낼 이유가 없다.
- 7881/7882 는 Caddy 설정에 넣지 않는다 (§5 참조)

**DNS**

- `irya.cloud` A 레코드 → EC2 Elastic IP. LiveKit 전용 레코드는 없다

**BE 컨테이너에 넣을 값** (§7)

## 7. Backend 가 최종적으로 필요로 하는 값

`backend/app/core/config.py` 의 `Settings` 가 읽는 네 개다.

```dotenv
LIVEKIT_URL=wss://irya.cloud
LIVEKIT_API_KEY=<LIVEKIT_KEYS 의 키>
LIVEKIT_API_SECRET=<LIVEKIT_KEYS 의 시크릿>
LIVEKIT_INTERNAL_URL=http://livekit:7880
```

- **`wss://` 스킴 그대로** 넣는다. BE 는 이 값을 두 군데에 쓴다.
  - FE 응답(`JoinResponse.livekitUrl`) — 브라우저가 붙을 주소라 `wss://` 여야 한다.
  - RoomService 호출 — `media.py` 가 `wss://` → `https://` 로 바꿔서 부른다.
- 포트를 붙이지 않는다. `wss://irya.cloud:7880` 이 아니라 **443(기본)** 이다.
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` 은 LiveKit 컨테이너의 `LIVEKIT_KEYS` 와 **같은 쌍**이어야 한다. 다르면 토큰 서명 검증이 깨져 입장이 401 난다.
- **`LIVEKIT_INTERNAL_URL` 은 BE 가 RoomService 를 부를 때만 쓴다.** 비우면 `LIVEKIT_URL` 로
  떨어지는데, 그러면 관리 API 호출이 Caddy 를 한 바퀴 돌고 `/twirp` 가 막혀 있어 실패한다.
  compose 가 `http://livekit:7880` 을 기본값으로 넣어 준다.
- AI 파트도 앞의 세 값을 쓴다 (`ai/.env.example`).

## 8. 로컬 실행 / 검증

Docker 없이 공식 바이너리로 확인할 수 있다.

**설치** (둘 중 하나)

```bash
brew install livekit
```

```bash
curl -sSL https://get.livekit.io | bash
```

**실행**

```bash
LIVEKIT_KEYS="devkey: devsecret_local_only_0123456789abcdef" \
LIVEKIT_RTC_USE_EXTERNAL_IP=false \
  livekit-server --config infra/livekit/livekit.yaml
```

로컬에서는 `use_external_ip` 를 **꺼야 한다**. 켜져 있으면 STUN 으로 찾은 공인 IP 가
ICE 후보로 나가는데, 로컬에서는 그 IP 로 자기 자신에게 돌아올 수 없다.
`--node-ip` 만으로는 안 된다 — `use_external_ip` 가 우선이라 STUN 결과가 `node_ip` 를 덮어쓴다.
(`backend/.env.example` 의 docker 예시는 설정 파일 없이 돌아 `use_external_ip` 기본값이
`false` 라서 `--node-ip 127.0.0.1` 만으로 충분하다. 이 파일을 쓸 때만 다르다.)

**검증**

```bash
livekit-server --config infra/livekit/livekit.yaml ports
```

```bash
curl -sf http://localhost:7880 && echo " <- signaling/API 살아있음"
```

실제 통화까지 확인하려면 토큰을 만들어 [LiveKit Meet](https://meet.livekit.io/?tab=custom) 에
`ws://localhost:7880` 과 함께 넣는다.

```bash
LIVEKIT_KEYS="devkey: devsecret_local_only_0123456789abcdef" \
  livekit-server create-join-token --room test --identity alice
```

**BE 와 함께 확인**

`backend/.env.example` 의 로컬 기본값(`ws://localhost:7880`, `devkey`)이 위 실행값과 이미 맞다.
`cp backend/.env.example backend/.env` 후 BE 를 띄우면 `POST /api/v1/sessions/{id}/join` 이 토큰을 내준다.

## 9. EC2 배포 시 확인사항

- [ ] Security Group 인바운드에 **7882/UDP** 가 있는가 — 가장 흔한 누락이고, 증상은 "붙긴 붙는데 영상이 안 뜸"이다.
- [ ] **7881/TCP** 가 열려 있는가 — 없으면 UDP 막힌 망의 사용자만 골라서 실패한다.
- [ ] **7880 이 퍼블리싱되지 않았는가** — compose 의 `ports` 에 7880 이 없어야 한다. 열려 있으면 평문 ws 로 토큰이 오간다.
- [ ] `irya.cloud` DNS 가 EIP 를 가리키는가 — Caddy 인증서 발급 선행 조건.
- [ ] 서버 로그 기동 라인의 `nodeIP` 가 **EIP(공인)** 인가, 사설 IP(`172.x` / `10.x`)가 아닌가.
      사설이면 `use_external_ip` 가 STUN 탐지에 실패한 것이니 `NODE_IP=<EIP>` 를 주입한다.
- [ ] BE 의 `LIVEKIT_API_KEY/SECRET` 이 LiveKit 의 `LIVEKIT_KEYS` 와 동일한 쌍인가.
- [ ] BE 의 `LIVEKIT_URL` 이 `wss://` 이고 포트가 붙어 있지 않은가.
- [ ] FE `CORS_ORIGINS` 에 실제 서비스 도메인이 들어갔는가 (BE 설정).
- [ ] 포트 매핑이 `7881:7881`, `7882:7882/udp` 로 **같은 번호**인가.
      번호가 다르면 LiveKit 이 광고하는 ICE 후보 포트와 실제 포트가 어긋나 연결이 실패한다.
- [ ] Caddy 가 `/rtc*` 를 프록시하는가, 그리고 `/twirp` 는 열려 있지 않은가.
- [ ] EC2 인스턴스 타입 — 미디어 중계는 CPU/네트워크를 먹는다. FE·BE·AI(STT)와 한 대를 공유하므로
      동시 면접 수가 늘면 여기부터 병목이 온다. t3.micro 급이면 2~3 세션에서 한계다.

## 참고

- [LiveKit self-hosting](https://docs.livekit.io/home/self-hosting/deployment/)
- [Ports and firewall](https://docs.livekit.io/home/self-hosting/ports-firewall/)
- [config-sample.yaml](https://github.com/livekit/livekit/blob/master/config-sample.yaml)
