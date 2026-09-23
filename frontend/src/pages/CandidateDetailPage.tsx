import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { InterviewerHeader } from '../components/layout/InterviewerHeader';
import {
  findDemoCandidate,
  formatDemoDuration,
  formatDemoTime,
  loadDemoCandidates,
  saveDemoCandidates,
  updateDemoCandidate,
  type DemoCandidate,
  type DemoFinding,
  type FindingState,
} from '../lib/demoReview';

function downloadRecord(candidate: DemoCandidate) {
  const blob = new Blob([JSON.stringify(candidate, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${candidate.name}-샘플-검토.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function Panel({
  id,
  title,
  aside,
  children,
}: {
  id: string;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-4 sm:p-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-[#22242c] pb-3">
        <h2 className="text-sm font-bold">{title}</h2>
        {aside && <div className="text-[11px] text-[#9498a4]">{aside}</div>}
      </header>
      <div className="pt-4">{children}</div>
    </section>
  );
}

function stateText(state: FindingState) {
  if (state === 'adopted') return '근거 채택';
  if (state === 'excluded') return '제외';
  return '미검토';
}

export default function CandidateDetailPage() {
  const { candidateId } = useParams<{ candidateId: string }>();
  const location = useLocation();
  const [candidates, setCandidates] = useState(loadDemoCandidates);
  const [notice, setNotice] = useState('');
  const [expandedQuestions, setExpandedQuestions] = useState(false);
  const [transcriptFinding, setTranscriptFinding] = useState<string | null>(null);
  const [editingRange, setEditingRange] = useState<DemoFinding | null>(null);
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [undoState, setUndoState] = useState<DemoCandidate | null>(null);

  const candidate = findDemoCandidate(candidates, candidateId);
  const selectedIndex = candidates.findIndex((item) => item.id === candidateId);

  useEffect(() => {
    if (!location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth' });
  }, [location.hash]);

  const persistCandidate = (update: (current: DemoCandidate) => DemoCandidate) => {
    if (!candidate) return;
    setUndoState(candidate);
    const next = updateDemoCandidate(candidates, candidate.id, update);
    setCandidates(next);
    saveDemoCandidates(next);
  };

  const setFindingState = (findingId: string, state: FindingState) => {
    const finding = candidate?.findings.find((item) => item.id === findingId);
    if (!finding) return;
    persistCandidate((current) => ({
      ...current,
      status: current.status === '확정' ? '검토 중' : current.status,
      findings: current.findings.map((item) => (item.id === findingId ? { ...item, state } : item)),
      reviewHistory: [
        ...current.reviewHistory,
        {
          id: `event-${Date.now()}`,
          at: new Date().toISOString(),
          action: `${stateText(state)} · ${finding.title}`,
        },
      ],
    }));
    setNotice(`${stateText(state)} 상태를 샘플 기록에 저장했습니다.`);
  };

  const undoLast = () => {
    if (!candidate || !undoState) return;
    const next = updateDemoCandidate(candidates, candidate.id, () => undoState);
    setCandidates(next);
    saveDemoCandidates(next);
    setUndoState(null);
    setNotice('직전 변경을 되돌렸습니다.');
  };

  const saveCorrectedRange = () => {
    if (!candidate || !editingRange) return;
    const startSec = Number(rangeStart);
    const endSec = Number(rangeEnd);
    if (
      !Number.isFinite(startSec) ||
      !Number.isFinite(endSec) ||
      startSec < 0 ||
      endSec <= startSec
    ) {
      setNotice('끝 시각은 시작 시각보다 뒤여야 합니다.');
      return;
    }
    persistCandidate((current) => ({
      ...current,
      findings: current.findings.map((finding) =>
        finding.id === editingRange.id
          ? { ...finding, correctedRange: { startSec, endSec } }
          : finding,
      ),
      reviewHistory: [
        ...current.reviewHistory,
        {
          id: `event-${Date.now()}`,
          at: new Date().toISOString(),
          action: `${editingRange.title} · 구간 보정 ${formatDemoTime(startSec)}–${formatDemoTime(endSec)}`,
        },
      ],
    }));
    setEditingRange(null);
    setNotice('보정 구간을 샘플 기록에 저장했습니다.');
  };

  const confirmReview = () => {
    if (!candidate) return;
    persistCandidate((current) => ({
      ...current,
      status: '확정',
      reviewHistory: [
        ...current.reviewHistory,
        { id: `event-${Date.now()}`, at: new Date().toISOString(), action: '검토 확정' },
      ],
    }));
    setNotice('샘플 검토 상태를 확정했습니다.');
  };

  if (!candidate) {
    return (
      <div className="min-h-full bg-[#121316] text-[#eaecef]">
        <InterviewerHeader demo />
        <main className="mx-auto max-w-3xl px-4 py-12">
          <h1 className="text-xl font-bold">지원자 기록을 찾을 수 없습니다</h1>
          <Link className="mt-5 inline-flex text-sm underline" to="/demo/candidates">
            샘플 목록으로
          </Link>
        </main>
      </div>
    );
  }

  const previous = candidates[(selectedIndex - 1 + candidates.length) % candidates.length];
  const next = candidates[(selectedIndex + 1) % candidates.length];
  const questions = expandedQuestions ? candidate.questions : candidate.questions.slice(0, 4);
  const adoptedCount = candidate.findings.filter((finding) => finding.state === 'adopted').length;
  const excludedCount = candidate.findings.filter((finding) => finding.state === 'excluded').length;
  const unresolvedCount = candidate.findings.filter(
    (finding) => finding.state === 'unreviewed',
  ).length;
  const latestHistoryId = candidate.reviewHistory[candidate.reviewHistory.length - 1]?.id;

  return (
    <div className="min-h-full bg-[#121316] pb-24 text-[#eaecef]">
      <InterviewerHeader demo />
      <main className="mx-auto max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
        <header className="border-b border-[#272a33] pb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to="/demo/candidates" className="text-xs text-[#9498a4] hover:text-white">
              ← 지원자 목록
            </Link>
            <div className="flex gap-2">
              <Link
                to={`/demo/candidates/${previous.id}`}
                className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-xs hover:bg-[#282b34]"
              >
                ← 이전
              </Link>
              <Link
                to={`/demo/candidates/${next.id}`}
                className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-xs hover:bg-[#282b34]"
              >
                다음 →
              </Link>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <p className="font-mono text-[10px] text-[#686c7b]">
                {dateLabel(candidate.interviewAt)} · {formatDemoDuration(candidate.durationSec)}
              </p>
              <h1 className="mt-1 text-lg font-bold sm:text-xl">
                {candidate.name} · {candidate.role} · 경력 {candidate.years}년
              </h1>
              <p className="mt-1 text-xs text-[#9498a4]">
                면접관 {candidate.interviewer} · 샘플 면접 기록
              </p>
            </div>
            <span className="ml-auto rounded border border-amber-500/50 bg-[#ffe082] px-2 py-1 text-[10px] font-bold text-[#212121]">
              {candidate.status}
            </span>
            <Link
              to={`/demo/candidates/${candidate.id}/memo`}
              className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs hover:bg-[#282b34]"
            >
              AI 메모 화면
            </Link>
          </div>
        </header>

        <nav
          aria-label="지원자 기록 구간"
          className="sticky top-14 z-20 mt-4 flex gap-1 overflow-x-auto border-b border-[#272a33] bg-[#121316]/95 py-2 backdrop-blur"
        >
          {[
            ['section-a', 'A 개요'],
            ['section-b', 'B 확인 필요'],
            ['section-c', 'C 질문·답변'],
            ['section-d', 'D 검토 기록'],
            ['section-e', 'E 내 메모'],
            ['section-f', 'F 내보내기'],
          ].map(([href, label]) => (
            <a
              key={href}
              href={`#${href}`}
              className="shrink-0 rounded px-3 py-2 text-[11px] text-[#9498a4] hover:bg-[#1a1c22] hover:text-white"
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="mt-4 grid items-start gap-4 lg:grid-cols-[190px_minmax(0,1fr)]">
          <aside className="hidden lg:sticky lg:top-28 lg:block">
            <p className="mb-2 font-mono text-[10px] text-[#686c7b]">검토 목차</p>
            <div className="flex flex-col gap-1">
              {[
                ['section-a', 'A 개요'],
                ['section-b', `B 확인 필요 ${unresolvedCount}`],
                ['section-c', `C 질문·답변 ${candidate.questions.length}`],
                ['section-d', 'D 검토 기록'],
                ['section-e', 'E 내 메모'],
                ['section-f', 'F 내보내기'],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={`#${href}`}
                  className="rounded px-3 py-2 text-xs text-[#9498a4] hover:bg-[#1a1c22] hover:text-white"
                >
                  {label}
                </a>
              ))}
            </div>
          </aside>

          <div className="flex min-w-0 flex-col gap-4">
            <Panel id="section-a" title="A. 이 면접에서 확인한 내용">
              <div className="grid gap-3 sm:grid-cols-2">
                {candidate.coverage.map((item) => (
                  <div
                    key={item.name}
                    className="flex items-center gap-3 rounded border border-[#272a33] bg-[#15161b] p-3"
                  >
                    <span
                      aria-hidden
                      className={`flex h-3 w-3 shrink-0 items-center justify-center rounded-full border ${item.state === 'confirmed' ? 'border-[#eaecef] bg-[#eaecef]' : item.state === 'partial' ? 'border-[#eaecef] bg-gradient-to-r from-[#eaecef] from-50% to-transparent to-50%' : 'border-[#686c7b]'}`}
                    />
                    <span className="text-xs">{item.name}</span>
                    <span className="ml-auto font-mono text-[10px] text-[#9498a4]">
                      {item.state === 'confirmed'
                        ? '확인'
                        : item.state === 'partial'
                          ? '일부'
                          : '미확인'}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs leading-5 text-[#9498a4]">{candidate.summary.join(' ')}</p>
            </Panel>

            <Panel
              id="section-b"
              title={`B. 확인이 필요한 항목 ${unresolvedCount}건`}
              aside="근거가 없는 항목은 만들지 않았습니다."
            >
              <div className="space-y-3">
                {candidate.findings.map((finding) => (
                  <article
                    key={finding.id}
                    className={`rounded-lg border p-4 ${finding.uncertain ? 'border-dashed border-amber-500/50 bg-[#191a20]' : 'border-[#272a33] bg-[#15161b]'}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded px-2 py-1 text-[10px] font-bold ${finding.state === 'adopted' ? 'bg-[#eaecef] text-[#121316]' : finding.state === 'excluded' ? 'bg-[#202229] text-[#9498a4]' : 'bg-[#ffe082] text-[#212121]'}`}
                          >
                            {stateText(finding.state)}
                          </span>
                          {finding.uncertain && (
                            <span className="rounded border border-amber-500/50 px-2 py-1 text-[10px] text-[#ffe082]">
                              전사 확인 필요
                            </span>
                          )}
                          <span className="font-mono text-[10px] text-[#686c7b]">
                            {finding.source}
                          </span>
                        </div>
                        <h3 className="mt-2 text-sm font-semibold">{finding.title}</h3>
                      </div>
                      {finding.atSec !== null && (
                        <span className="font-mono text-[11px] text-[#9498a4]">
                          {formatDemoTime(finding.atSec)}
                        </span>
                      )}
                    </div>
                    <p className="mt-3 border-l border-[#44474a] pl-3 text-xs leading-5 text-[#c4c7c9]">
                      “{finding.quote}”
                    </p>
                    <p className="mt-2 text-[11px] leading-5 text-[#9498a4]">{finding.rationale}</p>
                    {finding.correctedRange && (
                      <p className="mt-2 font-mono text-[10px] text-[#ffe082]">
                        보정 구간 {formatDemoTime(finding.correctedRange.startSec)}–
                        {formatDemoTime(finding.correctedRange.endSec)}
                      </p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {finding.state !== 'adopted' && (
                        <button
                          type="button"
                          onClick={() => setFindingState(finding.id, 'adopted')}
                          className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-[11px] hover:bg-[#282b34]"
                        >
                          근거로 채택
                        </button>
                      )}
                      {finding.state !== 'excluded' && (
                        <button
                          type="button"
                          onClick={() => setFindingState(finding.id, 'excluded')}
                          className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-[11px] hover:bg-[#282b34]"
                        >
                          제외
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() =>
                          setTranscriptFinding((current) =>
                            current === finding.id ? null : finding.id,
                          )
                        }
                        className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-[11px] hover:bg-[#282b34]"
                      >
                        원문 STT 보기
                      </button>
                      {finding.atSec !== null && (
                        <button
                          type="button"
                          onClick={() => {
                            setEditingRange(finding);
                            setRangeStart(
                              String(
                                finding.correctedRange?.startSec ?? Math.max(0, finding.atSec! - 5),
                              ),
                            );
                            setRangeEnd(
                              String(finding.correctedRange?.endSec ?? finding.atSec! + 10),
                            );
                          }}
                          className="rounded border border-[#2e323c] bg-[#202229] px-2.5 py-1.5 text-[11px] hover:bg-[#282b34]"
                        >
                          구간 보정
                        </button>
                      )}
                    </div>
                    {transcriptFinding === finding.id && (
                      <blockquote className="mt-3 rounded border border-[#272a33] bg-[#121316] p-3 text-xs leading-5 text-[#c4c7c9]">
                        “{finding.transcript}”
                      </blockquote>
                    )}
                  </article>
                ))}
              </div>
            </Panel>

            <Panel
              id="section-c"
              title={`C. 질문 · 답변 ${candidate.questions.length}건`}
              aside="행을 열면 질문의 전체 답변을 봅니다."
            >
              <div className="divide-y divide-[#272a33] rounded border border-[#272a33]">
                {questions.map((question, index) => (
                  <article
                    key={question.id}
                    className="grid gap-3 p-3 sm:grid-cols-[68px_minmax(0,1fr)_120px]"
                  >
                    <div className="font-mono text-[10px] text-[#9498a4]">
                      {String(index + 1).padStart(2, '0')} · {formatDemoTime(question.atSec)}
                    </div>
                    <div>
                      <p className="text-xs font-semibold">Q. {question.question}</p>
                      <p className="mt-1 text-xs leading-5 text-[#9498a4]">A. {question.answer}</p>
                    </div>
                    <span className="self-start font-mono text-[10px] text-[#9498a4]">
                      샘플 발언
                    </span>
                  </article>
                ))}
              </div>
              {candidate.questions.length > 4 && (
                <button
                  type="button"
                  onClick={() => setExpandedQuestions((value) => !value)}
                  className="mt-3 w-full rounded border border-[#2e323c] bg-[#202229] py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
                >
                  {expandedQuestions
                    ? '접기'
                    : `나머지 ${candidate.questions.length - 4}건 더 보기`}
                </button>
              )}
            </Panel>

            <Panel
              id="section-d"
              title="D. 검토 기록"
              aside="이 기록은 현재 브라우저의 샘플 상태에만 저장됩니다."
            >
              {candidate.reviewHistory.length === 0 ? (
                <p className="text-xs text-[#686c7b]">아직 검토한 항목이 없습니다.</p>
              ) : (
                <ul className="space-y-2">
                  {[...candidate.reviewHistory].reverse().map((event) => {
                    const canUndo = Boolean(undoState && event.id === latestHistoryId);
                    return (
                      <li
                        key={event.id}
                        className="flex flex-wrap items-center justify-between gap-2 border-b border-[#22242c] pb-2 text-xs last:border-0"
                      >
                        <span className="font-mono text-[10px] text-[#9498a4]">
                          {dateLabel(event.at)}
                        </span>
                        <span className="flex-1 sm:pl-4">{event.action}</span>
                        <button
                          type="button"
                          disabled={!canUndo}
                          onClick={undoLast}
                          className="rounded border border-[#2e323c] px-2 py-1 text-[10px] text-[#c4c7c9] hover:bg-[#22242c] disabled:opacity-40"
                        >
                          되돌리기
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {undoState && (
                <button
                  type="button"
                  onClick={undoLast}
                  className="mt-3 text-[11px] text-[#9498a4] underline"
                >
                  직전 변경 되돌리기
                </button>
              )}
            </Panel>

            <Panel
              id="section-e"
              title={`E. 내 메모 · 북마크 ${candidate.questions.filter((question) => question.bookmarked).length}건`}
              aside="메모는 이 데모 브라우저에만 보관됩니다."
            >
              <label htmlFor="candidate-memo" className="text-xs text-[#9498a4]">
                면접관 메모
              </label>
              <textarea
                id="candidate-memo"
                rows={4}
                value={candidate.memo}
                onChange={(event) => {
                  const next = updateDemoCandidate(candidates, candidate.id, (current) => ({
                    ...current,
                    memo: event.target.value,
                  }));
                  setCandidates(next);
                  saveDemoCandidates(next);
                }}
                placeholder="확인한 근거와 다음 질문을 기록하세요."
                className="mt-2 w-full resize-y rounded border border-[#2e323c] bg-[#121316] p-3 text-xs leading-5 text-[#eaecef] placeholder:text-[#686c7b]"
              />
              <div className="mt-4 space-y-2">
                {candidate.questions
                  .filter((question) => question.bookmarked)
                  .map((question) => (
                    <a
                      key={question.id}
                      href="#section-c"
                      className="flex gap-3 rounded border border-[#272a33] bg-[#15161b] p-3 text-xs hover:bg-[#202229]"
                    >
                      <span className="font-mono text-[#9498a4]">
                        {formatDemoTime(question.atSec)}
                      </span>
                      <span>{question.answer}</span>
                    </a>
                  ))}
              </div>
            </Panel>

            <Panel
              id="section-f"
              title="F. 샘플 기록 내보내기"
              aside="현재 브라우저의 샘플 상태를 내려받습니다."
            >
              <button
                type="button"
                onClick={() => downloadRecord(candidate)}
                className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
              >
                샘플 기록 내보내기
              </button>
            </Panel>
          </div>
        </div>
      </main>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-[#272a33] bg-[#15161b]/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <span className="font-mono text-[11px] text-[#9498a4]">
            채택 {adoptedCount} · 제외 {excludedCount} · 미검토 {unresolvedCount}
          </span>
          <span className="min-w-0 flex-1 text-[11px] text-[#686c7b]" aria-live="polite">
            {notice || '샘플 자료의 근거를 검토한 뒤 확정하세요.'}
          </span>
          <button
            type="button"
            onClick={confirmReview}
            disabled={candidate.status === '확정'}
            className="rounded bg-[#f0f2f5] px-4 py-2 text-xs font-bold text-[#121316] hover:bg-white disabled:cursor-default disabled:opacity-50"
          >
            {candidate.status === '확정' ? '검토 확정됨' : '검토 확정'}
          </button>
        </div>
      </div>

      {editingRange && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEditingRange(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="range-title"
            className="w-full max-w-md rounded-lg border border-[#2e323c] bg-[#15161b] p-5"
          >
            <h2 id="range-title" className="text-sm font-bold">
              샘플 발언 구간 보정
            </h2>
            <p className="mt-1 text-xs text-[#9498a4]">
              샘플 기록에서 사용할 시작·끝 시각을 초 단위로 지정합니다.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="text-xs text-[#9498a4]">
                시작(초)
                <input
                  type="number"
                  min="0"
                  value={rangeStart}
                  onChange={(event) => setRangeStart(event.target.value)}
                  className="mt-1 w-full rounded border border-[#2e323c] bg-[#121316] px-3 py-2 text-[#eaecef]"
                />
              </label>
              <label className="text-xs text-[#9498a4]">
                끝(초)
                <input
                  type="number"
                  min="0"
                  value={rangeEnd}
                  onChange={(event) => setRangeEnd(event.target.value)}
                  className="mt-1 w-full rounded border border-[#2e323c] bg-[#121316] px-3 py-2 text-[#eaecef]"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditingRange(null)}
                className="rounded border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9]"
              >
                취소
              </button>
              <button
                type="button"
                onClick={saveCorrectedRange}
                className="rounded bg-[#f0f2f5] px-3 py-2 text-xs font-bold text-[#121316]"
              >
                저장
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}
