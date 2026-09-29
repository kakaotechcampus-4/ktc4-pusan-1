import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { InterviewerHeader } from '../components/layout/InterviewerHeader';
import {
  findDemoCandidate,
  formatDemoTime,
  loadDemoCandidates,
  saveDemoCandidates,
  updateDemoCandidate,
  type DemoCandidate,
} from '../lib/demoReview';

export default function CandidateMemoPage() {
  const { candidateId } = useParams<{ candidateId: string }>();
  const [candidates, setCandidates] = useState<DemoCandidate[]>(loadDemoCandidates);
  const [notice, setNotice] = useState('');
  const candidate = findDemoCandidate(candidates, candidateId);

  const saveMemo = (memo: string) => {
    if (!candidate) return;
    const next = updateDemoCandidate(candidates, candidate.id, (current) => ({ ...current, memo }));
    setCandidates(next);
    saveDemoCandidates(next);
    setNotice('샘플 메모를 저장했습니다.');
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

  const bookmarks = candidate.questions.filter((question) => question.bookmarked);
  const unresolved = candidate.findings.filter((finding) => finding.state === 'unreviewed');
  const questionCounts = candidate.coverage.map((item) => ({
    ...item,
    count: candidate.questions.filter((question) => question.competency === item.name).length,
  }));

  return (
    <div className="min-h-full bg-[#121316] text-[#eaecef]">
      <InterviewerHeader demo />
      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-full border border-[#44474a] bg-[#202229] font-mono text-sm">
              {candidate.name.slice(0, 1)}
            </span>
            <div>
              <p className="font-mono text-[10px] text-[#686c7b]">
                샘플 면접 기록 · {candidate.role}
              </p>
              <h1 className="mt-1 text-xl font-bold">{candidate.name}</h1>
              <p className="mt-1 text-xs text-[#9498a4]">
                경력 {candidate.years}년 · {candidate.interviewer} 면접관
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/demo/candidates"
              className="rounded-full border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
            >
              ← 목록
            </Link>
            <Link
              to={`/demo/candidates/${candidate.id}`}
              className="rounded-full border border-[#2e323c] bg-[#202229] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#282b34]"
            >
              면접 기록 보기
            </Link>
          </div>
        </header>

        <p className="mt-4 border-l-2 border-[#44474a] pl-3 text-xs leading-5 text-[#9498a4]">
          샘플 발언을 요약하고 근거 위치를 연결했습니다. 평가와 채용 판단은 면접관이 합니다.
        </p>

        <nav aria-label="면접 메모 요약" className="mt-5 flex flex-wrap gap-2">
          <a
            href="#memo-summary"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            요약
          </a>
          <a
            href="#memo-quotes"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            직접 인용 {candidate.questions.length}
          </a>
          <a
            href="#memo-notes"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            내 메모
          </a>
          <a
            href="#memo-balance"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            질문 균형
          </a>
          <a
            href="#memo-followup"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            다음 질문
          </a>
          <a
            href="#memo-unconfirmed"
            className="rounded-full border border-[#2e323c] px-3 py-2 text-xs text-[#c4c7c9] hover:bg-[#202229]"
          >
            확인하지 못한 항목 {unresolved.length}
          </a>
        </nav>

        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(300px,0.9fr)]">
          <div className="flex flex-col gap-4">
            <section
              id="memo-summary"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="flex items-center justify-between gap-3 border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">발언 요약</h2>
                <span className="text-[10px] text-[#9498a4]">지원자 발언 기반</span>
              </header>
              <div className="mt-4 space-y-3">
                {candidate.summary.map((paragraph, index) => (
                  <p
                    key={index}
                    className="border-l border-[#44474a] pl-3 text-xs leading-6 text-[#c4c7c9]"
                  >
                    {paragraph}
                  </p>
                ))}
              </div>
            </section>

            <section
              id="memo-quotes"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="flex items-center justify-between gap-3 border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">직접 인용</h2>
                <span className="text-[10px] text-[#9498a4]">샘플 발언</span>
              </header>
              <div className="divide-y divide-[#272a33]">
                {candidate.questions.map((question) => (
                  <article
                    key={question.id}
                    className="flex flex-wrap items-start gap-3 py-4 first:pt-3 last:pb-0"
                  >
                    <span className="rounded bg-[#22242c] px-2 py-1 font-mono text-[10px] text-[#9498a4]">
                      {formatDemoTime(question.atSec)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold">“{question.answer}”</p>
                      <p className="mt-1 text-[10px] text-[#686c7b]">
                        지원자 · {question.competency}
                      </p>
                    </div>
                    <Link
                      to={`/demo/candidates/${candidate.id}#section-c`}
                      className="rounded border border-[#2e323c] px-2.5 py-1.5 text-[10px] text-[#c4c7c9] hover:bg-[#22242c]"
                    >
                      질문·답변 보기
                    </Link>
                  </article>
                ))}
              </div>
            </section>

            <section
              id="memo-notes"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="flex items-center justify-between gap-3 border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">내 메모</h2>
                <span className="text-[10px] text-[#9498a4]">면접관만 볼 수 있음 · 데모 저장</span>
              </header>
              <label htmlFor="candidate-private-memo" className="sr-only">
                면접관 메모
              </label>
              <textarea
                id="candidate-private-memo"
                value={candidate.memo}
                onChange={(event) => saveMemo(event.target.value)}
                rows={5}
                placeholder="면접 중 확인한 내용을 기록하세요."
                className="mt-4 w-full resize-y rounded border border-[#2e323c] bg-[#121316] p-3 text-xs leading-5 text-[#eaecef] placeholder:text-[#686c7b]"
              />
              <p className="mt-2 min-h-4 text-[10px] text-[#9498a4]" aria-live="polite">
                {notice || '입력한 메모는 이 브라우저 세션에 보관됩니다.'}
              </p>
            </section>
          </div>

          <aside className="flex flex-col gap-4">
            <section
              id="memo-balance"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">질문 균형</h2>
                <p className="mt-1 text-[10px] text-[#9498a4]">질문 수를 정리합니다.</p>
              </header>
              <div className="mt-4 space-y-3">
                {questionCounts.map((item) => (
                  <div
                    key={item.name}
                    className="grid grid-cols-[72px_1fr_24px] items-center gap-2 text-[10px]"
                  >
                    <span
                      className={item.state === 'missing' ? 'text-[#f59e0b]' : 'text-[#9498a4]'}
                    >
                      {item.name}
                    </span>
                    <span className="h-2 overflow-hidden rounded-full bg-[#262831]">
                      <span
                        className="block h-full rounded-full bg-[#8e9194]"
                        style={{ width: `${Math.min(100, item.count * 34)}%` }}
                      />
                    </span>
                    <span className="text-right font-mono text-[#9498a4]">{item.count}</span>
                  </div>
                ))}
              </div>
              <p className="mt-4 rounded bg-[#22242c] p-3 text-[10px] leading-5 text-[#9498a4]">
                질문 분포만 보여줍니다. 역량 점수나 합격 판단은 제공하지 않습니다.
              </p>
            </section>

            <section
              id="memo-followup"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">다음에 확인할 내용</h2>
                <p className="mt-1 text-[10px] text-[#9498a4]">면접관이 판단할 후속 질문입니다.</p>
              </header>
              <div className="mt-4 space-y-2">
                {candidate.findings.map((finding, index) => (
                  <Link
                    key={finding.id}
                    to={`/demo/candidates/${candidate.id}#section-b`}
                    className="flex gap-3 rounded border border-[#272a33] bg-[#202229] p-3 text-xs hover:bg-[#282b34]"
                  >
                    <span className="font-mono text-[#ffe082]">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span>{finding.title}</span>
                  </Link>
                ))}
              </div>
            </section>

            <section
              id="memo-unconfirmed"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">확인하지 못한 항목</h2>
              </header>
              <div className="mt-4 flex flex-wrap gap-2">
                {candidate.coverage
                  .filter((item) => item.state !== 'confirmed')
                  .map((item) => (
                    <Link
                      key={item.name}
                      to={`/demo/candidates/${candidate.id}#section-a`}
                      className={`rounded-full border px-3 py-1.5 text-[10px] ${item.state === 'missing' ? 'border-amber-500/50 bg-[#191a20] text-[#ffe082]' : 'border-[#44474a] text-[#c4c7c9]'}`}
                    >
                      {item.name} · {item.state === 'missing' ? '미확인' : '일부 확인'}
                    </Link>
                  ))}
              </div>
            </section>

            <section
              id="memo-bookmarks"
              className="scroll-mt-20 rounded-lg border border-[#272a33] bg-[#18191f] p-5"
            >
              <header className="border-b border-[#22242c] pb-3">
                <h2 className="text-sm font-bold">북마크 {bookmarks.length}건</h2>
              </header>
              <div className="mt-3 space-y-2">
                {bookmarks.length === 0 ? (
                  <p className="text-xs text-[#686c7b]">저장된 북마크가 없습니다.</p>
                ) : (
                  bookmarks.map((question) => (
                    <Link
                      key={question.id}
                      to={`/demo/candidates/${candidate.id}#section-c`}
                      className="flex gap-2 rounded border border-[#272a33] p-2.5 text-[10px] hover:bg-[#202229]"
                    >
                      <span className="font-mono text-[#9498a4]">
                        {formatDemoTime(question.atSec)}
                      </span>
                      <span>{question.label}</span>
                    </Link>
                  ))
                )}
              </div>
            </section>
          </aside>
        </div>
        <p className="mt-5 text-[10px] leading-5 text-[#686c7b]">
          이 화면의 인물과 발언은 가공 샘플입니다. 실제 면접 정보와 섞이지 않습니다.
        </p>
      </main>
    </div>
  );
}
