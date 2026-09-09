# 면접 컨텍스트 분석 MVP 테스트 케이스

작성 기준: 2026-09-08. 멘토와 팀원이 구현 범위, 검증 근거, 미검증 항목을
한 번에 리뷰할 수 있도록 정리했다. 관련 입력·출력 계약은
[context-analysis.md](context-analysis.md), 실행 방법은 [AI README](../README.md)에 있다.

## 판정 기준

| 결과 | 의미 |
| --- | --- |
| 자동 통과 | 로컬에서 같은 입력으로 재현 가능한 코드 계약 검증 |
| 수동 확인 | 실제 GPT 호출이 필요하며 응답 문구가 매번 달라질 수 있는 품질 검증 |
| 미검증 | 실제 BE/STT/FE 또는 운영 환경이 필요해 이번 MVP에서 확인하지 않은 항목 |

자동 테스트는 실제 면접 데이터나 실제 OpenAI 네트워크를 사용하지 않는다.
OpenAI 연동 테스트는 실제 Python SDK가 만든 요청을 가짜 HTTP 응답과 연결해
직렬화, 구조화 응답 파싱, 오류 처리를 검증한다.

## 자동 테스트

### 입력과 전사 수정본

| ID | 입력·상황 | 기대 결과 | 자동 테스트 |
| --- | --- | --- | --- |
| TC-IN-01 | 정상 가상 Transcript | 세션과 발화 5개를 읽는다 | `test_sample_transcript_loads` |
| TC-IN-02 | `is_final: false` 중간 발화 포함 | 중간 발화를 Q&A·GPT 입력·근거에서 제외한다 | `test_final_utterances_exclude_provisional_results`, `test_real_sdk_request_and_parsing_with_stubbed_http` |
| TC-IN-03 | 입력 발화 순서가 뒤섞임 | 시작 시각 순으로 처리한다 | `test_final_utterances_are_sorted_by_start_time` |
| TC-IN-04 | 동일 ID의 final 수정본이 여러 개 있고 마지막에 interim 도착 | 마지막 final 전체 문자열을 쓰고 뒤늦은 interim은 무시한다 | `test_latest_final_revision_wins_even_when_interim_arrives_last` |
| TC-IN-05 | 동일 ID에서 화자 또는 시작 시각 변경 | 입력 검증 실패 | `test_conflicting_identity_in_revisions_is_rejected` |
| TC-IN-06 | 음수 시작 시각 또는 종료 < 시작 | 입력 검증 실패 | `test_utterance_rejects_negative_start`, `test_utterance_rejects_reversed_time_range` |
| TC-IN-07 | final 발화가 빈 문자열 또는 공백뿐 | 입력 검증 실패 | `test_blank_final_text_is_rejected` 2건 |

### Q&A 구조화와 세션 격리

| ID | 입력·상황 | 기대 결과 | 자동 테스트 |
| --- | --- | --- | --- |
| TC-QA-01 | 면접관 질문 뒤 지원자 답변 | 질문과 답변, 발화 ID, 전체 구간 시각을 한 쌍으로 반환한다 | `test_offline_analysis_has_source_evidence` |
| TC-QA-02 | 같은 화자의 연속 발화 조각 | 같은 질문 또는 답변 안에서 순서대로 합친다 | `test_grouping_handles_fragments_orphans_and_unanswered_question` |
| TC-QA-03 | 첫 질문 전에 지원자 발화 | 버리지 않고 `unpaired_utterance_ids`에 남긴다 | `test_grouping_handles_fragments_orphans_and_unanswered_question` |
| TC-QA-04 | 질문 뒤 final 답변 없음 | 빈 답변의 Q&A와 `UNANSWERED_QUESTIONS` 경고를 남긴다 | `test_unanswered_question_survives_without_llm` |
| TC-QA-05 | 두 세션을 동시에 분석 | 세션별 결과와 근거가 섞이지 않고 입력 변화가 결과에 반영된다 | `test_input_changes_result_and_concurrent_sessions_stay_separate` |
| TC-QA-06 | 이전 세션의 LLM 실패 후 다음 세션 분석 | 다음 세션은 독립적으로 정상 완료된다 | `test_provider_failure_preserves_qa_and_does_not_poison_next_session` |

### GPT 요청과 근거 검증

