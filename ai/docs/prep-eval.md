# 사전 가공 실호출 검증 (이슈 #155)

JD·인재상·이력서 본문을 프로젝트 LLM에 넘겨 면접에서 확인할 역량(`Competency`)과
이력서 주장(`ResumeClaim`)이 실제로 쓸 만하게 나오는지 확인한 기록이다.

자동 테스트(`tests/test_prep.py`, `tests/test_openai_prep.py`)는 HTTP mock으로 돌아
키가 없어도 통과한다. 이 문서는 **실제 모델 호출** 결과만 다룬다.

## 대상 모델

| 모델 | 단가 (per 1M tokens) |
| --- | --- |
| `gpt-5.6-luna` | 입력 ₩304 / 출력 ₩1,827. 캐시된 입력은 1/10 |

Elice ML API의 OpenAI 호환 게이트웨이를 쓴다. 지원 목록 밖 파라미터는 400이라
`openai_prep.py`는 `model`, `messages`, `response_format`, `max_completion_tokens`,
(설정 시) `reasoning_effort`만 보낸다.

## 실행 방법

```bash
# ai/.env  (값은 절대 커밋하지 않는다)
LLM_BASE_URL=https://<mlapi-endpoint>/v1
LLM_API_KEY=<Serverless API Key>
LLM_MODEL=gpt-5.6-luna

uv run irya-ai prep data/samples/context_backend_junior.json
uv run irya-ai prep data/samples/context_backend_junior.json --backend extractive  # 기준선
```

종료 코드: `completed` 0, `partial`·`failed` 1, 입력·설정 오류 2.

## 입력 샘플

`data/samples/context_backend_junior.json`. 합성 이력서 본문(프로젝트 4줄, 기술 3줄,
학력 1줄, 글머리 기호 `- `로 시작)과 JD 본문 6문장, 인재상 한 단락이다. 실제 인물의
정보는 없다.

## 결과 — 2026-10-07 `gpt-5.6-luna`, `prep-v1`, reasoning_effort 미지정

| 항목 | 실행 1 | 실행 2 | 실행 3 |
| --- | --- | --- | --- |
| status | completed | completed | completed |
| 역량 / 주장 | 6 / 6 | 6 / 7 | 5 / 6 |
| 탈락 | 0 | 0 | 0 |
| tokens (prompt / completion / cached) | 1,407 / 446 / 0 | 1,126 / 502 / 1,123 | 1,467 / 533 / 0 |
| 추정 비용 | 약 ₩1.2 | 약 ₩1.0 | 약 ₩1.4 |
| 소요 | 6.1s | 6.7s | 6.7s |

실행 3은 글머리 기호 처리(아래)와 프롬프트 한 줄을 고친 뒤의 결과다.

### 역량

실행 1의 역량 6개. `required`는 JD의 "필요합니다"와 "있으면 좋습니다"를 그대로 따랐다.

| name | required | description |
| --- | --- | --- |
| 서버 API 개발 | true | Python 또는 Java 기반으로 상품 조회·주문 API를 설계하고 구현한 경험 |
| 관계형 DB·캐시 활용 | true | 관계형 DB와 캐시를 활용해 조회 성능과 데이터 처리 효율을 개선한 경험 |
| 장애 대응 | false | 장애 상황에서 원인을 분석하고 개선 조치를 적용한 경험 |
| API 계약 조율 | false | 다른 직군과 API 요구사항과 계약을 조율하고 협업한 경험 |
| 온콜 대응 | true | 온콜 상황에서 장애를 신속히 공유하고 서비스 운영에 대응한 경험 |
| 전체 서비스 운영 | true | 작은 팀에서 개발부터 배포·운영까지 서비스 전체를 맡아본 경험 |

- 이름 전부 20자 이내 명사구, 설명 전부 120자 이내다. 평가·점수 표현은 없다.
- 마지막 역량은 JD가 아니라 인재상("작은 팀이 서비스 전체를 맡는다")에서 왔다.
  인재상을 보내는 것이 역량 목록에 실제로 반영된다.
