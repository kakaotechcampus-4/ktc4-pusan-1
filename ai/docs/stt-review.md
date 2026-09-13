# STT 적대적 리뷰와 검증 기록

2026-09-13. 대상은 [PR #36](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/36) / [Issue #35](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/35)의 최초 공개 `72eb757` 및 후속 수정이다. 구현·회귀 테스트는 실제 Claude Opus(`claude-opus-5`), 독립 재현·검토·최종 문서는 Codex가 담당한다.

**Codex 독립 검증 완료.** Opus 3회 수정과 재리뷰 후 이번 범위에서 남은 재현 결함은 없다. 검증한 코드 커밋은 `7d10226`이며 아래 문서는 그 코드의 결과와 한계를 기록한다. PR #36은 팀 승인·머지 전이고 배포하지 않았다. 원격 HEAD와 CI 상태는 PR에서 확인한다.

## 검토에서 찾은 문제

| 항목 | 수정 전 재현 | 수정 방향·검증 |
| --- | --- | --- |
| 열린 소비자 종료 | 첫 청크 전·발화 사이 큐가 비면 iterator 종료 | 입력/종료 알림과 열린 큐 대기, 정상 close/drain |
| 세션 순서 충돌 | 두 트랙 모두 seq=0, 답변이 질문보다 먼저 정렬되어 Q&A 누락 | 공유 SessionOrdering·실제 offset, HTTP 역전·다중 청크·Q&A 검증 |
| 외부 응답 파싱 | HTML, list root, 짧은/비숫자 timestamp가 예외로 전파 | 안전한 SttError, start/end·유한값·순서 검증, 다음 정상 청크 복구 |
| 큐 무제한 | 요청 1개가 막힐 때 30청크·약 2.19MB PCM 대기 | max_pending, OVERLOADED 구간·상태 기록, 취소·회복 |
| 오류 본문 로그 | 공급자 reason의 가짜 비밀 표식이 로그에 등장 | 안전한 코드·메타데이터 로그, 인증/일시 오류 재시도 분류 |
| 지연 정의 | 5초 수신 후 4초 컷인데 길이+HTTP만 더해 1초 누락 | 샘플 위치·결정·큐·HTTP·순서 대기 계측, 주입 시계 검증 |
| 단어 시각 주장 | word 파라미터를 안 보낸 응답만으로 미지원 단정 | 실제 배포 bool schema와 기본 응답 관찰을 보존하고 명시적 word 동작은 미검증으로 정정 |
| 큰 정수 timestamp | 1차 수정 뒤에도 `10**400`에서 OverflowError | 변환 전 정수 범위 검사, 양/음·start/end·warm-up·스트림 회귀 |
| 취소/응답 완료 경합 | 이미 취소한 작업이 RELEASED로 바뀌며 전사 1건 전달 | 작업의 abandonment 상태를 명시, 성공/실패 경합과 정상 drain 회귀 |
| HTTP 의존성 로그 | 2차 수정 뒤 root INFO에서 httpx가 가짜 비공개 주소 출력 | 생성 시 호스트 등록과 httpx/httpcore 필터. root INFO/DEBUG·동시 무관 요청 회귀 및 실제 httpcore loopback 검증 |

## 확인한 실행과 한계

- 최초 공개본: Codex 독립 실행 165 tests, Ruff 통과. 그중 STT 44개였지만 위 결함은 기존 테스트가 놓쳤다.
- Opus 1차 인계: 전체 263 tests 통과 보고. Codex가 큰 정수·취소 경합을 추가 재현했다.
- Opus 2차 인계: 전체 272 tests 통과 보고. Codex 독립 재현은 `SttError`, 전사 0건/`ABANDONED`로 두 문제가 해소됐음을 확인했다. HTTP 의존성 로그 노출은 추가 발견했다.
- Opus 3차 인계: 전체 287 tests 통과 보고. Codex가 Python 3.12.13에서 전체 287 tests를 독립 실행해 통과를 확인했다(그중 STT 166개). Ruff lint, format 53파일, `uv lock --check`, `git diff --check`도 통과했다.
- Codex가 초기 재현의 수정 후 대응 스크립트를 재실행했다. 열린 소비자는 다음 발화를 받았고, 다중 트랙 Q&A의 답변 누락은 0건이었다. 불량 응답 6종은 안전한 거절로 기록됐고 다음 정상 응답을 전달했다. 30청크 입력/큐 한도 4에서 4개만 대기하고 나머지 26개는 `OVERLOADED`로 남았다. 5초 수신/4초 컷의 빠진 1초도 계측됐다.
- 큰 정수와 완료 직전 취소의 독립 스크립트는 `SttError`, 전사 0건/`ABANDONED`를 반환했다. root INFO 프로브의 배포 호스트 노출 값은 수정 전 `true`에서 `false`로 바뀌었다.
- MockTransport가 실행하지 않는 실제 httpcore 경로는 로컬 HTTP/1.1 서버로 추가 확인했다. root DEBUG 성공/500 응답에서 합성 호스트·요청 키·응답 본문 canary가 없고 메서드·상태 기록은 유지됐다. TLS·프록시·실제 Elice 트래픽 검증은 아니다. httpcore DEBUG 응답 헤더까지 임의 비밀값 제거를 보장하지 않는다.
- 기본 검증은 합성 PCM·HTTP mock이며 추가 확인은 loopback이다. 이 리뷰의 외부 STT API 호출은 **0회·합성 오디오 0초**다. 원래 합성 음성 benchmark 호출과 구분한다.
- 테스트 수는 이 STT 브랜치 기준이다. 별도 #23 인용 정책 브랜치 132 tests는 합산하지 않는다.

전체 검사 재실행은 `ai/`에서 한다. 실제 키 없이 가능하며 `.env`의 값은 출력하지 않는다.

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
```

기존 합성 음성 원본과 독립 감사 스크립트는 공개 저장소 밖 `stt-bench/`에 보존했다. 숫자는 [파이프라인 문서](stt-pipeline.md#기존-벤치마크와-공급자-관찰)에 재계산 방법과 함께 요약하며, 로컬 자료가 GitHub에 커밋됐다고 표시하지 않는다.

지연 수치·코퍼스·제약과 다음 실제 통합 검증은 [STT 파이프라인](stt-pipeline.md)을 따른다. 브라우저 표시·화면 무갱신 간격, 실제 마이크 정확도, LiveKit/BE/FE, 녹화/REALIGNED, 제품 LLM Luna를 이 패키지 테스트로 검증했다고 하지 않는다.