| ID | 입력·상황 | 기대 결과 | 자동 테스트 |
| --- | --- | --- | --- |
| TC-AI-01 | 기본 모델로 정상 구조화 응답 | `/v1/responses`, `gpt-4o-mini`, strict schema, `store: false`로 요청하고 응답을 파싱한다 | `test_real_sdk_request_and_parsing_with_stubbed_http` |
| TC-AI-02 | 모델을 `gpt-4o`로 지정 | 요청 모델이 바뀌고 같은 계약으로 처리한다 | `test_partial_grounding_and_model_override` |
| TC-GR-01 | 존재하지 않는 발화 ID 인용 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point0]` |
| TC-GR-02 | interim 발화 ID 인용 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point1]` |
| TC-GR-03 | 면접관 발화를 지원자 근거로 인용 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point2]` |
| TC-GR-04 | 원문에 없는 인용 또는 빈 인용 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point3]`, `[bad_point4]` |
| TC-GR-05 | 요약 수치가 해당 인용문에 없음 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point5]` |
| TC-GR-06 | 인용이 없거나 요약문이 공백 | 해당 요약 항목 전체를 제외한다 | `test_invalid_claim_is_removed_from_all_display_fields[bad_point6]`, `[bad_point7]` |
| TC-GR-07 | 한 항목에 유효·무효 인용이 함께 있음 | 일부 인용만 남기지 않고 항목 전체를 제외한다 | `test_one_bad_citation_rejects_whole_claim` |
| TC-GR-08 | 유효한 인용 | 화자와 시작·종료 시각을 모델 응답이 아닌 Transcript에서 붙인다 | `test_times_and_speaker_come_from_transcript` |
| TC-GR-09 | 일부 요약만 근거 검증 통과 | 통과 항목만 반환하고 상태 `partial`, `UNGROUNDED_POINTS_REMOVED` 경고를 기록한다 | `test_partial_grounding_and_model_override` |
| TC-GR-10 | 미리 정한 상수 요약을 정상 결과처럼 반환 | 근거 있는 points가 없으므로 `NO_GROUNDED_SUMMARY`로 실패한다 | `test_preset_fake_is_not_reported_as_grounded_analysis` |

### 실패와 보안

| ID | 입력·상황 | 기대 결과 | 자동 테스트 |
| --- | --- | --- | --- |
| TC-ER-01 | 확정된 지원자 발화가 없음 | 모델을 호출하지 않고 `empty`, `NO_FINAL_CANDIDATE_SPEECH`를 반환한다 | `test_empty_or_interim_input_never_calls_model` |
| TC-ER-02 | 분석 제한 시간 초과 | `failed`, `LLM_TIMEOUT`, 재시도 가능으로 반환하고 Q&A를 보존한다 | `test_agent_timeout_retains_transcript_structure` |
| TC-ER-03 | OpenAI 401 | `LLM_API_ERROR`, 재시도 불가로 반환한다 | `test_http_errors_are_safe_and_preserve_qa[401-LLM_API_ERROR-False]` |
| TC-ER-04 | OpenAI 429 | `LLM_RATE_LIMITED`, 재시도 가능으로 반환한다 | `test_http_errors_are_safe_and_preserve_qa[429-LLM_RATE_LIMITED-True]` |
| TC-ER-05 | OpenAI 503 | `LLM_API_ERROR`, 재시도 가능으로 반환한다 | `test_http_errors_are_safe_and_preserve_qa[503-LLM_API_ERROR-True]` |
| TC-ER-06 | 거절, 잘못된 JSON, 미완료 출력, 빈 요약 | 성공 결과를 만들지 않고 `failed`로 반환한다 | `test_unusable_responses_fail_without_fabricated_summary` 4건 |
| TC-SEC-01 | 공급자 오류 본문에 비공개 문자열 포함 | 분석 결과에 원본 오류 본문을 노출하지 않는다 | `test_http_errors_are_safe_and_preserve_qa` 3건 |
| TC-SEC-02 | 잘못된 입력에 비공개 문자열 포함 | CLI 오류 출력에 입력 본문을 노출하지 않는다 | `test_invalid_input_does_not_echo_sensitive_data` |
| TC-SEC-03 | API Key 미설정 | 가짜 성공으로 대체하지 않고 `OPENAI_API_KEY_MISSING`, 종료 코드 2를 반환한다 | `test_missing_key_does_not_fall_back_to_fake_success` |
| TC-SEC-04 | 설정 객체 출력 | LiveKit·OpenAI Secret 값이 표시되지 않는다 | `test_secret_values_are_masked` |

### 실행 인터페이스와 기존 환경

| ID | 입력·상황 | 기대 결과 | 자동 테스트 |
| --- | --- | --- | --- |
| TC-CLI-01 | 가상 샘플을 오프라인 모드로 실행 | 종료 코드 0, `completed`, Q&A 2개를 JSON으로 출력한다 | `test_offline_cli_reads_backend_fixture_and_prints_json` |
| TC-EV-01 | 핵심 사실 또는 원문에 없는 수치 검사 | 공백·영문 대소문자를 정규화하고 없는 수치를 중복 없이 찾는다 | `test_evaluation.py` 6건 |
| TC-CFG-01 | 기본값과 환경변수 설정 | 기본 `gpt-4o-mini`, 허용된 `gpt-4o` 변경, Secret 로딩을 확인한다 | `test_config.py` 3건 |
| TC-ENV-01 | 공통 AI 환경 | LiveKit SDK import와 비동기 테스트 환경이 동작한다 | `test_environment.py` 2건 |
| TC-LEG-01 | 기존 요약 프로토콜과 테스트 대역 | 인터페이스 호환과 final 발화 선택을 확인한다 | `test_summarize.py` 3건 |

## 자동 테스트 재현

`ai/` 디렉터리에서 실행한다.

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

2026-09-09 로컬 결과:

```text
54 passed
ruff lint passed
ruff format check passed
uv lock check passed
source distribution and wheel build passed
```

세부 테스트 이름은 다음 명령으로 확인할 수 있다.

```bash
uv run pytest --collect-only -q
```

## 실제 GPT 수동 테스트

수동 테스트 전 `.env`에 본인의 개발용 `OPENAI_API_KEY`를 넣는다. Key와 `.env`는
커밋하거나 테스트 결과에 복사하지 않는다. 아래 입력은 모두
[sample_interview.json](../tests/fixtures/sample_interview.json)의 가상 대화다.

### MT-GPT-01 - GPT-4o mini 기본 분석

```bash
uv run python -m irya_ai tests/fixtures/sample_interview.json
```

통과 기준:

- 프로세스 종료 코드가 0이고 `status`가 `completed`다.
- 요약에 `Django`에서 `FastAPI`로 전환한 경험과 응답 시간 `40%` 감소가 유지된다.
- 배포 주기 `주 1회`에서 `주 3회`로 변경한 수치의 의미가 바뀌지 않는다.
- 모든 `evidence.quote`가 해당 지원자 원문에 정확히 존재한다.
- 근거 ID는 `u-002` 또는 `u-004`이며 중간 발화 `u-004-partial`은 없다.
- 합격·불합격, 점수, 순위, 성격·감정 판단을 생성하지 않는다.
- `model`에 공급자가 반환한 실제 모델 ID가 기록된다.

### MT-GPT-02 - GPT-4o 비교

```bash
uv run python -m irya_ai tests/fixtures/sample_interview.json --model gpt-4o
```

MT-GPT-01과 같은 기준으로 통과 여부를 판정한다. 추가로 실행 시간을 기록하고,
두 모델의 요약 항목 수·제외 항목 수·핵심 사실 누락 여부를 아래 표에 남긴다.

| 실행 시각 | 모델 | 상태 | elapsed_ms | 요약 항목 | 제외 항목 | 핵심 사실 누락 | 비고 |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| TBD | `gpt-4o-mini` | TBD | TBD | TBD | TBD | TBD | API Key 설정 후 기록 |
| TBD | `gpt-4o` | TBD | TBD | TBD | TBD | TBD | API Key 설정 후 기록 |

### MT-GPT-03 - 반복 실행 안정성

`gpt-4o-mini`로 MT-GPT-01을 3회 실행한다.

통과 기준:

- 세 실행 모두 원문에 없는 수치나 경력을 추가하지 않는다.
- 표현이나 항목 수가 달라도 위 핵심 사실의 의미가 유지된다.
- 인용 검증에서 제외된 항목이 있으면 `partial`과 `rejected_point_count`로 드러난다.
- 실패가 발생하면 성공처럼 빈 요약을 반환하지 않고 `error.code`를 남긴다.

## 실제 연동 후 추가할 테스트

아래 항목은 현재 자동 테스트 통과로 주장하지 않는다.

| ID | 필요한 환경 | 확인할 내용 |
| --- | --- | --- |
| IT-BE-01 | BE가 확정한 실제 DTO·호출 경로 | 필드명, 시간 기준, `stage`, 수정본 순서가 계약과 맞는지 |
| IT-STT-01 | 실제 LiveKit 트랙과 STT | 중간본·최종본·재전송을 거쳐 Q&A와 근거가 중복되지 않는지 |
| IT-AI-01 | 실제 OpenAI 계정과 네트워크 | 모델 접근, 응답 품질, 오류율, 30초 제한, 호출 지연 |
| IT-FAIL-01 | 진행 중인 실제 통화 | GPT·STT 장애가 통화·녹화를 중단하지 않는지 |
| IT-FE-01 | FE 화면 | `completed`·`partial`·`failed`·`empty`, 경고, 원문 시각을 올바르게 표시하는지 |
| IT-LOAD-01 | 여러 동시 면접 | 처리량, rate limit, 큐 길이와 세션 격리 |

## 멘토 리뷰 요청 지점

1. 백엔드가 전체 Transcript 스냅샷을 보내는 가정과 수정본 선택 규칙이 적절한가.
2. 화자 전환만으로 Q&A를 나누는 MVP 기준이 충분한가.
3. 정확한 부분 문자열 인용과 수치 검사 후에도 필요한 의미 검증이 무엇인가.
4. `partial` 상태에서 통과한 항목을 노출하는 것이 적절한가.
5. 분석 재시도 주체와 실제 STT·BE 연결 시 호출 시점을 어디에 둘 것인가.
