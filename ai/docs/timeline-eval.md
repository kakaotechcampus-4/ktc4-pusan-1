# 리뷰 타임라인 실호출 검증 (이슈 #48)

STT 청크(`Utterance` JSON)를 면접 종료 후 한꺼번에 프로젝트 LLM에 넘겨, 면접 기록 화면(S3)의
타임라인 마커와 질문별 답변 한 줄 요약이 실제로 쓸 만하게 나오는지 확인한 기록이다.

자동 테스트(`tests/test_timeline.py`, `tests/test_openai_timeline.py`)는 HTTP mock으로 돌아
키가 없어도 통과한다. 이 문서는 **실제 모델 호출** 결과만 다룬다.

## 대상 모델

| 순서 | 모델 | 이유 |
| --- | --- | --- |
| 1차 | `gpt-5.6-luna` | 대량 요약·추출용 경량 모델. 입력 ₩304 / 출력 ₩1,827 per 1M tokens |
| 예비 | `gpt-5.6-terra` | Luna 결과가 부족할 때. 입력 ₩3,045 / 출력 ₩18,270 per 1M tokens (10배) |

두 모델 모두 Elice ML API의 OpenAI 호환 게이트웨이를 쓴다. **지원 목록에 없는 파라미터는 400으로
거절**되므로 `openai_timeline.py`는 `model`, `messages`, `response_format`,
`max_completion_tokens`, (설정 시) `reasoning_effort`만 보낸다. `store` 등은 보내지 않는다.

## 실행 방법

```bash
# ai/.env  (값은 절대 커밋하지 않는다)
LLM_BASE_URL=https://<mlapi-endpoint>/v1
LLM_API_KEY=<Serverless API Key>
LLM_MODEL=gpt-5.6-luna
LLM_REASONING_EFFORT=        # 비우면 보내지 않음. none / low / medium / high
LLM_TIMEOUT_SECONDS=60

# 실호출
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json > /tmp/timeline_01.json
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json --frontend   # FE Moment 형태

# 모델 바꿔서 비교
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json --model gpt-5.6-terra

# 비교 기준선 (모델 없음, 답변 첫 문장 인용)
uv run irya-ai timeline data/samples/chunks_backend_junior_01.json --backend extractive
```

종료 코드: `completed` 0, `partial`·`failed` 1, 입력·설정 오류 2.

## 입력 샘플

| 파일 | 내용 | 청크 수 | Q&A | 선별 |
| --- | --- | --- | --- | --- |
| `data/samples/chunks_backend_junior_01.json` | 대본 01을 문장 단위로 나눈 FINAL 청크. 지원자 문장 하나는 5초 컷을 흉내 내 중간에서 두 청크로 쪼갬 | 36 | 7 | 7 |

#36 STT 파이프라인이 실제로 내는 형식(청크마다 FINAL, 단어 시각 없음)에 맞췄다. #36 머지 후
실제 STT 출력으로 한 번 교체해 확인한다.

## 기록 항목

실호출마다 아래를 적는다. 응답 원문 전체와 키는 남기지 않는다.

- 모델 ID(응답의 `model`), 프롬프트 버전(`openai_timeline.PROMPT_VERSION`), `reasoning_effort`
- `usage`: prompt / completion / cached prompt tokens
- 상태, 생성된 Moment 수 / 선별 수, `rejectedMomentCount`와 `rejections` 사유
- 사람이 본 소견: 라벨이 마커 아래 붙일 만한 주제명인가, answer가 지원자 말만 담고 평가·추측이 없는가,
  숫자·고유명사가 원문 표기 그대로인가

## 결과

### 실행 1 — 2026-09-13 `gpt-5.6-luna`, `timeline-v1`, reasoning_effort 미지정

| 항목 | 값 |
| --- | --- |
| 응답 model | `gpt-5.6-luna` |
| usage (prompt / completion / cached) | 2160 / 1274 / 0 |
| 추정 비용 | 약 ₩3.0 |
| status | `completed` |
| moments / selected | 7 / 7 |
| rejectedMomentCount | 0 |
| rejections | 없음 |
| 소요 ms | 11039 |

라벨·answer 표:

| qaId | label | answer | 소견 |
| --- | --- | --- | --- |
| qa_utt_000 | 자기소개 | 컴퓨터공학을 전공했고 팀 프로젝트로 소규모 커머스 서비스의 백엔드를 개발했습니다. 주로 Python과 FastAPI를 사용했고 조회 성능 개선에 관심이 많다고 답했습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_005 | 캐시 적용 | 조회가 많은 상품 상세 API 앞에 Redis를 적용했고, 조회 용도로만 사용했습니다. 재고처럼 실시간성이 중요한 값은 캐시하지 않고 DB에서 바로 읽도록 분리했습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_009 | 성능 측정 | 응답 시간이 체감상 빨라졌다고 했지만 정확한 수치는 기억하지 못했습니다. 로컬에서 몇 번 호출해 확인했고, 캐시 적중률은 따로 측정하지 않았습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_014 | 역할 분담 | 백엔드는 다른 팀원 한 명과 함께 했고, API 설계 초안을 먼저 작성했습니다. 엔드포인트 목록을 정리해 프론트 팀원과 합의했으며 일정 관리는 PM 역할의 팀원이 주로 맡았습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_020 | 의견 조율 | 목록 API에 상세 정보까지 담자는 의견에 응답이 너무 커진다고 반대했습니다. 목록은 가볍게 두고 상세는 따로 호출하되 필요한 필드를 쿼리 파라미터로 선택하는 방식으로 절충했습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_026 | 부하 테스트 | k6를 사용해 로컬 노트북에서 서버와 DB를 함께 띄운 상태로 상품 상세 조회 한 종류를 30초 동안 반복했습니다. 캐시가 모두 적중하는 조건이어서 실제 환경 수치로 보기는 어렵다고 말했습니다. | 원문 표기 유지, 평가 없음 |
| qa_utt_030 | 장애 대응 | 새벽에 장애 알림을 받는 상황이 괜찮다고 답했습니다. 발표 전날 밤 서버가 죽었을 때 새벽에 로그를 보며 원인을 찾고 수정한 경험을 말했습니다. | 원문 표기 유지, 평가 없음 |

