> 2026-10-31 갱신: 현재 리뷰 PR은 [#281](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/281) 하나이며 base는 develop이다. #257–#271은 코드 포함 확인 후 중복 정리로 닫았다. 아래 표는 최초 스택 구조의 이력이다. 현재 통합 내역은 [2026-10-31 기록](../2026-10-31/CONSOLIDATION.md)을 따른다.

# 기능 PR과 후속 이슈

2026-10-30 발행한 초안 PR이다. 아래 15개 PR의 실행된 CI는 이 기록 시점에 전부 통과했다. 병합·배포 완료와 구분한다.

| PR                                                                 | head                                 | base                                |
| ------------------------------------------------------------------ | ------------------------------------ | ----------------------------------- |
| [#257](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/257) | `feature/248-interview-panels`       | `develop`                           |
| [#258](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/258) | `feature/240-report-ui`              | `feature/248-interview-panels`      |
| [#259](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/259) | `feature/interview-resume`           | `feature/240-report-ui`             |
| [#260](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/260) | `feature/interview-media-controls`   | `feature/interview-resume`          |
| [#261](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/261) | `feature/suggestion-dismiss`         | `feature/interview-media-controls`  |
| [#262](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/262) | `feature/suggestion-focus-view`      | `feature/suggestion-dismiss`        |
| [#263](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/263) | `feature/candidate-management-grid`  | `feature/suggestion-focus-view`     |
| [#264](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/264) | `feature/candidate-inline-review`    | `feature/candidate-management-grid` |
| [#265](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/265) | `feature/candidate-compare`          | `feature/candidate-inline-review`   |
| [#266](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/266) | `feature/candidate-export`           | `feature/candidate-compare`         |
| [#267](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/267) | `feature/review-processing-ui`       | `feature/candidate-export`          |
| [#268](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/268) | `feature/interview-owner-read`       | `feature/238-report-be`             |
| [#269](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/269) | `feature/suggestion-reason-contract` | `feature/interview-owner-read`      |
| [#270](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/270) | `feature/suggestion-focus-ai`        | `feature/239-report-generator`      |
| [#271](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/271) | `feature/249-report-poller`          | `feature/suggestion-focus-ai`       |

## 최종 통합

[#281](https://github.com/kakaotechcampus-4/ktc4-pusan-1/pull/281)에서 기존 #253·#254 충돌을 해결하고, FE 51개·BE 789개·AI 989개를 다시 검사했다. 아래 기능 PR 통합 뒤 base를 develop으로 바꿔 반영한다. 원격 병합·배포는 하지 않았다.

## 후속 이슈

- [면접 당시 회사·직무 스냅샷 보존](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/272)
- [지원자 식별·재지원·면접 차수와 과거 세션 이력](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/273)
- [조직·팀 권한과 면접관 간 공유](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/274)
- [여러 기기 메모 수정 충돌 감지](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/275)
- [관리 목록 고급 열·수식·공동 편집 도입 조건](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/276)
- [파일 재가져오기와 신규 면접 일괄 생성 도입 조건](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/277)
- [검토 변경 후 리포트 유효성·무효화·재생성 정책](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/278)
- [완료 알림 SSE 전환 필요성 측정](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/279)
- [관리 화면 추가 자료의 공개 API·보관 정책](https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues/280)

## 남은 통합

- 동의 #255/#256: 사용자 계약 선택 뒤 하나만 사용. 현재 기존 입장 정책으로 검증했으므로 동의 차단 완료로 간주하지 않는다.
- 삭제 #246: 기존 담당 작업 추적. 실제 삭제·연관 자료 제거 검증은 미완료.
- 공유·지원자 식별·회사 직무 스냅샷·실제 제공되지 않는 데이터는 후속 이슈 조건 충족 후 도입.
- F10 v3 원문 시안·외부 STT/LLM 품질·물리 기기·Egress/파일 저장은 별도 검증 필요.