- **이름이 실행마다 흔들린다.** 세 실행에서 ID가 같은 역량은 "서버 API 개발"과
  "장애 대응" 둘뿐이다. 나머지는 "관계형 DB·캐시 활용 / 관계형 DB·캐시 / DB·캐시
  성능 개선"처럼 같은 뜻을 다른 이름으로 써서 ID가 달라졌다. 내용 해시 ID의 알려진
  한계이고(#155), 재가공은 이력서를 다시 올릴 때만 일어나므로(#162) 면접 하나 안에서는
  문제가 되지 않는다. 이름을 고정 목록에서 고르게 하는 것은 `prep-v2` 후보다.

### 이력서 주장

실행 3의 주장 6개. 전부 이력서 본문의 연속된 부분 문자열로 검증을 통과했다.

| section | quote |
| --- | --- |
| 프로젝트 | 상품 조회 API에 Redis 캐시를 도입하여 응답 시간을 60% 단축 |
| 프로젝트 | 4인 팀 프로젝트에서 백엔드 파트 리드로 API 설계와 일정 관리를 담당 |
| 프로젝트 | 부하 테스트로 초당 3,000건 요청 처리 확인 |
| 프로젝트 | 주문 API의 재고 차감을 트랜잭션으로 묶어 중복 주문을 제거 |
| 기술 | Kubernetes 기반 배포 파이프라인 구축 |
| 기술 | GitHub Actions로 테스트와 배포를 자동화 |

- 학력 줄은 세 실행 모두 고르지 않았다. 프롬프트의 "확인할 것이 없는 항목은 빼라"가 지켜졌다.
- `section`은 세 실행 모두 이력서의 소제목("프로젝트", "기술")을 그대로 썼다.
- 수치("60%", "3,000건")와 영문 표기("Redis", "GitHub Actions")는 원문 그대로다.

### 실행 중 고친 것

- **글머리 기호.** 실행 2는 `- 상품 조회 API에 …`처럼 줄 앞의 `- `까지 인용했다.
  검증은 통과하지만(원문에 그대로 있으므로) 실행 1과 ID가 전부 달라졌다. 글머리 기호는
  문장이 아니라 레이아웃이라, 인용 앞의 `- * • · ∙` 등은 떼고 검증·저장·ID 계산을
  하도록 했다. 프롬프트에도 "글머리 기호는 빼고 문장만"을 더했다. 실행 3의 주장 ID는
  실행 1과 6개 전부 같다.
- **기술 나열 줄.** 실행 2는 `Python, FastAPI, PostgreSQL, Redis`를 주장으로 골랐다.
  확인할 사실이 없는 줄이라 프롬프트에 "기술 이름만 나열한 줄은 고르지 말라"를 더했고,
  실행 3에서는 나오지 않았다. 1회 관찰이라 더 봐야 한다.

### 게이트웨이 사용 시 걸린 것

- **비스트리밍 응답의 `max_completion_tokens` 상한이 2,000이다.** 3,000을 보내면 400과
  함께 "exceeds the 2000-token ceiling this proxy holds a NON-STREAMING reply to"라는
  메시지가 온다(2026-10-07 실측). 기본값을 2,000으로 두었다. `openai_timeline.py`는
  4,000을 보내므로 같은 게이트웨이에서 지금은 400이 난다(별도 수정).

## 검증하지 않은 것

- BE가 Helpy Document Vision으로 뽑은 실제 PDF 본문(#143). HTML 표가 섞인 본문에서
  인용 검증이 어떻게 되는지는 BE 내부 API가 열린 뒤 본다.
- 12,000자 상한에 걸리는 긴 이력서. 샘플은 300자 남짓이다.
- 역량 이름의 안정성을 높이는 프롬프트(`prep-v2`).
