import { useQuery } from '@tanstack/react-query';
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { InterviewComparison } from '../components/review/InterviewComparison';
import { InterviewWorkspacePanel } from '../components/review/InterviewWorkspacePanel';
import { listInterviews } from '../api/interview';
import { Badge } from '../components/ui/Badge';
import { buttonClass } from '../components/ui/buttonClass';
import { Skeleton } from '../components/ui/Skeleton';
import {
  candidateRows,
  delimitedCell,
  rangeSelection,
  saveDownload,
  type SortKey,
  type SortRule,
} from '../lib/candidateManagement';
import { durationLabel, pendingReason, STATUS_LABEL, STATUS_TONE } from '../lib/interviewList';
import type { InterviewListItem, ReviewStatus } from '../types/interview';

const PAGE_SIZE = 50;
const COLUMNS = [
  { key: 'name', title: '지원자', width: 190 },
  { key: 'review', title: '검토 상태', width: 105 },
  { key: 'date', title: '면접', width: 155 },
  { key: 'coverage', title: '확인한 항목', width: 115 },
  { key: 'needsReview', title: '확인할 내용', width: 110 },
  { key: 'adopted', title: '리포트 반영', width: 110 },
  { key: 'memo', title: '메모', width: 185 },
  { key: 'report', title: '리포트', width: 100 },
  { key: 'actions', title: '작업', width: 100 },
] as const;
type ColumnKey = (typeof COLUMNS)[number]['key'];
const SORTABLE = new Set<string>(['name', 'date', 'needsReview', 'adopted']);
const REPORT_LABEL = { PROCESSING: '생성 중', READY: '완료', FAILED: '실패' };
const FIELD =
  'border-border-input bg-surface-input text-ink focus:ring-brand min-h-10 rounded-lg border px-3 text-sm focus:ring-2';
const dateLabel = (value: string | null) =>
  value
    ? new Date(value).toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '면접 전';

