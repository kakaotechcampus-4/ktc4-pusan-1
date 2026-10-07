# Findings 생성기 — #137 REVIEW 입력

사전 가공 결과 `InterviewContext`와 BE에 저장된 `TranscriptSnapshot`을 받아,
기존 `Finding` 목록을 만든다. 폴러는 `FindingsAgent.run(context, snapshot)`을 호출하고
결과의 `findings`를 REVIEW 요청에 넣는다. PREP/REVIEW 폴러와 BE API는 정원·BE 담당
후속이며 이 변경에 포함하지 않는다. `Resume.text` 스키마는 선행 PR #156을 따른다.

## 실행

```bash
# 개인정보 없는 합성 컨텍스트 + 저장된 FINAL 한 건, 외부 호출 없음
uv run irya-ai findings data/samples/findings_context.json --backend extractive

# 컨텍스트와 전사 파일을 따로 받은 경우
uv run irya-ai findings context.json stored-finals.json --backend extractive

# 기존 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL로 모델 호출
uv run irya-ai findings context.json stored-finals.json
```

BE 컨텍스트 응답의 `utterances`는 CLI가 분리해서 `TranscriptSnapshot`으로 검증한다.
별도 전사는 JSON 배열·JSON Lines·스냅샷을 기존 `load_chunks`로 읽는다.
서로 다른 세션의 컨텍스트와 전사는 `CONTEXT_SESSION_MISMATCH`로 실패한다.

## 검증과 결과

- 마지막 FINAL 수정본만 사용한다. 뒤늦은 INTERIM은 FINAL을 덮지 않는다.
- 모델은 종류·참조 ID·인용·요약을 작성한다. ID·시각·세션·검토 상태는 코드가 정한다.
- 참조는 입력의 `claimId`·`competencyId`에 있어야 한다. ID 형식을 파싱하지 않는다.
- 주장 종류는 claimId가 필수이고, 역량 근거·GAP은 competencyId가 필수다.
- GAP 이외의 근거는 지원자 FINAL 발화 하나의 연속 부분 문자열이다. 정규화는 기존
  grounding과 같은 NFC + 기존 공백 축약이다. 의역·대소문자·단어 경계 수정은 거부한다.
- GAP은 역량에 관한 근거 부재다. claimId·인용·시각 없이 내며 역량 부족이라고 단정하지 않는다.
- 관련 발언 없는 주장은 생략한다. 기존 Finding 계약이 CLAIM_UNVERIFIED에도 전사 근거를
  요구하므로, 무근거 주장을 해당 종류로 만들지 않는다.
- 시각은 기존 grounding이 원문 단어 시각에서 계산하고 없으면 발화 시작으로 돌아간다.
- ID는 종류·역량·주장·근거 발화·정규화 인용의 JSON 배열을 SHA-256으로 해시한
  `fnd_` + 24자리 값이다. 순서·요약 문구 변경은 ID를 바꾸지 않고 인용 변경은 바꾼다.
- 최대 24개, 요약 최대 240자는 **이번 구현의 기본값**이며 팀이 확정한 수치가 아니다.
- 중복·상한 초과·미지원 수치·잘못된 인용은 탈락한다. 탈락 이유는 순번과 코드 설명만
  담고 이력서·발화·모델 응답 본문을 넣지 않는다. AI 상태는 항상 PROPOSED다.

결과는 `completed`(초안 전부 통과, 0개도 가능), `partial`(일부 탈락),
`failed`(모델 실패 또는 전부 탈락), `empty`(가공 컨텍스트 또는 지원자 FINAL 없음)이다.
LIVE 입력에는 PROVISIONAL_TRANSCRIPT 경고를 남긴다. FINAL 청크라고 녹화에 정렬된
확정 전사가 되는 것은 아니다.

## 검증 범위와 한계

자동 테스트는 참조·인용·정정·결정적 ID·오류 처리·게이트웨이 요청·CLI 계약을 검증한다.
오프라인 baseline은 이력서 주장과 답변에 정확히 같은 문장이 있을 때만 CLAIM_VERIFIED를
만든다. 이는 **면접 답변에 같은 표현이 있었다는 관찰**이며 이력서 주장의 사실성 입증은 아니다.
LLM 입력에서도 지원자 이름·이력서 전체 본문·storageKey·시각을 제외한다.

실제 LLM 의미 판단 품질과 #162/#164의 BE 저장·폴러 통합은 아직 검증하지 않았다.
입력 전체 FINAL을 보내며 임의로 앞부분을 잘라 누락된 답변을 GAP으로 만들지 않는다.
모델의 입력 한도 초과는 안전한 LLM_BAD_REQUEST로 실패한다. 문자 인용 검증은
요약의 의미·역량 연결·모순 판정까지 입증하지 못하므로 면접관 검토가 필요하다.

출처: [#137](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/137),
[#156](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/156),
[#162](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/162),
[#164](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/164).
