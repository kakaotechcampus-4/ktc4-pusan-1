import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { InterviewerHeader } from '../components/layout/InterviewerHeader';
import { loadDemoCandidates, type CandidateStatus, type DemoCandidate } from '../lib/demoReview';

type Filter = 'all' | CandidateStatus | 'uncertain';
type Column =
  'candidate' | 'status' | 'interview' | 'coverage' | 'findings' | 'adopted' | 'duration';
type Sort = 'recent' | 'name' | 'findings';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: '대기', label: '검토 대기' },
  { id: '검토 중', label: '검토 중' },
  { id: '확정', label: '확정' },
  { id: 'uncertain', label: '전사 확인 필요' },
];

const COLUMNS: { id: Column; label: string }[] = [
  { id: 'candidate', label: '지원자' },
  { id: 'status', label: '검토 상태' },
  { id: 'interview', label: '면접' },
  { id: 'coverage', label: '확인 항목' },
  { id: 'findings', label: '확인 필요' },
  { id: 'adopted', label: '근거 채택' },
  { id: 'duration', label: '답변 분량' },
];

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function counts(candidate: DemoCandidate) {
  return {
    adopted: candidate.findings.filter((finding) => finding.state === 'adopted').length,
    needsReview: candidate.findings.filter((finding) => finding.state === 'unreviewed').length,
    uncertain: candidate.findings.filter((finding) => finding.uncertain).length,
  };
}