소견:

- 라벨 7개 모두 2~5자 명사구로 마커 아래 붙일 만하다. 12자 상한에 걸린 것 없음.
- answer는 지원자 발화만 담았고 평가·추측이 없다. "정확한 수치는 기억하지 못했습니다", "캐시 적중률은 따로 측정하지 않았습니다"처럼 말하지 않은 것을 부재로 표현하는 지시를 따랐다.
- 인용 21개(질문당 3개)가 전부 원문 부분 문자열로 검증됐다. 5초 컷을 흉내 내 중간에서 쪼갠 문장(`utt_023`/`utt_024`)도 두 청크를 각각 인용해 넘어갔다.
- 숫자·고유명사(k6, Redis, FastAPI, 30초)는 원문 표기 그대로다. 질문의 "3,000건"은 답변에 없어 answer에도 넣지 않았다.
- 첫 질문의 answer에서 지원자 이름("정민호입니다")은 뺐다. 개인정보 관점에서는 오히려 낫다.

### 실행 2 — 같은 입력, 안정성 확인

| 항목 | 값 |
| --- | --- |
| usage (prompt / completion / cached) | 1728 / 1476 / 1725 |
| 추정 비용 | 약 ₩2.7 |
| status / moments / rejected | `completed` / 7 / 0 |
| 소요 ms | 14774 |

- 두 번째 호출부터 시스템 프롬프트가 캐시에 잡혀 prompt 토큰의 99%가 cached로 과금됐다. 같은 세션 안에서 모델을 바꿔 재시도해도 입력 비용은 거의 없다.
- 라벨은 7개 중 6개가 같았다(`캐시 적용` → `캐시 설계`). 인용 발화 ID는 7개 중 5개가 같았고, 두 개는 인용 개수만 달랐다(2개 vs 3개). 인용 검증 탈락은 두 실행 모두 0.
- **문체가 실행마다 흔들린다.** 실행 1은 "~했습니다", 실행 2는 "~했다"로 끝났다. 화면에 섞여 보이면 어색하므로 프롬프트에 종결 어미를 고정하는 편이 좋다(후속, `timeline-v2`).
- 실행 2의 `qa_utt_020` answer는 "이후 프론트 요청 횟수가 늘어 결정이 맞는지는 확신하지 못한다"까지 담아 한두 문장 지시를 넘어 세 문장이 됐다. 길이 상한을 문장 수가 아니라 글자 수로 주는 것을 검토한다.

### 결론

- **Luna로 충분하다.** 두 실행 모두 7/7 완료, 인용 탈락 0, 호출당 11~15초, 비용 ₩3 안팎. Terra는 비교 실행하지 않았다(필요 시 `--model gpt-5.6-terra`로 같은 입력을 돌려 이 문서에 추가).
- 프롬프트 수정 후보(`timeline-v2`): 종결 어미 고정("~했다"), answer 글자 수 상한(예: 120자), 라벨 중복 방지.
- 인용 탈락은 없었지만 입력이 합성 청크 1건뿐이다. #36 실제 STT 출력과 기획 모의 면접 녹음으로 다시 돌려야 대소문자·띄어쓰기 흔들림에 의한 탈락률을 알 수 있다.

### 게이트웨이 사용 시 걸린 것

- `LLM_BASE_URL`에 `/v1`을 빼고 넣으면 모든 경로가 404다. 문서대로 `https://<endpoint>/v1`이어야 하며, `config.py`가 `/v1`이 없으면 붙이도록 했다.
- `LLM_REASONING_EFFORT=`를 비워 두면 빈 문자열이 들어와 Literal 검증에 걸렸다. 빈 값은 None(미전송)으로 읽도록 했다.
- 404 응답 본문에 `error` 객체가 없어 SDK가 원인 메시지를 주지 않는다. 주소 문제는 상태 코드로만 알 수 있다.

## 검증하지 않은 것

- 실제 면접 음성 → STT 청크 → 타임라인의 E2E. 샘플은 대본에서 만든 합성 청크다.
- 공통 t=0 정렬. `atMs`는 스냅샷 타임스탬프 원점을 그대로 쓴다.
- FE 화면 실제 렌더링. `--frontend` 출력이 `types/interview.ts`의 `Moment` 형태와 맞는지만 확인했다.
- `aiReview.paragraphs`(AI 평가 서술)와 면접 전체 한 줄 요약은 이 이슈 범위 밖이다.
