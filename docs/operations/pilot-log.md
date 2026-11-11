# 운영 사용 기록 (2026-09-17 ~ 2026-11-10)

운영 서버(`irya.cloud`)에서 팀이 직접 면접을 돌려 본 기록입니다. 그동안 운영에서 많이 돌렸지만 어디에도 숫자로 남기지 않아서, 운영 DB 와 배포 기록에서 실측값을 뽑아 한 곳에 모았습니다.

- 집계 시점: 2026-11-11 (KST). 날짜는 모두 KST 기준입니다.
- 집계 방법: SSM 으로 운영 EC2 에 들어가 `psql` 을 `default_transaction_read_only=on` 으로 띄우고 `SELECT` 집계만 했습니다. 데이터는 바꾸지 않았습니다. 쿼리는 [맨 아래](#재현-쿼리)에 있습니다.
- 이름 · 발화 내용 · 카카오 ID 같은 개인정보는 옮기지 않았습니다. 건수와 날짜, 상태값만 있습니다.
- 팀원이 아닌 사람도 썼습니다. 계정은 팀원과 팀원 외로만 나눴고, 누구인지는 적지 않았습니다. 테스트하다 중간에 끊은 면접도 그대로 들어 있습니다.

## 한눈에 보기

| 항목 | 값 |
|---|---|
| 카카오 로그인 계정 | 10개 — 팀원 5 · 팀원 외 5. 면접을 끝까지 종료해 본 계정은 8개 |
| 팀원 외 계정이 만든 면접 | 20건 (3개 계정) |
| 만든 면접 | 44건 (첫 건 09-17, 마지막 건 11-10) |
| 면접방 세션 | 43개 — 종료 32 · 대기 10 · 진행 중으로 남은 것 1 |
| 실제 진행 시간 | 시작 · 종료가 모두 찍힌 30회, 합계 179.4분 (중앙값 2.0분, 최장 23.3분) |
| 실시간 자막 발화 | 637개, 22개 세션 (면접관 515 · 지원자 122) |
| 꼬리질문 제안 | 35개, 5개 세션 |
| 녹화 | 23건 모두 `READY` (중앙 1분 58초, 최장 16분 1초) |
| 면접 전 준비(PREP) | 29건 — `READY` 22 · `FAILED` 7. 성공 건 처리 시간 중앙 5.5초, 최장 48.4초 |
| 면접 후 요약 | 29건 — `READY` 2 · `FAILED` 27 (아래 [요약 실패](#요약은-1108-전까지-계속-실패했다)) |
| 검토 표시 | 19개 — 채택 13 · 제외 2 · 북마크만 4 |
| 검토 완료 · 리포트 | 2건 · 2건 (리포트 생성 중앙 17.5초) |

## 끝까지 돈 면접 2건

준비 → 면접 → 자막 · 꼬리질문 → 녹화 → 요약 · 확인할 내용 → 검토 완료 → 리포트까지 한 번에 이어진 면접은 11-08, 11-10 두 건입니다. 11-10 건은 테스트 가이드 시나리오(가상 회사 「노드로우」)로 돌린 것입니다.

| 날짜 | 진행 | 자막 발화 | 꼬리질문 | 녹화 | 요약 | 확인할 내용 | 검토 표시 | 검토 | 리포트 |
|---|---|---|---|---|---|---|---|---|---|
| 11-08 | 5.4분 | 55 | 12 | READY | READY | COMPLETED | 8 | CONFIRMED | READY |
| 11-10 | 3.7분 | 48 | 12 | READY | READY | COMPLETED | 11 | CONFIRMED | READY |

## 날짜별 세션

| 날짜 | 세션 | 종료 | 비고 |
|---|---|---|---|
| 09-17 | 6 | 3 | 첫 배포 날. 자막 없음 |
| 10-03 ~ 10-06 | 7 | 5 | 자막 없음 |
| 10-07 | 2 | 2 | 처음으로 자막 · 꼬리질문이 운영에서 쌓임 (발화 79, 꼬리질문 6) |
| 10-11 | 1 | 1 | 한 세션에 발화 232개 (가장 긴 자막) |
| 10-14 ~ 10-15 | 2 | 1 | PREP 첫 성공 |
| 10-23 | 3 | 2 | |
| 10-26 ~ 10-28 | 17 | 13 | 가장 많이 돌린 기간. 10-27 하루에만 13세션 |
| 11-04 ~ 11-05 | 3 | 3 | 확인할 내용(findings) 첫 생성 |
| 11-08 | 1 | 1 | 첫 리포트 |
| 11-10 | 1 | 1 | 테스트 가이드 시나리오 |

## 요약은 11-08 전까지 계속 실패했다

숨기지 않고 남깁니다. 면접 후 요약 29건 중 27건이 `FAILED` 입니다.

- 10-03 ~ 10-23 의 11건은 `model` 칸이 비어 있습니다. 이 가운데 5건은 발화가 0개였습니다.
- 10-27 ~ 10-28 의 13건은 `gpt-6-luna` 로 돌았지만 모두 `FAILED` 입니다.
- 11-04 1건은 요약은 `FAILED`, 확인할 내용은 `COMPLETED` 였습니다. 11-05 2건은 발화가 0 · 5개라 확인할 내용이 `EMPTY` 였습니다. 실패와 빈 목록을 화면에서 구분하는 건 #251 에서 했습니다.
- 11-08 부터 요약 · 확인할 내용 · 리포트가 모두 성공했습니다.

이 기간에 머지된 관련 PR 은 #229 (REVIEW 폴러에 findings 에이전트 연결), #241 (운영에서 한 사이클 처음 완주), #252 · #250 (리포트 생성), #296 (리포트 작업 실패 원인 코드 로그) 입니다. 서버 로그는 11-10 재배포 이후 것만 남아 있어서, 11-08 이전 실패 건마다의 원인은 로그로 다시 확인할 수 없습니다.

PREP 실패 7건은 10-07 · 10-11 · 10-27(3) · 10-28(2) 입니다. 10-28 이후로는 실패가 없습니다.

## 배포 · 백업

| 항목 | 값 | 출처 |
|---|---|---|
| 자동 배포 (`cd.yml`) | 99회 — 성공 89 · 실패 6 · 취소 4 (09-17 ~ 11-11) | GitHub Actions 실행 기록 |
| DB 백업 | 10-25 부터 11-11 까지 하루도 안 빠지고 18개 | S3 `db/` (`infra/backup-db.sh`, 매일 KST 04시) |

## 재현 쿼리

운영 EC2 의 `infra/` 에서 읽기 전용으로 띄웁니다.

```sh
docker compose exec -T db sh -c \
  'PGOPTIONS="-c default_transaction_read_only=on" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off'
```

```sql
SET TIME ZONE 'Asia/Seoul';

-- 계정 · 면접 수와 기간
SELECT count(*), min(created_at)::date, max(created_at)::date FROM app_user;
SELECT count(*), min(created_at)::date, max(created_at)::date FROM interview;

-- 세션 상태, 진행 시간
SELECT status, count(*) FROM session GROUP BY 1;
SELECT count(*),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM ended_at - started_at)) / 60,
       max(extract(epoch FROM ended_at - started_at)) / 60,
       sum(extract(epoch FROM ended_at - started_at)) / 60
FROM session WHERE started_at IS NOT NULL AND ended_at > started_at;

-- 단계별 상태
SELECT speaker, count(*) FROM utterance GROUP BY 1;
SELECT status, count(*), count(DISTINCT session_id) FROM suggestion GROUP BY 1;
SELECT status, count(*) FROM interview_prep GROUP BY 1;
SELECT requested_at::date, status, findings_status, model, count(*) FROM session_summary GROUP BY 1, 2, 3, 4 ORDER BY 1;
SELECT status, count(*) FROM recording GROUP BY 1;
SELECT state, bookmarked, count(*) FROM review_mark GROUP BY 1, 2;
SELECT review_status, count(*) FROM interview GROUP BY 1;
SELECT status, completed_at::date FROM interview_report;
```
