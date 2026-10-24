/**
 * 지원자 목록 (S4) — `GET /api/v1/interviews`
 *
 * 내가 만든 면접을 한 줄씩 보여준다. 서버는 최신순으로 내 것을 전부 주고,
 * 거르고 정렬하는 일은 여기서 한다 (#137 1-1).
 *
 * 점수도 순위도 만들지 않는다. 숫자는 「무엇을 아직 안 봤는지」를 가리킬 뿐이다 —
 * 판단은 면접관이 한다.
 *
 * 샘플 화면(`/demo/candidates`)에 있는 경력 · 질문 수 · 나란히 비교는 서버에 그
 * 데이터가 없어 넣지 않았다.
 */

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listInterviews } from '../api/interview';
import { durationLabel, pendingReason } from '../lib/interviewList';
import type { ReviewStatus } from '../types/interview';

/** 검토 상태의 한글 표시. 서버는 값만 주고 말은 FE 가 정한다 (#137 1-3). */
const STATUS_LABEL: Record<ReviewStatus, string> = {
  PENDING: '검토 대기',
  IN_REVIEW: '검토 중',
  CONFIRMED: '확정',
};

type Filter = 'all' | ReviewStatus;
type Sort = 'recent' | 'name' | 'needsReview';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: 'PENDING', label: STATUS_LABEL.PENDING },
  { id: 'IN_REVIEW', label: STATUS_LABEL.IN_REVIEW },
  { id: 'CONFIRMED', label: STATUS_LABEL.CONFIRMED },
];

/** 이름을 비워 두고 만든 면접이 있다. 목록에서 빈 칸으로 보이면 줄을 못 읽는다. */
const UNNAMED = '이름 없는 지원자';

const POLL_INTERVAL_MS = 3000;

const dateLabel = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));

