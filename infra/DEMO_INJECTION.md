# 최종 발표 데모 — 켜고 끄는 순서

무대에는 지원자가 없다. 그래서 **「지원자가 소리를 냈다」는 사실 하나만** 대본으로
대신하고, 그 뒤는 전부 실제 서버가 돈다 — 발표자의 질문은 진짜 STT 를 타고 자막에
오르고, 꼬리질문은 진짜 LLM 이 그 답변에서 만들고, 인용이 답변의 글자 그대로가
아니면 면접에서와 똑같이 버려진다.

구현은 `ai/src/irya_ai/demo_injection.py` 와 `POST /sessions/{id}/demo/utterance`.

## ⚠️ 순서가 중요하다

세팅을 바꾼 뒤 **컨테이너를 다시 띄우고, 그 다음에 방에 들어가야 한다.**

- BE 는 설정을 모듈이 뜰 때 한 번 읽는다 (`app/core/config.py` 의 `settings`).
- Agent 는 `get_settings()` 가 `@lru_cache` 라 프로세스당 한 번 읽고, 데모 핸들러를
  **방 작업이 시작될 때 한 번** 붙인다 (`worker.py`).

그래서 이미 돌고 있는 방은 나중에 목록에 올려도 **그 방이 끝날 때까지 핸들러가
없다.** 이때의 증상이 제일 나쁘다 — BE 는 204 를 주고, 브라우저 콘솔에도 성공으로
찍히고, **아무 일도 안 일어나는데 어디에도 오류가 없다.** 유일한 신호는 Agent 가
방에 붙을 때 남기는 한 줄이다.

## 켜기

**① 데모용 면접·세션을 한 번 만들어 두고 id 를 고정한다.** 세션마다 id 가 바뀌면
아래를 매번 다시 해야 한다. 만들고 **시작은 하지 않은 채** 둔다 (`WAITING`).

**② 서버 `infra/.env`**

```
DEMO_INJECTION_ENABLED=true
DEMO_INJECTION_SESSIONS=ses_<①에서 만든 세션 id>
```

목록이 비면 **아무 세션도 허용되지 않는다.** 플래그만 켜서 그 서버의 모든 면접이
열리는 일이 없게 실패를 닫는 쪽으로 뒀다. 와일드카드는 없다 — `*` 나 `all` 은 그런
이름의 세션 id 로 읽히고 아무것과도 안 맞는다.

⑤의 JSON 배열 모양(`["ses_abc"]`)을 여기 붙여넣어도 된다. 대괄호·따옴표는 떼고
읽는다 — BE·Agent·브라우저 세 쪽이 같은 규칙이다. 다만 구분자는 **쉼표**다.
`;` 로 적으면 쓸모없는 id 한 개가 되어 404 만 나오고 이유가 안 보인다.

**③ 두 컨테이너를 다시 띄운다**

```
docker compose up -d backend ai
```

**④ 로그에서 확인한다.** 방에 들어가면 Agent 가 이 줄을 남긴다.

```
docker compose logs -f ai | grep -i demo
```

- `demo utterance injection is ENABLED for session=ses_… topic=irya.demo.v1` → 붙었다
- `demo injection is on but session=… is not listed; no handler` → ②를 틀렸다
- `DEMO_INJECTION_ENABLED is on but DEMO_INJECTION_SESSIONS is empty` → ②를 빼먹었다

**⑤ 브라우저에 세션과 대본을 넣는다.** 면접 화면을 열고 콘솔에서:

```js
localStorage.setItem('irya.demo.sessions', JSON.stringify(['ses_<세션 id>']));
localStorage.setItem('irya.demo.script', JSON.stringify([
  '답변 한 줄입니다. 8어절을 넘겨야 꼬리질문이 생깁니다.',
  '두 줄입니다.',
]));
```

적지 않으면 어느 화면에서도 키를 잡지 않는다 — 평소 면접이 화살표를 잃지 않게 하기
위한 것이다. 새로고침하면 적용된다. 대본을 넣지 않으면 코드에 있는 기본 3줄을 쓴다.

**⑥ 번들에 데모가 들어 있어야 한다.** 레포 Variable `DEMO_SCRIPT=on`.
**제출 전에 켜 둬야 한다** — CD 는 같은 SHA 가 이미 올라가 있으면 FE 를 다시 빌드하지
않으므로, Variable 만 나중에 바꿔도 번들은 그대로다. 번들에 켜져 있어도 ②·⑤가 없으면
아무 일도 일어나지 않으니, **번들은 켜고 서버·브라우저에서 여닫는 것**이 제출 뒤에
남는 유일한 자유도다.

## 대본이 지켜야 하는 조건

지키지 않으면 **조용히** 아무 일도 안 일어난다.

| | |
|---|---|
| 발표자가 할 질문 | 의문 어미(`나요 · 까요 · 어떤 · 어떻게 · 왜 · 얼마나 · ?`)가 있고, 공백·기호를 뗀 길이가 **10자 초과**. 짧으면 맞장구로 분류돼 버려진다 |
| 대본의 답변 | **8어절 이상** (`MIN_ANSWER_WORDS`). 짧으면 자막만 뜨고 꼬리질문 라운드가 안 돈다 |
| 답변 내용 | 인용할 수 있는 **구체적인 숫자나 고유명사**. 꼬리질문은 답변에서 글자 그대로 인용할 수 있는 것만 근거로 쓰고, 근거가 없으면 버려진다. 「열심히 했습니다」에서는 아무것도 안 나온다 |

그리고 **말하고 나서 누른다.** 발화 순서가 질문 → 답변이어야 짝이 맞는다.

## 리허설에서 반드시 재야 하는 것

**꼬리질문이 몇 초 만에 뜨는가.** 측정된 값이 코드에 없다. 상한은 10초
(`SUGGESTION_ROUND_TIMEOUT_SECONDS`), 테크스펙 목표는 3초다.

```
docker compose logs ai | grep "suggestion round"
# suggestion round session=… status=… kept=1 rejected=0 1234ms
```

끝의 숫자가 이 데모의 성립 여부를 정한다. 8초를 넘으면 무대에서 기다릴 수 없으므로
설계를 바꿔야 한다.

## 끄기

발표가 끝나면 **되돌린다.**

```
# infra/.env
DEMO_INJECTION_ENABLED=false
DEMO_INJECTION_SESSIONS=
```

```
docker compose up -d backend ai
```

## 알고 있어야 하는 것

- **데모 세션의 기록은 실제 기록과 구분되지 않는다.** 주입된 발화의 `track_id` 는
  `trk_demo_candidate` 고 발화 id 에도 `demo` 가 들어가지만, 그 id 는 자막과 꼬리질문
  근거로만 FE 에 닿는다. 그 세션의 **검토 화면과 리포트는 사람이 말한 것처럼
  읽힌다.** 허용 목록 덕분에 데모 세션 자기 기록에만 국한되지만, 그 세션을 실제 면접
  기록으로 쓰지는 않는다.
- **브라우저는 문이 아니다.** ⑤는 평소 면접이 화살표를 가로채지 않게 하는 것이고,
  실제로 막는 것은 서버의 ②와, 사람 토큰에 `canPublishData` 가 없다는 사실이다
  (`backend/app/services/media.py`).