function exportRows(candidates: DemoCandidate[]) {
  const rows = [
    ['지원자', '직무', '검토 상태', '면접 일시', '확인 항목', '확인 필요', '근거 채택'],
    ...candidates.map((candidate) => {
      const state = counts(candidate);
      return [
        candidate.name,
        candidate.role,
        candidate.status,
        dateLabel(candidate.interviewAt),
        `${candidate.coverage.filter((item) => item.state === 'confirmed').length}/${candidate.coverage.length}`,
        String(state.needsReview),
        String(state.adopted),
      ];
    }),
  ];
  const csv = rows
    .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(','))
    .join('\r\n');
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '샘플-지원자-검토.csv';
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function CandidateListPage({ demo = false }: { demo?: boolean }) {
  const [candidates] = useState<DemoCandidate[]>(() => (demo ? loadDemoCandidates() : []));
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  const [visibleColumns, setVisibleColumns] = useState<Set<Column>>(
    () => new Set(COLUMNS.map((column) => column.id)),
  );
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [notice, setNotice] = useState('');

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ko-KR');
    const result = candidates.filter((candidate) => {
      const state = counts(candidate);
      const matchesFilter =
        filter === 'all' ||
        (filter === 'uncertain' ? state.uncertain > 0 : candidate.status === filter);
      const matchesSearch =
        !query || `${candidate.name} ${candidate.role}`.toLocaleLowerCase('ko-KR').includes(query);
      return matchesFilter && matchesSearch;
    });

    return result.sort((left, right) => {
      if (sort === 'name') return left.name.localeCompare(right.name, 'ko-KR');
      if (sort === 'findings') return counts(right).needsReview - counts(left).needsReview;
      return right.interviewAt.localeCompare(left.interviewAt);
    });
  }, [candidates, filter, search, sort]);

  const selectedCandidates = candidates.filter((candidate) => selected.includes(candidate.id));
  const visible = (column: Column) => visibleColumns.has(column);
  const toggleColumn = (column: Column) => {
    setVisibleColumns((current) => {
      const next = new Set(current);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });
  };

  const toggleSelected = (id: string) => {
    if (selected.includes(id)) {
      setSelected(selected.filter((value) => value !== id));
      return;
    }
    if (selected.length >= 3) {
      setNotice('한 번에 세 명까지 비교할 수 있습니다.');
      return;
    }
    setNotice('');
    setSelected([...selected, id]);
  };

  if (!demo) {
    return (
      <div className="min-h-full bg-[#121316] text-[#eaecef]">
        <InterviewerHeader />
        <main className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:px-8">
          <p className="font-mono text-xs text-[#686c7b]">지원자 검토</p>
          <h1 className="mt-2 text-2xl font-bold">지원자 목록</h1>
          <section className="mt-8 rounded-lg border border-[#272a33] bg-[#18191f] p-6">
            <h2 className="text-sm font-semibold">목록 API가 아직 연결되지 않았습니다</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#9498a4]">
              실제 지원자 자료를 불러올 수 없어 이 화면에는 표시하지 않습니다. 화면 동작은 가공
              샘플로 확인할 수 있습니다.
            </p>
            <Link
              to="/demo/candidates"
              className="mt-5 inline-flex rounded border border-[#3f4452] bg-[#202229] px-3 py-2 text-xs font-semibold text-[#eaecef] hover:bg-[#282b34]"
            >
              샘플 검토 화면 열기
            </Link>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-[#121316] text-[#eaecef]">
      <InterviewerHeader demo />
      <main className="mx-auto max-w-[1440px] px-4 py-7 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[#272a33] pb-5">
          <div>
            <p className="font-mono text-xs text-[#686c7b]">채용 검토 · 샘플 회차</p>
            <h1 className="mt-1 text-xl font-bold sm:text-2xl">백엔드 개발자 · 2026 상반기</h1>
            <p className="mt-2 text-xs text-[#9498a4]">
              {candidates.length}명 · 근거와 면접 기록을 검토합니다. 점수와 순위는 제공하지
              않습니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setColumnsOpen((open) => !open)}
              aria-expanded={columnsOpen}
              className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
            >
              열 설정
            </button>
            <button
              type="button"
              onClick={() => exportRows(filtered)}
              className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
            >
              CSV 내보내기
            </button>
            <Link
              to="/demo/candidates/candidate-kim/memo"
              className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
            >
              샘플 메모 화면
            </Link>
          </div>
        </header>

        {columnsOpen && (
          <section
            aria-label="표시할 열"
            className="mt-3 rounded-lg border border-[#272a33] bg-[#18191f] p-3"
          >
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {COLUMNS.filter((column) => column.id !== 'candidate').map((column) => (
                <label key={column.id} className="flex items-center gap-2 text-xs text-[#c4c7c9]">
                  <input
                    type="checkbox"
                    checked={visible(column.id)}
                    onChange={() => toggleColumn(column.id)}
                    className="accent-[#f0f2f5]"
                  />
                  {column.label}
                </label>
              ))}
            </div>
          </section>
        )}

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
                <span className="ml-1.5 font-mono text-[10px]">
                  {item.id === 'all'
                    ? candidates.length
                    : item.id === 'uncertain'
                      ? candidates.filter((candidate) => counts(candidate).uncertain > 0).length
                      : candidates.filter((candidate) => candidate.status === item.id).length}
                </span>
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="candidate-search">
              이름 또는 직무 검색
            </label>
            <input
              id="candidate-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="이름 또는 직무 검색"
              className="min-w-0 rounded border border-[#2e323c] bg-[#17191f] px-3 py-2 text-xs text-[#eaecef] placeholder:text-[#686c7b] sm:w-56"
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
              <option value="recent">면접 종료 최신순</option>
              <option value="name">이름순</option>
              <option value="findings">확인 필요 많은순</option>
            </select>
          </div>
        </section>

        <div
          className="mt-4 flex min-h-9 flex-wrap items-center gap-3 text-xs text-[#9498a4]"
          aria-live="polite"
        >
          <span>선택 {selected.length}명</span>
          <button
            type="button"
            disabled={selected.length < 2}
            onClick={() => setCompareOpen(true)}
            className="rounded border border-[#2e323c] bg-[#202229] px-3 py-1.5 text-[#c4c7c9] hover:bg-[#282b34] disabled:cursor-not-allowed disabled:opacity-40"
          >
            나란히 비교
          </button>
          {selected.length > 0 && (
            <button
              type="button"
              className="text-xs text-[#9498a4] underline"
              onClick={() => setSelected([])}
            >
              선택 해제
            </button>
          )}
          {notice && <span className="text-amber-300">{notice}</span>}
        </div>

        <div className="mt-2 overflow-x-auto rounded-lg border border-[#272a33] bg-[#15161b]">
          <table className="w-full min-w-[980px] border-collapse text-left text-xs">
            <thead className="bg-[#15161b] text-[#686c7b]">
              <tr className="border-b border-[#272a33]">
                <th className="w-10 px-3 py-3">
                  <span className="sr-only">비교 선택</span>
                </th>
                {COLUMNS.filter((column) => visible(column.id)).map((column) => (
                  <th
                    key={column.id}
                    scope="col"
                    className="px-3 py-3 font-medium whitespace-nowrap"
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((candidate) => {
                const state = counts(candidate);
                const coverage = candidate.coverage.filter(
                  (item) => item.state === 'confirmed',
                ).length;
                return (
                  <tr
                    key={candidate.id}
                    className="border-b border-[#22242c] last:border-0 hover:bg-white/[0.015]"
                  >
                    <td className="px-3 py-4">
                      <input
                        type="checkbox"
                        aria-label={`${candidate.name} 비교 선택`}
                        checked={selected.includes(candidate.id)}
                        onChange={() => toggleSelected(candidate.id)}
                        className="accent-[#eaecef]"
                      />
                    </td>
                    {visible('candidate') && (
                      <td className="px-3 py-4">
                        <Link
                          to={`/demo/candidates/${candidate.id}`}
                          className="block min-w-40 hover:text-white"
                        >
                          <span className="block font-semibold">{candidate.name}</span>
                          <span className="mt-1 block text-[10px] text-[#686c7b]">
                            {candidate.role} · 경력 {candidate.years}년
                          </span>
                        </Link>
                      </td>
                    )}
                    {visible('status') && (
                      <td className="px-3 py-4">
                        <span
                          className={`rounded border px-2 py-1 text-[10px] ${candidate.status === '대기' ? 'border-amber-500/50 bg-[#ffe082] font-bold text-[#212121]' : 'border-[#2e323c] bg-[#202229] text-[#c4c7c9]'}`}
                        >
                          {candidate.status}
                        </span>
                      </td>
                    )}
                    {visible('interview') && (
                      <td className="px-3 py-4 whitespace-nowrap">
                        <span className="block font-mono">{dateLabel(candidate.interviewAt)}</span>
                        <span className="mt-1 block text-[10px] text-[#686c7b]">
                          {candidate.interviewer}
                        </span>
                      </td>
                    )}
                    {visible('coverage') && (
                      <td className="px-3 py-4">
                        <span className="font-mono">
                          {coverage}/{candidate.coverage.length}
                        </span>
                        <span className="mt-1 block text-[10px] text-[#686c7b]">
                          확인 {coverage} · 일부{' '}
                          {candidate.coverage.filter((item) => item.state === 'partial').length} ·
                          미확인{' '}
                          {candidate.coverage.filter((item) => item.state === 'missing').length}
                        </span>
                      </td>
                    )}
                    {visible('findings') && (
                      <td className="px-3 py-4">
                        <span className="font-mono">{state.needsReview}건</span>
                        <span className="mt-1 block text-[10px] text-[#686c7b]">
                          불일치 · 미확인 · 전사 확인
                        </span>
                      </td>
                    )}
                    {visible('adopted') && (
                      <td className="px-3 py-4 font-mono">
                        {state.adopted}/{candidate.findings.length}
                      </td>
                    )}
                    {visible('duration') && (
                      <td className="px-3 py-4">
                        <span className="font-mono">
                          {Math.round(candidate.durationSec / 60)}분
                        </span>
                        <span className="mt-1 block text-[10px] text-[#686c7b]">
                          질문 {candidate.questions.length}개
                        </span>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <p className="p-8 text-center text-sm text-[#9498a4]">조건에 맞는 지원자가 없습니다.</p>
          )}
        </div>
        <p className="mt-3 text-[11px] leading-5 text-[#686c7b]">
          이 화면의 인물과 내용은 화면 동작 확인용 샘플입니다. 평가 점수나 지원자 순위는 만들지
          않습니다.
        </p>
      </main>

      {compareOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setCompareOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="compare-title"
            className="max-h-[85vh] w-full max-w-4xl overflow-auto rounded-lg border border-[#2e323c] bg-[#15161b] p-5 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="compare-title" className="text-base font-bold">
                  지원자 기록 비교
                </h2>
                <p className="mt-1 text-xs text-[#9498a4]">
                  판단은 면접관이 합니다. 두 사람의 근거와 확인 항목을 나란히 봅니다.
                </p>
              </div>
              <button
                type="button"
                aria-label="비교 닫기"
                onClick={() => setCompareOpen(false)}
                className="rounded border border-[#2e323c] px-2 py-1 text-xs text-[#c4c7c9] hover:bg-[#22242c]"
              >
                닫기
              </button>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {selectedCandidates.map((candidate) => (
                <article
                  key={candidate.id}
                  className="rounded-lg border border-[#272a33] bg-[#18191f] p-4"
                >
                  <h3 className="font-semibold">{candidate.name}</h3>
                  <p className="mt-1 text-xs text-[#9498a4]">
                    {candidate.role} · 경력 {candidate.years}년
                  </p>
                  <p className="mt-4 text-[11px] text-[#686c7b]">확인 항목</p>
                  <ul className="mt-2 space-y-2 text-xs">
                    {candidate.coverage.map((item) => (
                      <li key={item.name} className="flex items-center justify-between gap-2">
                        <span>{item.name}</span>
                        <span className="text-[#9498a4]">
                          {item.state === 'confirmed'
                            ? '확인'
                            : item.state === 'partial'
                              ? '일부'
                              : '미확인'}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-4 border-t border-[#272a33] pt-3 text-xs leading-5 text-[#c4c7c9]">
                    미검토 {counts(candidate).needsReview}건 · 채택 {counts(candidate).adopted}건
                  </p>
                  <Link
                    to={`/demo/candidates/${candidate.id}`}
                    onClick={() => setCompareOpen(false)}
                    className="mt-3 inline-flex text-xs text-[#c4c7c9] underline"
                  >
                    상세 기록 열기
                  </Link>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