export default function InterviewListPage() {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ['interviews'],
    queryFn: listInterviews,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.summaryStatus === 'PROCESSING')
        ? POLL_INTERVAL_MS
        : false,
  });

  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<Sort>('recent');

  const items = useMemo(() => data?.items ?? [], [data]);

  /**
   * 검색만 적용한 결과. 상태 필터와 따로 두는 이유는 칩의 숫자 때문이다 —
   * 칩이 검색을 무시하고 전체를 세면 표에 한 줄만 남은 채 「전체 10」이 떠서
   * 나머지 아홉이 어디로 갔는지 알 수 없다.
   *
   * 직무로는 찾지 않는다. 서버가 `role` 을 내 컨텍스트에서 한 번 읽어 모든 줄에 같은
   * 값으로 주므로(`list_interviews`), 직무 검색은 전체가 통과하거나 전무가 된다.
   */
  const searched = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ko-KR');
    if (!query) return items;
    return items.filter((item) =>
      (item.candidateName ?? '').toLocaleLowerCase('ko-KR').includes(query),
    );
  }, [items, search]);

  const filtered = useMemo(() => {
    const result =
      filter === 'all' ? searched : searched.filter((item) => item.reviewStatus === filter);

    // 서버가 최신순으로 주므로 'recent' 는 받은 순서 그대로 둔다.
    if (sort === 'recent') return result;
    return [...result].sort((left, right) => {
      if (sort === 'name') {
        return (left.candidateName ?? '').localeCompare(right.candidateName ?? '', 'ko-KR');
      }
      return (right.counts?.needsReview ?? 0) - (left.counts?.needsReview ?? 0);
    });
  }, [searched, filter, sort]);

  const countFor = (id: Filter) =>
    id === 'all' ? searched.length : searched.filter((item) => item.reviewStatus === id).length;

  return (
    <div className="min-h-full bg-[#121316] text-[#eaecef]">
      <main className="mx-auto max-w-[1440px] px-4 py-7 sm:px-6 lg:px-8">
        <header className="border-b border-[#272a33] pb-5">
          <p className="text-ink-muted font-mono text-xs">지원자 검토</p>
          <h1 className="mt-1 text-xl font-bold sm:text-2xl">지원자 목록</h1>
          <p className="mt-2 text-xs text-[#9498a4]">
            내가 만든 면접입니다. 근거와 면접 기록을 검토합니다. 점수와 순위는 제공하지 않습니다.
          </p>
        </header>

        {isLoading && <p className="mt-8 text-sm text-[#9498a4]">불러오는 중…</p>}

        {isError && (
          <div role="alert" className="mt-8 text-sm text-amber-300">
            <p>지원자 목록을 불러오지 못했습니다.</p>
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="mt-2 underline disabled:opacity-50"
            >
              다시 확인
            </button>
          </div>
        )}

        {/*
          조회가 한 번 성공한 뒤 재조회가 실패하면 v5 는 앞의 data 를 그대로 들고 있다.
          그러면 오류 배너와 「아직 만든 면접이 없습니다」가 같이 떠서 서로 다른 말을 한다.
        */}
        {data && !isError && items.length === 0 && (
          <section className="mt-8 rounded-lg border border-[#272a33] bg-[#18191f] p-6">
            <h2 className="text-sm font-semibold">아직 만든 면접이 없습니다</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#9498a4]">
              면접을 만들면 여기에 쌓입니다. 화면 동작만 먼저 보려면 샘플을 열 수 있습니다.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link
                to="/interviews/new"
                className="inline-flex rounded border border-[#3f4452] bg-[#202229] px-3 py-2 text-xs font-semibold text-[#eaecef] hover:bg-[#282b34]"
              >
                면접 만들기
              </Link>
              <Link
                to="/demo/candidates"
                className="inline-flex rounded border border-[#3f4452] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
              >
                샘플 검토 화면 열기
              </Link>
            </div>
          </section>
        )}

        {items.length > 0 && (
          <>
            <section className="mt-5 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex gap-2 overflow-x-auto pb-1">
                {FILTERS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setFilter(item.id)}
                    aria-pressed={filter === item.id}
                    className={`shrink-0 rounded-full border px-3 py-2 text-xs ${
                      filter === item.id
                        ? 'border-[#eaecef] bg-[#f0f2f5] font-bold text-[#121316]'
                        : 'border-[#2e323c] bg-[#202229] text-[#9498a4] hover:bg-[#282b34]'
                    }`}
                  >
                    {item.label}
                    <span className="ml-1.5 font-mono text-[10px]">{countFor(item.id)}</span>
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <label className="sr-only" htmlFor="candidate-search">
                  지원자 이름 검색
                </label>
                <input
                  id="candidate-search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="지원자 이름 검색"
                  className="placeholder:text-ink-muted min-w-0 rounded border border-[#2e323c] bg-[#17191f] px-3 py-2 text-xs text-[#eaecef] sm:w-56"
                />
                <label className="sr-only" htmlFor="candidate-sort">
                  정렬
                </label>
                <select
                  id="candidate-sort"
                  value={sort}
                  onChange={(event) => setSort(event.target.value as Sort)}
                  className="rounded border border-[#2e323c] bg-[#17191f] px-3 py-2 text-xs text-[#c4c7c9]"
                >
                  <option value="recent">최신순</option>
                  <option value="name">이름순</option>
                  <option value="needsReview">확인 필요 많은순</option>
                </select>
              </div>
            </section>

            <div className="mt-4 overflow-x-auto rounded-lg border border-[#272a33] bg-[#15161b]">
              <table className="w-full min-w-[860px] border-collapse text-left text-xs">
                <thead className="text-ink-muted bg-[#15161b]">
                  <tr className="border-b border-[#272a33]">
                    {[
                      '지원자',
                      '검토 상태',
                      '면접',
                      '확인 항목',
                      '확인 필요',
                      '근거 채택',
                      '면접 길이',
                    ].map((label) => (
                      <th
                        key={label}
                        scope="col"
                        className="px-3 py-3 font-medium whitespace-nowrap"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((item) => {
                    const reason = pendingReason(item);
                    const duration = durationLabel(item.durationSec);
                    return (
                      <tr
                        key={item.interviewId}
                        className="border-b border-[#22242c] last:border-0 hover:bg-white/[0.015]"
                      >
                        <td className="px-3 py-4">
                          {/* 아직 지원자 상세 화면이 없다. 면접 기록이 가장 가까운 다음 화면이다. */}
                          <Link
                            to={`/review/${item.interviewId}`}
                            className="block min-w-40 hover:text-white"
                          >
                            <span className="block font-semibold">
                              {item.candidateName ?? UNNAMED}
                            </span>
                            {item.role && (
                              <span className="text-ink-muted mt-1 block text-[10px]">
                                {item.role}
                              </span>
                            )}
                          </Link>
                        </td>
                        <td className="px-3 py-4">
                          <span
                            className={`rounded border px-2 py-1 text-[10px] whitespace-nowrap ${
                              item.reviewStatus === 'PENDING'
                                ? 'border-amber-500/50 bg-[#ffe082] font-bold text-[#212121]'
                                : 'border-[#2e323c] bg-[#202229] text-[#c4c7c9]'
                            }`}
                          >
                            {STATUS_LABEL[item.reviewStatus]}
                          </span>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap">
                          {item.interviewedAt ? (
                            <span className="block font-mono">{dateLabel(item.interviewedAt)}</span>
                          ) : (
                            <span className="text-ink-muted block">아직 보지 않음</span>
                          )}
                          <span className="text-ink-muted mt-1 block text-[10px]">
                            {item.interviewer.nickname}
                          </span>
                        </td>
                        {reason ? (
                          // 숫자 세 칸이 모두 같은 이유로 비므로 한 칸으로 합쳐 한 번만 말한다.
                          <td colSpan={3} className="text-ink-muted px-3 py-4">
                            {reason}
                          </td>
                        ) : (
                          <>
                            <td className="px-3 py-4 font-mono whitespace-nowrap">
                              {item.counts!.coverageConfirmed}/{item.counts!.coverageTotal}
                            </td>
                            <td className="px-3 py-4 font-mono whitespace-nowrap">
                              {item.counts!.needsReview}건
                            </td>
                            <td className="px-3 py-4 font-mono whitespace-nowrap">
                              {item.counts!.adopted}/{item.counts!.findings}
                            </td>
                          </>
                        )}
                        <td className="px-3 py-4 font-mono whitespace-nowrap">
                          {duration === null ? <span className="text-ink-muted">—</span> : duration}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length === 0 && (
                <p className="p-8 text-center text-sm text-[#9498a4]">
                  조건에 맞는 지원자가 없습니다.
                </p>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