export default function InterviewListPage() {
  const [params, setParams] = useSearchParams();
  const query = useQuery({
    queryKey: ['interviews'],
    queryFn: listInterviews,
    refetchInterval: (q) =>
      q.state.data?.items.some(
        (item) =>
          item.summaryStatus === 'PROCESSING' ||
          item.reportStatus === 'PROCESSING' ||
          item.latestSession?.status === 'INTERVIEWING',
      )
        ? 3000
        : false,
  });
  const expanded = params.get('interview');
  const [sort, setSort] = useState<SortRule[]>([]);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [comparing, setComparing] = useState<[string, string] | null>(null);
  const [columnOrder, setColumnOrder] = useState<ColumnKey[]>(COLUMNS.map((column) => column.key));
  const [hidden, setHidden] = useState<Set<ColumnKey>>(new Set());
  const [widths, setWidths] = useState<Record<string, number>>(
    Object.fromEntries(COLUMNS.map((column) => [column.key, column.width])),
  );
  const [settings, setSettings] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [copyText, setCopyText] = useState<string | null>(null);
  const [exportRange, setExportRange] = useState('filtered');
  const [exportProgress, setExportProgress] = useState<string | null>(null);
  const anchor = useRef<string | null>(null);
  const resizeCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => resizeCleanup.current?.(), []);
  const search = params.get('q') ?? '';
  const statusParam = params.get('status') ?? 'all';
  const review: 'all' | ReviewStatus = ['PENDING', 'IN_REVIEW', 'CONFIRMED'].includes(statusParam)
    ? (statusParam as ReviewStatus)
    : 'all';
  const summary = params.get('summary') ?? 'all';
  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const filtered = useMemo(
    () => candidateRows(items, { search, review, summary }, sort),
    [items, search, review, summary, sort],
  );
  const searched = useMemo(
    () => candidateRows(items, { search, review: 'all', summary }, []),
    [items, search, summary],
  );
  const visibleColumns = columnOrder
    .filter((key) => !hidden.has(key))
    .map((key) => COLUMNS.find((column) => column.key === key)!);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const selected = items.filter((item) => selection.has(item.interviewId));
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (!value || value === 'all') next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
    setPage(0);
  };
  const selectOne = (id: string, shift: boolean) => {
    const checked = !selection.has(id);
    setSelection(
      shift
        ? rangeSelection(
            filtered.map((item) => item.interviewId),
            anchor.current,
            id,
            selection,
            checked,
          )
        : rangeSelection([id], null, id, selection, checked),
    );
    anchor.current = id;
  };
  const changeSort = (key: SortKey, multi: boolean) =>
    setSort((old) => {
      const previous = old.find((rule) => rule.key === key);
      const rest = multi ? old.filter((rule) => rule.key !== key) : [];
      return previous?.descending === false ? rest : [...rest, { key, descending: !previous }];
    });
  const moveColumn = (key: ColumnKey, delta: number) =>
    setColumnOrder((old) => {
      const next = [...old];
      const from = next.indexOf(key);
      const to = from + delta;
      if (key === 'name' || to <= 0 || to >= next.length) return old;
      [next[from], next[to]] = [next[to], next[from]];
      return next;
    });
  const resize = (key: ColumnKey, clientX: number) => {
    resizeCleanup.current?.();
    const width = widths[key];
    const move = (event: PointerEvent) =>
      setWidths((old) => ({
        ...old,
        [key]: Math.max(88, Math.min(480, width + event.clientX - clientX)),
      }));
    const end = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
      document.removeEventListener('pointercancel', end);
      resizeCleanup.current = null;
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', end);
    document.addEventListener('pointercancel', end);
    resizeCleanup.current = end;
  };
  const openId = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) {
      next.set('interview', id);
      const index = filtered.findIndex((item) => item.interviewId === id);
      if (index >= 0) setPage(Math.floor(index / PAGE_SIZE));
    } else next.delete('interview');
    setParams(next, { replace: true });
  };
  const open = (item: InterviewListItem) =>
    openId(expanded === item.interviewId ? null : item.interviewId);

  const value = (item: InterviewListItem, key: ColumnKey): string => {
    const counts = item.counts;
    if (key === 'name') return item.candidateName || '이름 없는 지원자';
    if (key === 'review') return STATUS_LABEL[item.reviewStatus];
    if (key === 'date')
      return `${dateLabel(item.interviewedAt)}${item.durationSec === null ? '' : ` · ${durationLabel(item.durationSec)}`}`;
    if (key === 'coverage')
      return item.findingsStatus === 'FAILED'
        ? '확인 불가'
        : counts
          ? `${counts.coverageConfirmed}/${counts.coverageTotal}`
          : (pendingReason(item) ?? '—');
    if (key === 'needsReview')
      return item.findingsStatus === 'FAILED'
        ? '정리 실패'
        : counts
          ? `${counts.needsReview}건`
          : '—';
    if (key === 'adopted') return counts ? `${counts.adopted}/${counts.findings}` : '—';
    if (key === 'memo') return item.memo ?? '조회 필요';
    if (key === 'report')
      return item.reportStatus
        ? REPORT_LABEL[item.reportStatus]
        : item.reportStatus === null
          ? '미생성'
          : '조회 필요';
    return '';
  };
  const textTable = (rows: InterviewListItem[], delimiter: string) =>
    [
      visibleColumns
        .filter((column) => column.key !== 'actions')
        .map((column) => delimitedCell(column.title, delimiter))
        .join(delimiter),
      ...rows.map((item) =>
        visibleColumns
          .filter((column) => column.key !== 'actions')
          .map((column) => delimitedCell(value(item, column.key), delimiter))
          .join(delimiter),
      ),
    ].join('\r\n');
  const copy = async () => {
    const text = textTable(selected, '\t');
    try {
      await navigator.clipboard.writeText(text);
      setNotice(`${selected.length}건을 복사했습니다.`);
    } catch {
      setCopyText(text);
    }
  };
  const exportRows =
    exportRange === 'all' ? items : exportRange === 'selected' ? selected : filtered;
  const exportXlsx = async () => {
    setExportProgress('자료 확인 중');
    setNotice(null);
    try {
      const { candidateExport } = await import('../lib/candidateExport');
      const blob = await candidateExport(exportRows, (done, total) =>
        setExportProgress(`${done}/${total}건 확인`),
      );
      saveDownload(blob, 'IRYA_면접기록.xlsx');
      setNotice(`${exportRows.length}건을 내보냈습니다.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '내보내기에 실패했습니다.');
    } finally {
      setExportProgress(null);
    }
  };
  const cell = (item: InterviewListItem, key: ColumnKey): ReactNode => {
    if (key === 'name')
      return (
        <button
          type="button"
          onClick={() => open(item)}
          className="text-ink flex w-full items-center gap-2 text-left font-semibold"
        >
          <span className="bg-brand-tint text-brand flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
            {(item.candidateName || '?').slice(0, 1)}
          </span>
          <span className="truncate">{value(item, key)}</span>
        </button>
      );
    if (key === 'review')
      return <Badge tone={STATUS_TONE[item.reviewStatus]}>{value(item, key)}</Badge>;
    if (key === 'memo')
      return (
        <button
          type="button"
          onClick={() => open(item)}
          className="text-ink-muted w-full truncate text-left"
          title={item.memo || undefined}
        >
          {item.memo || '메모 작성'}
        </button>
      );
    if (key === 'actions')
      return (
        <button
          type="button"
          onClick={() => open(item)}
          className="border-border-base text-brand min-h-10 rounded-lg border px-3 text-xs"
        >
          확인
        </button>
      );
    return (
      <span
        className={
          key === 'needsReview' && (item.counts?.needsReview ?? 0) > 0
            ? 'text-warning font-semibold'
            : 'text-ink-muted'
        }
      >
        {value(item, key)}
      </span>
    );
  };
  return (
    <div className="mx-auto w-full max-w-[1800px] px-4 py-7 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-ink text-[26px] font-bold">지원자 관리</h1>
          <p className="text-ink-muted mt-1.5 text-sm">내가 만든 면접을 확인하고 처리합니다.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setSettings((old) => !old)}
            aria-expanded={settings}
            className={buttonClass('secondary')}
          >
            열 표시·순서
          </button>
          <select
            aria-label="내보낼 범위"
            className={FIELD}
            value={exportRange}
            onChange={(event) => setExportRange(event.target.value)}
          >
            <option value="filtered">필터 결과 {filtered.length}건</option>
            <option value="all">전체 {items.length}건</option>
            <option value="selected" disabled={!selected.length}>
              선택 {selected.length}건
            </option>
          </select>
          <button
            type="button"
            disabled={!exportRows.length}
            onClick={() =>
              saveDownload(
                new Blob(['\uFEFF', textTable(exportRows, ',')], {
                  type: 'text/csv;charset=utf-8',
                }),
                'IRYA_면접목록.csv',
              )
            }
            className={buttonClass('secondary')}
          >
            CSV 내보내기
          </button>
          <button
            type="button"
            disabled={!exportRows.length || exportProgress !== null}
            onClick={() => void exportXlsx()}
            className={buttonClass('primary')}
          >
            {exportProgress ?? 'XLSX 내보내기'}
          </button>
        </div>
      </header>
      {settings && (
        <section
          aria-label="표 열 설정"
          className="border-border-base bg-surface-panel mt-4 grid gap-2 rounded-xl border p-4 sm:grid-cols-3"
        >
          {columnOrder.map((key) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <label className="text-ink flex flex-1 items-center gap-2">
                <input
                  type="checkbox"
                  disabled={key === 'name'}
                  checked={!hidden.has(key)}
                  onChange={() =>
                    setHidden((old) => {
                      const next = new Set(old);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      return next;
                    })
                  }
                />
                {COLUMNS.find((column) => column.key === key)!.title}
              </label>
              {key !== 'name' && (
                <>
                  <button
                    type="button"
                    aria-label={`${key} 열 왼쪽으로`}
                    onClick={() => moveColumn(key, -1)}
                    className="text-brand p-2"
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    aria-label={`${key} 열 오른쪽으로`}
                    onClick={() => moveColumn(key, 1)}
                    className="text-brand p-2"
                  >
                    →
                  </button>
                </>
              )}
            </div>
          ))}
        </section>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="검토 상태"
          className="bg-surface-bright flex flex-wrap gap-1 rounded-xl p-1"
        >
          {(['all', 'PENDING', 'IN_REVIEW', 'CONFIRMED'] as const).map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={review === status}
              onClick={() => setFilter('status', status)}
              className={`rounded-lg px-3 py-2 text-sm ${review === status ? 'bg-surface-panel text-ink shadow-card font-semibold' : 'text-ink-muted'}`}
            >
              {status === 'all' ? '전체' : STATUS_LABEL[status]}{' '}
              {status === 'all'
                ? searched.length
                : searched.filter((item) => item.reviewStatus === status).length}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            aria-label="지원자 이름 검색"
            placeholder="이름 검색"
            className={FIELD}
            value={search}
            onChange={(event) => setFilter('q', event.target.value)}
          />
          <select
            aria-label="정리 상태"
            className={FIELD}
            value={summary}
            onChange={(event) => setFilter('summary', event.target.value)}
          >
            <option value="all">정리 상태 전체</option>
            <option value="PROCESSING">정리 중</option>
            <option value="READY">정리 완료</option>
            <option value="FAILED">정리 실패</option>
          </select>
          <button
            type="button"
            onClick={() => {
              setParams({});
              setSort([]);
              setPage(0);
            }}
            className={buttonClass('secondary')}
          >
            초기화
          </button>
        </div>
      </div>
      <p className="text-ink-dim mt-3 text-xs">
        Shift로 여러 행 선택 · 열 제목으로 정렬 · Shift+열 제목으로 다중 정렬
      </p>
      {selected.length > 0 && (
        <div className="border-brand/20 bg-brand-tint text-brand-strong mt-3 flex flex-wrap items-center gap-3 rounded-xl border p-3 text-sm">
          <strong>{selected.length}건 선택</strong>
          <button
            type="button"
            disabled={selected.length !== 2}
            onClick={() => {
              if (selected.length === 2)
                setComparing([selected[0].interviewId, selected[1].interviewId]);
            }}
            className="rounded px-2 py-1 underline disabled:opacity-40"
          >
            나란히 비교
          </button>
          <button type="button" onClick={() => void copy()} className="rounded px-2 py-1 underline">
            선택 행 복사
          </button>
          <button
            type="button"
            onClick={() => setSelection(new Set(filtered.map((item) => item.interviewId)))}
            className="rounded px-2 py-1 underline"
          >
            검색 결과 {filtered.length}건 모두 선택
          </button>
          <button
            type="button"
            onClick={() => setSelection(new Set())}
            className="rounded px-2 py-1 underline"
          >
            선택 취소
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="text-ink-muted mt-3 text-sm">
          {notice}
        </p>
      )}
      {copyText !== null && (
        <div className="mt-3">
          <label className="text-ink text-sm">
            자동 복사를 사용할 수 없습니다. 아래 내용을 직접 복사해 주세요.
            <textarea
              readOnly
              value={copyText}
              onFocus={(event) => event.currentTarget.select()}
              className={`${FIELD} mt-2 block w-full p-3`}
            />
          </label>
          <button
            type="button"
            onClick={() => setCopyText(null)}
            className="text-brand mt-2 text-sm underline"
          >
            닫기
          </button>
        </div>
      )}
      {query.isLoading && <Skeleton className="mt-5 h-64" />}
      {query.isError && (
        <div role="alert" className="text-danger mt-5 text-sm">
          목록을 불러오지 못했습니다.{' '}
          <button type="button" onClick={() => void query.refetch()} className="underline">
            다시 확인
          </button>
        </div>
      )}
      {comparing && <InterviewComparison ids={comparing} onBack={() => setComparing(null)} />}
      {query.data && !query.isError && !comparing && (
        <div className="border-border-base bg-surface-panel shadow-card mt-4 overflow-hidden rounded-2xl border">
          <div className="max-h-[70dvh] overflow-auto">
            <table
              className="w-full table-fixed border-separate border-spacing-0 text-left text-sm"
              style={{
                minWidth:
                  44 + visibleColumns.reduce((total, column) => total + widths[column.key], 0),
              }}
            >
              <colgroup>
                <col style={{ width: 44 }} />
                {visibleColumns.map((column) => (
                  <col key={column.key} style={{ width: widths[column.key] }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th className="border-border-base bg-surface-container sticky top-0 left-0 z-30 border-b p-3">
                    <input
                      type="checkbox"
                      aria-label="현재 페이지 선택"
                      checked={
                        pageItems.length > 0 &&
                        pageItems.every((item) => selection.has(item.interviewId))
                      }
                      onChange={(event) =>
                        setSelection((old) => {
                          const next = new Set(old);
                          for (const item of pageItems) {
                            if (event.target.checked) next.add(item.interviewId);
                            else next.delete(item.interviewId);
                          }
                          return next;
                        })
                      }
                    />
                  </th>
                  {visibleColumns.map((column) => (
                    <th
                      key={column.key}
                      className={`border-border-base bg-surface-container sticky top-0 z-20 border-b px-3 py-3 text-xs font-medium ${column.key === 'name' ? 'left-11 z-30' : ''}`}
                      aria-sort={
                        sort[0]?.key === column.key
                          ? sort[0].descending
                            ? 'descending'
                            : 'ascending'
                          : undefined
                      }
                    >
                      <div className="flex items-center gap-1">
                        {SORTABLE.has(column.key) ? (
                          <button
                            type="button"
                            onClick={(event) => changeSort(column.key as SortKey, event.shiftKey)}
                            className="text-ink-muted min-h-9 flex-1 text-left"
                          >
                            {column.title}
                            {sort.some((rule) => rule.key === column.key)
                              ? sort.find((rule) => rule.key === column.key)!.descending
                                ? ' ↓'
                                : ' ↑'
                              : ''}
                          </button>
                        ) : (
                          <span className="text-ink-muted flex-1">{column.title}</span>
                        )}
                        <span
                          role="separator"
                          aria-label={`${column.title} 열 너비`}
                          aria-orientation="vertical"
                          aria-valuemin={88}
                          aria-valuemax={480}
                          aria-valuenow={widths[column.key]}
                          tabIndex={0}
                          onPointerDown={(event) => {
                            event.preventDefault();
                            resize(column.key, event.clientX);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                              event.preventDefault();
                              setWidths((old) => ({
                                ...old,
                                [column.key]: Math.max(
                                  88,
                                  Math.min(
                                    480,
                                    old[column.key] + (event.key === 'ArrowRight' ? 16 : -16),
                                  ),
                                ),
                              }));
                            }
                          }}
                          className="border-border-input h-7 w-2 cursor-col-resize border-r"
                        />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageItems.map((item) => (
                  <Fragment key={item.interviewId}>
                    <tr
                      key={item.interviewId}
                      className={selection.has(item.interviewId) ? 'bg-brand-tint' : ''}
                    >
                      <td
                        className={`border-border-base sticky left-0 z-10 border-b p-3 ${selection.has(item.interviewId) ? 'bg-brand-tint' : 'bg-surface-panel'}`}
                      >
                        <input
                          type="checkbox"
                          aria-label={`${item.candidateName || '이름 없는 지원자'} 선택`}
                          readOnly
                          checked={selection.has(item.interviewId)}
                          onClick={(event) => selectOne(item.interviewId, event.shiftKey)}
                        />
                      </td>
                      {visibleColumns.map((column) => (
                        <td
                          key={column.key}
                          className={`border-border-base border-b px-3 py-3 ${column.key === 'name' ? `sticky left-11 z-10 ${selection.has(item.interviewId) ? 'bg-brand-tint' : 'bg-surface-panel'}` : ''}`}
                        >
                          {cell(item, column.key)}
                        </td>
                      ))}
                    </tr>
                    {expanded === item.interviewId && (
                      <tr>
                        <td colSpan={visibleColumns.length + 1}>
                          <InterviewWorkspacePanel
                            key={item.interviewId}
                            interviewId={item.interviewId}
                            onClose={() => openId(null)}
                            onPrevious={
                              filtered.findIndex(
                                (entry) => entry.interviewId === item.interviewId,
                              ) > 0
                                ? () =>
                                    openId(
                                      filtered[
                                        filtered.findIndex(
                                          (entry) => entry.interviewId === item.interviewId,
                                        ) - 1
                                      ].interviewId,
                                    )
                                : undefined
                            }
                            onNext={
                              filtered.findIndex(
                                (entry) => entry.interviewId === item.interviewId,
                              ) +
                                1 <
                              filtered.length
                                ? () =>
                                    openId(
                                      filtered[
                                        filtered.findIndex(
                                          (entry) => entry.interviewId === item.interviewId,
                                        ) + 1
                                      ].interviewId,
                                    )
                                : undefined
                            }
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <p className="text-ink-muted p-10 text-center">
                {items.length ? '조건에 맞는 지원자가 없습니다.' : '아직 만든 면접이 없습니다.'}{' '}
                <Link to="/interviews/new" className="text-brand underline">
                  면접 만들기
                </Link>
              </p>
            )}
          </div>
          <div className="text-ink-muted flex flex-wrap items-center justify-between gap-3 p-3 text-xs">
            <span>
              {filtered.length}건 · {currentPage + 1}/{pageCount}페이지
            </span>
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={currentPage === 0}
                onClick={() => setPage(currentPage - 1)}
                className="min-h-10 px-3 disabled:opacity-40"
              >
                이전
              </button>
              <button
                type="button"
                disabled={currentPage + 1 >= pageCount}
                onClick={() => setPage(currentPage + 1)}
                className="min-h-10 px-3 disabled:opacity-40"
              >
                다음
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
