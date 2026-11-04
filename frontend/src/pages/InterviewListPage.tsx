/**
 * 지원자 목록 (S4) — `GET /api/v1/interviews`
 *
 * 내가 만든 면접을 한 줄씩 보여준다. 서버는 최신순으로 내 것을 전부 주고,
 * 거르고 정렬하는 일은 여기서 한다 (#137 1-1).
 *
 * 점수도 순위도 만들지 않는다. 숫자는 「무엇을 아직 안 봤는지」를 가리킬 뿐이다 —
 * 판단은 면접관이 한다.
 *
 * 줄을 누르면 미리보기 시트가 열리고, 거기서 면접 기록으로 간다 (#232).
 */

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listInterviews } from '../api/interview';
import emptyInterviews from '../assets/illustrations/empty-interviews.webp';
import { DeleteInterviewButton } from '../components/interview/DeleteInterviewButton';
import { Badge } from '../components/ui/Badge';
import { buttonClass } from '../components/ui/buttonClass';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { Sheet } from '../components/ui/Sheet';
import { Skeleton } from '../components/ui/Skeleton';
import { durationLabel, pendingReason, STATUS_LABEL, STATUS_TONE } from '../lib/interviewList';
import type { InterviewListItem, ReviewStatus } from '../types/interview';

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

  // 줄을 누르면 오른쪽(좁으면 아래) 시트로 미리 본다. 목록을 떠나지 않고 훑어보게 한다.
  const [previewId, setPreviewId] = useState<string | null>(null);
  const preview = items.find((item) => item.interviewId === previewId);
  const sheetSide = window.matchMedia('(min-width: 1024px)').matches ? 'right' : 'bottom';

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-8 pb-10 sm:px-6 lg:px-10 lg:pt-10">
      <header>
        <h1 className="text-ink text-[26px] font-bold tracking-tight">지원자</h1>
        <p className="text-ink-muted mt-1.5 text-[15px]">
          내가 만든 면접입니다. 점수와 순위는 매기지 않습니다 — 판단은 면접관이 합니다.
        </p>
      </header>

      {isLoading && (
        <div className="mt-8 flex flex-col gap-2">
          <Skeleton className="h-11 w-80" />
          <Skeleton className="mt-3 h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}

      {isError && (
        <div role="alert" className="text-ink-muted mt-8 text-[15px]">
          <p>지원자 목록을 불러오지 못했습니다.</p>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="text-brand mt-2 font-semibold disabled:opacity-50"
          >
            다시 시도
          </button>
        </div>
      )}

      {/*
        조회가 한 번 성공한 뒤 재조회가 실패하면 v5 는 앞의 data 를 그대로 들고 있다.
        그러면 오류 배너와 「아직 만든 면접이 없습니다」가 같이 떠서 서로 다른 말을 한다.
      */}
      {data && !isError && items.length === 0 && (
        <Card className="mt-8">
          <EmptyState
            image={emptyInterviews}
            title="아직 만든 면접이 없습니다"
            description="면접을 만들면 여기에 쌓입니다."
            action={
              <Link to="/interviews/new" className={buttonClass('primary')}>
                면접 만들기
              </Link>
            }
          />
        </Card>
      )}

      {items.length > 0 && (
        <>
          <div className="mt-7 flex flex-col gap-3 lg:flex-row lg:items-center">
            {/* 상태 탭 — 숫자는 검색까지 적용한 결과를 센다 */}
            <div
              role="group"
              aria-label="검토 상태"
              className="bg-surface-bright flex gap-1 overflow-x-auto rounded-xl p-1"
            >
              {FILTERS.map((item) => {
                const on = filter === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setFilter(item.id)}
                    aria-pressed={on}
                    className={`flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-2 text-[13px] font-semibold transition sm:gap-1.5 sm:px-3.5 sm:text-[14px] ${
                      on ? 'bg-surface-panel text-ink shadow-card' : 'text-ink-muted hover:text-ink'
                    }`}
                  >
                    {item.label}
                    <span
                      className={`rounded-full px-1.5 text-[12px] tabular-nums ${on ? 'bg-brand-tint text-brand-strong' : 'text-ink-dim'}`}
                    >
                      {countFor(item.id)}
                    </span>
                  </button>
                );
              })}
            </div>
            <span className="flex-1" />
            <div className="flex gap-2">
              <label className="relative min-w-0 flex-1 lg:w-60 lg:flex-none">
                <span className="sr-only">지원자 이름 검색</span>
                <span
                  aria-hidden
                  className="material-symbols-outlined text-ink-dim pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-[20px]"
                >
                  search
                </span>
                <input
                  id="candidate-search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="이름 검색"
                  className={`${FIELD} w-full pl-10`}
                />
              </label>
              <label className="shrink-0">
                <span className="sr-only">정렬</span>
                <select
                  id="candidate-sort"
                  value={sort}
                  onChange={(event) => setSort(event.target.value as Sort)}
                  className={`${FIELD} pr-8`}
                >
                  <option value="recent">최신순</option>
                  <option value="name">이름순</option>
                  <option value="needsReview">확인 필요 많은순</option>
                </select>
              </label>
            </div>
          </div>

          <div className="border-border-base bg-surface-panel shadow-card mt-4 overflow-hidden rounded-2xl border">
            {/* 넓은 화면 — 표 머리 */}
            <div className="border-border-base text-ink-dim hidden grid-cols-[minmax(0,2fr)_110px_minmax(0,1.3fr)_minmax(0,1.6fr)_80px_24px] gap-4 border-b px-5 py-3 text-[13px] font-medium md:grid">
              <span>지원자</span>
              <span>검토 상태</span>
              <span>면접</span>
              <span>확인 항목 · 확인 필요 · 근거 채택</span>
              <span>길이</span>
              <span />
            </div>
            <ul className="divide-border-base divide-y">
              {filtered.map((item) => {
                const reason = pendingReason(item);
                const duration = durationLabel(item.durationSec);
                const name = item.candidateName ?? UNNAMED;
                return (
                  <li key={item.interviewId}>
                    <button
                      type="button"
                      onClick={() => setPreviewId(item.interviewId)}
                      className="hover:bg-surface-container grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 px-5 py-4 text-left transition-colors md:grid-cols-[minmax(0,2fr)_110px_minmax(0,1.3fr)_minmax(0,1.6fr)_80px_24px]"
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className="bg-brand-tint text-brand flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[14px] font-bold">
                          {name.slice(0, 1)}
                        </span>
                        <span className="min-w-0">
                          <span className="text-ink block truncate text-[15px] font-semibold">
                            {name}
                          </span>
                          {item.role && (
                            <span className="text-ink-dim block truncate text-[13px]">
                              {item.role}
                            </span>
                          )}
                        </span>
                      </span>
                      <span>
                        <Badge tone={STATUS_TONE[item.reviewStatus]}>
                          {STATUS_LABEL[item.reviewStatus]}
                        </Badge>
                      </span>
                      <span className="text-ink-muted col-span-2 truncate pl-12 text-[13px] md:col-span-1 md:pl-0 md:text-[14px]">
                        {item.interviewedAt ? dateLabel(item.interviewedAt) : '아직 진행 전'}
                      </span>
                      <span className="text-ink-muted col-span-2 pl-12 text-[13px] md:col-span-1 md:pl-0 md:text-[14px]">
                        {reason ?? (
                          // 넓은 화면은 표 머리가 이름을 대신 말한다. 좁은 화면에서만 이름을 붙인다.
                          <span className="tabular-nums">
                            <span className="md:hidden">역량 </span>
                            {item.counts!.coverageConfirmed}/{item.counts!.coverageTotal} ·{' '}
                            <span className="md:hidden">확인 필요 </span>
                            <span
                              className={
                                item.counts!.needsReview > 0 ? 'text-warning font-semibold' : ''
                              }
                            >
                              {item.counts!.needsReview}건
                            </span>{' '}
                            · <span className="md:hidden">채택 </span>
                            {item.counts!.adopted}/{item.counts!.findings}
                          </span>
                        )}
                      </span>
                      <span className="text-ink-muted hidden text-[14px] tabular-nums md:block">
                        {duration ?? '—'}
                      </span>
                      {/* Google Fonts 의 아이콘 CSS 가 레이어 밖에서 inline-block 을 줘서 아이콘에 직접
                          hidden 을 걸면 지지 않는다. 숨기는 일은 감싸개가 한다. */}
                      <span aria-hidden className="text-ink-dim hidden md:block">
                        <span className="material-symbols-outlined text-[20px]">chevron_right</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {filtered.length === 0 && (
              <p className="text-ink-muted p-10 text-center text-[15px]">
                조건에 맞는 지원자가 없습니다.
              </p>
            )}
          </div>
        </>
      )}

      <Sheet
        open={Boolean(preview)}
        onClose={() => setPreviewId(null)}
        title="지원자 미리보기"
        side={sheetSide}
      >
        {preview && <Preview item={preview} onDeleted={() => setPreviewId(null)} />}
      </Sheet>
    </div>
  );
}

/** 입력 칸 · 고르기 칸 공통 모양 */
const FIELD =
  'h-11 rounded-xl border border-border-input bg-surface-input px-3.5 text-[14px] text-ink placeholder:text-ink-dim outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/20';

/** 시트 안 — 한 사람의 요약과 면접 기록으로 가는 길 */
function Preview({ item, onDeleted }: { item: InterviewListItem; onDeleted: () => void }) {
  const reason = pendingReason(item);
  const duration = durationLabel(item.durationSec);
  const name = item.candidateName ?? UNNAMED;
  return (
    <>
      <div className="flex items-center gap-3">
        <span className="bg-brand-tint text-brand flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-[18px] font-bold">
          {name.slice(0, 1)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-ink truncate text-[18px] font-bold">{name}</p>
          <p className="text-ink-dim truncate text-[14px]">{item.role || '직무 미입력'}</p>
        </div>
        <Badge tone={STATUS_TONE[item.reviewStatus]}>{STATUS_LABEL[item.reviewStatus]}</Badge>
      </div>

      <dl className="border-border-base mt-6 grid grid-cols-2 gap-4 border-t pt-5 text-[14px]">
        <Fact
          label="면접 일시"
          value={item.interviewedAt ? dateLabel(item.interviewedAt) : '아직 진행 전'}
        />
        <Fact label="면접 길이" value={duration ?? '—'} />
        <Fact label="면접관" value={item.interviewer.nickname} />
      </dl>

      <div className="bg-surface-container mt-6 rounded-2xl p-4">
        <p className="text-ink text-[14px] font-semibold">AI 검토 항목</p>
        {reason ? (
          <p className="text-ink-muted mt-2 text-[14px]">{reason}</p>
        ) : (
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Count
              label="확인된 역량"
              value={`${item.counts!.coverageConfirmed}/${item.counts!.coverageTotal}`}
            />
            <Count
              label="확인 필요"
              value={`${item.counts!.needsReview}건`}
              warn={item.counts!.needsReview > 0}
            />
            <Count label="근거 채택" value={`${item.counts!.adopted}/${item.counts!.findings}`} />
          </dl>
        )}
      </div>

      {/* 아직 지원자 상세 화면이 없다. 면접 기록이 가장 가까운 다음 화면이다. */}
      <Link
        to={`/review/${item.interviewId}`}
        className={`${buttonClass('primary', 'lg')} mt-6 w-full`}
      >
        면접 기록 열기
        <span aria-hidden className="material-symbols-outlined text-[20px]">
          arrow_forward
        </span>
      </Link>

      <DeleteInterviewButton
        interviewId={item.interviewId}
        candidateName={name}
        size="lg"
        className="mt-2 w-full"
        // 지운 면접의 미리보기는 닫는다. 목록을 다시 받으면 그 줄이 없다.
        onDeleted={onDeleted}
      />
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-ink-dim text-[12px]">{label}</dt>
      <dd className="text-ink mt-0.5 truncate font-medium">{value}</dd>
    </div>
  );
}

function Count({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="bg-surface-panel rounded-xl px-2 py-3">
      <dd className={`text-[18px] font-bold tabular-nums ${warn ? 'text-warning' : 'text-ink'}`}>
        {value}
      </dd>
      <dt className="text-ink-dim mt-0.5 text-[12px]">{label}</dt>
    </div>
  );
}
