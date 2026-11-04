/**
 * 면접 만들기 — 지원자 정보 · 이력서 · 초대 링크 발급 (면접관)
 *
 * 기획의 1·2·3 단계를 한 화면에서 끝낸다. 서버 쪽은 세 번의 호출이다.
 *
 *   POST /api/v1/interviews                  면접 정보 생성
 *   POST /api/v1/interviews/{id}/resume      이력서 업로드
 *   POST /api/v1/interviews/{id}/sessions    Session 생성 + 초대 링크 발급
 *
 * 사용자에게는 버튼 하나다. 이력서는 interviewId 가 있어야 올릴 수 있어서
 * 파일을 미리 받아 두고, 버튼을 누를 때 면접 생성 직후에 올린다.
 *
 * 중간에 실패하면 면접만 만들어지고 Session 이 없는 상태가 되는데,
 * 그때는 다시 누르면 새 면접이 생긴다 — 기존 InterviewSetupPage 와 같은 방침이다.
 *
 * 화면은 1 지원자 → 2 이력서 → 3 링크 발급 순서로 보이고, 만들어지면 초대 링크
 * 시트가 뜬다 (#232).
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getMe } from '../api/auth';
import { uploadErrorMessage } from '../api/client';
import { useAccessToken } from '../hooks/useAccessToken';
import { getCurrentContext } from '../api/context';
import { createInterview, createSession } from '../api/interview';
import { uploadResume } from '../api/resume';
import { DocCard } from '../components/context/DocCard';
import { DropZone } from '../components/context/DropZone';
import { buttonClass } from '../components/ui/buttonClass';
import { Card } from '../components/ui/Card';
import { Sheet } from '../components/ui/Sheet';
import { toast } from '../lib/toast';
import { normalizeCandidateName } from '../lib/candidateName';
import { checkFile } from '../lib/docFile';
import type { ContextDoc, UploadRejection } from '../types/interview';

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'empty-file': '내용이 있는 파일을 선택해주세요.',
  'unsupported-type': 'PDF 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

export default function InterviewCreatePage() {
  const token = useAccessToken();
  const { data: me } = useQuery({ queryKey: ['me', token], queryFn: getMe });
  const [candidateName, setCandidateName] = useState('');
  const {
    data: context,
    isError: contextError,
    isLoading: contextLoading,
  } = useQuery({
    queryKey: ['context'],
    queryFn: getCurrentContext,
  });

  // 고른 파일과 화면에 보여줄 상태를 나눠 둔다 — 파일은 업로드에, 상태는 카드 표시에 쓴다.
  const [resume, setResume] = useState<File | null>(null);
  const [doc, setDoc] = useState<ContextDoc | null>(null);

  const [notice, setNotice] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // 브라우저 기본 동작은 파일을 떨어뜨리면 그 파일을 여는 것이다.
  // 드롭존 밖에 놓쳤을 때 입력해 둔 값이 통째로 사라지는 것을 막는다.
  useEffect(() => {
    const block = (e: DragEvent) => e.preventDefault();
    window.addEventListener('dragover', block);
    window.addEventListener('drop', block);
    return () => {
      window.removeEventListener('dragover', block);
      window.removeEventListener('drop', block);
    };
  }, []);

  // 만들어지면 링크 시트를 띄운다. 닫아도 결과 카드에서 다시 열 수 있다.
  const [sheetOpen, setSheetOpen] = useState(false);

  // 세 요청이 이어지지만 사용자에게는 한 번의 동작이므로 하나의 뮤테이션으로 묶는다.
  const create = useMutation({
    mutationFn: async () => {
      if (!me) throw new Error('로그인 상태를 확인해주세요.');
      // 면접관은 보내지 않는다 — 서버가 토큰의 사용자를 주인으로 삼는다 (#145).
      const interview = await createInterview(normalizeCandidateName(candidateName));

      if (resume) {
        setDoc((prev) => prev && { ...prev, status: 'uploading', progress: 0 });
        try {
          await uploadResume(interview.interviewId, resume, (ratio) =>
            setDoc((prev) => prev && { ...prev, progress: ratio }),
          );
          setDoc((prev) => prev && { ...prev, status: 'ready', progress: undefined });
        } catch (error) {
          // 이력서 하나 때문에 링크 발급까지 막지 않는다. 면접은 그대로 만들고 실패만 알린다.
          setDoc((prev) => prev && { ...prev, status: 'failed', progress: undefined });
          setNotice(`${uploadErrorMessage(error)} 면접은 그대로 만들었습니다.`);
        }
      }

      return createSession(interview.interviewId);
    },
    onSuccess: () => setSheetOpen(true),
  });

  const session = create.data;
  // 복사 실패는 링크 시트 안에서 알린다.
  const error = create.isError ? '면접을 만들지 못했습니다. 잠시 후 다시 시도해주세요.' : null;
  const uploading = doc?.status === 'uploading';
  const canCreate = Boolean(me) && candidateName.trim().length > 0 && !create.isPending;

  const handleFiles = (files: File[]) => {
    setNotice(null);
    // 이력서는 한 장이다. 여러 개를 놓으면 첫 번째만 받는다.
    const file = files[0];
    if (!file) return;

    const checked = checkFile(file);
    if (!checked.ok) {
      setNotice(REJECTION_MESSAGE[checked.reason]);
      return;
    }

    setResume(file);
    setDoc({
      id: `resume_local_${Date.now()}`,
      name: file.name,
      kind: checked.kind,
      sizeBytes: file.size,
      // 아직 서버에 올리지 않았지만, 사용자에게는 "첨부된 파일" 이다.
      status: 'ready',
    });
  };

  const handleCopy = async () => {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(session.inviteUrl);
      setCopied(true);
      toast('초대 링크를 복사했습니다.', 'success');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한이 없거나 보안 컨텍스트가 아니면 실패한다.
      // 링크는 화면에 그대로 보이므로 직접 선택해 복사할 수 있다.
      setCopyError('자동 복사에 실패했습니다. 링크를 직접 선택해 복사해주세요.');
    }
  };

  // 넓은 화면은 오른쪽, 좁은 화면은 아래에서 올라온다. 여는 순간의 폭으로 정한다.
  const sheetSide = window.matchMedia('(min-width: 1024px)').matches ? 'right' : 'bottom';

  // 지금 어느 단계인지 — 이름을 넣으면 1, 이력서를 붙이면 2, 링크가 나오면 3 이 끝난다.
  const stepDone = [
    Boolean(candidateName.trim()) || Boolean(session),
    Boolean(doc),
    Boolean(session),
  ];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-10 sm:px-6 lg:pt-10">
      <header>
        <h1 className="text-ink text-[26px] font-bold tracking-tight">면접 만들기</h1>
        <p className="text-ink-muted mt-1.5 text-[15px] leading-relaxed">
          지원자 정보와 이력서를 등록하면 지원자에게 보낼 초대 링크가 만들어집니다.
        </p>
      </header>

      <ol aria-label="진행 단계" className="mt-7 grid grid-cols-3 gap-2">
        {['지원자', '이력서', '링크 발급'].map((label, i) => (
          <li key={label} className="flex flex-col gap-2">
            <span
              className={`h-1.5 rounded-full transition-colors ${stepDone[i] ? 'bg-brand' : 'bg-surface-bright'}`}
            />
            <span
              className={`text-[13px] font-semibold ${stepDone[i] ? 'text-brand-strong' : 'text-ink-dim'}`}
            >
              {i + 1}. {label}
              {i === 1 && <span className="text-ink-dim font-normal"> (선택)</span>}
            </span>
          </li>
        ))}
      </ol>

      {!session && (
        <div className="mt-6 flex flex-col gap-5">
          <SectionCard
            step={1}
            done={stepDone[0]}
            title="지원자"
            desc="면접관 화면에만 표시됩니다."
          >
            <label htmlFor="candidate-name" className="text-ink text-[14px] font-semibold">
              지원자 이름 <span className="text-danger">*</span>
            </label>
            <div className="relative mt-1.5">
              <input
                id="candidate-name"
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                placeholder="성명을 입력하세요"
                autoComplete="off"
                maxLength={20}
                className={INPUT_CLASS}
              />
              {candidateName.trim() && (
                <span
                  aria-hidden
                  className="material-symbols-outlined text-accent absolute top-3 right-3 text-[20px]"
                >
                  check_circle
                </span>
              )}
            </div>

            {/* 회사와 기본 직무는 읽기 전용으로 보여주고, 값 수정은 기업 설정에서 한다.
                ⚠️ 회사·직무를 실어 보낼 필드가 면접 생성 계약에 없다 — 화면에만 남는다. */}
            <div className="bg-surface-container mt-4 flex items-center gap-3 rounded-xl px-4 py-3">
              <span aria-hidden className="material-symbols-outlined text-ink-dim text-[20px]">
                apartment
              </span>
              <p className="text-ink-muted min-w-0 flex-1 truncate text-[14px]">
                {contextLoading
                  ? '불러오는 중…'
                  : context
                    ? [context.company, context.team, context.role].filter(Boolean).join(' · ') ||
                      '기본 정보 미등록'
                    : contextError
                      ? '설정을 불러오지 못했습니다.'
                      : '아직 등록된 설정이 없습니다.'}
              </p>
              <Link
                to="/settings/context"
                className="text-brand -my-1 shrink-0 py-1 text-[13px] font-semibold"
              >
                기업 설정
              </Link>
            </div>
          </SectionCard>

          <SectionCard
            step={2}
            done={stepDone[1]}
            title="이력서"
            desc="AI 가 이력서를 근거로 질문을 만듭니다. 면접을 만들 때 함께 올립니다."
          >
            {doc ? (
              <DocCard
                doc={doc}
                // 올리는 중에는 취소할 수 없다. 끝난 뒤 다른 파일로 바꾼다.
                onDelete={
                  uploading || create.isPending
                    ? undefined
                    : () => {
                        setResume(null);
                        setDoc(null);
                        setNotice(null);
                      }
                }
              />
            ) : (
              <DropZone
                onFiles={handleFiles}
                disabled={create.isPending}
                label="이력서를 끌어다 놓거나 눌러서 고르세요"
              />
            )}
          </SectionCard>

          <div className="border-border-base bg-surface-panel shadow-card flex flex-col gap-3 rounded-2xl border p-5 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="text-ink text-[15px] font-semibold">3. 초대 링크 발급</p>
              <p className="text-ink-muted mt-0.5 text-[13px]">
                {canCreate || create.isPending
                  ? '지원자는 이 링크로 로그인 없이 입장합니다.'
                  : '지원자 이름을 입력하면 만들 수 있습니다.'}
              </p>
            </div>
            <button
              type="button"
              onClick={() => create.mutate()}
              disabled={!canCreate}
              className={`${buttonClass('primary', 'lg')} w-full sm:w-auto`}
            >
              {create.isPending ? (uploading ? '이력서 올리는 중…' : '만드는 중…') : '면접 만들기'}
              {!create.isPending && (
                <span aria-hidden className="material-symbols-outlined text-[20px]">
                  arrow_forward
                </span>
              )}
            </button>
          </div>
        </div>
      )}

      {session && (
        <Card className="mt-6 text-center">
          <span
            aria-hidden
            className="material-symbols-outlined bg-accent-tint text-accent-strong rounded-full p-3 text-[30px]"
          >
            check
          </span>
          <h2 className="text-ink mt-4 text-[20px] font-bold">면접이 만들어졌습니다</h2>
          <p className="text-ink-muted mt-1.5 text-[15px]">
            {session.candidateName ?? candidateName} 님에게 초대 링크를 보내 주세요.
          </p>
          <div className="mt-6 flex flex-col justify-center gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              className={buttonClass('secondary')}
            >
              <span aria-hidden className="material-symbols-outlined text-[20px]">
                link
              </span>
              초대 링크 보기
            </button>
            <Link
              to={`/interview/${session.sessionId}?role=interviewer`}
              className={buttonClass('primary')}
            >
              면접방 입장
            </Link>
          </div>
        </Card>
      )}

      <div aria-live="polite" className="mt-4 min-h-[20px]">
        {error && <p className="text-danger text-sm">{error}</p>}
        {!error && notice && <p className="text-warning text-sm">{notice}</p>}
      </div>

      {session && (
        <Sheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="초대 링크"
          side={sheetSide}
        >
          <p className="text-ink-muted text-[14px] leading-relaxed">
            링크를 지원자에게 보내 주세요. 지원자는 로그인 없이 이 링크로 입장합니다.
          </p>
          <div className="mt-4 flex gap-2">
            <input
              readOnly
              value={session.inviteUrl}
              aria-label="지원자 초대 링크"
              onFocus={(e) => e.currentTarget.select()}
              className="border-border-input bg-surface-container text-ink min-w-0 flex-1 rounded-xl border px-3.5 font-mono text-[13px]"
            />
            <button
              type="button"
              onClick={() => void handleCopy()}
              className={buttonClass(copied ? 'accent' : 'primary')}
            >
              <span aria-hidden className="material-symbols-outlined text-[18px]">
                {copied ? 'check' : 'content_copy'}
              </span>
              {copied ? '복사됨' : '복사'}
            </button>
          </div>
          {copyError && <p className="text-danger mt-2 text-[13px]">{copyError}</p>}

          <dl className="border-border-base mt-6 grid grid-cols-2 gap-3 border-t pt-5 text-[14px]">
            <Summary label="지원자" value={session.candidateName ?? candidateName} />
            <Summary label="이력서" value={doc?.name ?? '첨부 없음'} />
            <Summary label="회사" value={context?.company || '—'} />
            <Summary label="직무" value={context?.role || '—'} />
          </dl>

          <details className="text-ink-dim mt-5 text-[13px]">
            <summary className="cursor-pointer">면접 정보 자세히</summary>
            <dl className="mt-3 flex flex-col gap-1.5 font-mono text-[12px]">
              <Row label="면접 ID" value={session.interviewId} />
              <Row label="Session ID" value={session.sessionId} />
              <Row label="상태" value={session.status} />
            </dl>
          </details>

          <Link
            to={`/interview/${session.sessionId}?role=interviewer`}
            className={`${buttonClass('primary', 'lg')} mt-6 w-full`}
          >
            면접방 입장
          </Link>
          <Link to="/" className={`${buttonClass('ghost')} mt-2 w-full`}>
            홈으로
          </Link>
        </Sheet>
      )}
    </div>
  );
}

/** 흰 입력 칸. 누르면 인디고 테두리와 옅은 테가 생긴다. */
const INPUT_CLASS =
  'h-12 w-full rounded-xl border border-border-input bg-surface-input px-4 text-[15px] text-ink placeholder:text-ink-dim transition outline-none focus:border-brand focus:ring-4 focus:ring-brand/20';

/** 번호가 붙은 단계 카드. 채우면 번호가 체크로 바뀐다. */
function SectionCard({
  step,
  done,
  title,
  desc,
  children,
}: {
  step: number;
  done: boolean;
  title: string;
  desc: string;
  children: ReactNode;
}) {
  return (
    <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-5 sm:p-6">
      <div className="mb-5 flex items-start gap-3">
        <span
          aria-hidden
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${
            done ? 'bg-accent-strong text-white' : 'bg-brand-tint text-brand'
          }`}
        >
          {done ? <span className="material-symbols-outlined text-[17px]">check</span> : step}
        </span>
        <div>
          <h2 className="text-ink text-[17px] font-semibold">{title}</h2>
          <p className="text-ink-muted mt-0.5 text-[14px]">{desc}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

/** 생성 결과 요약 한 칸 */
function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-ink-dim text-[12px]">{label}</dt>
      <dd className="text-ink mt-0.5 truncate font-semibold">{value}</dd>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0">{label}</dt>
      <dd className="text-ink-muted min-w-0 truncate">{value}</dd>
    </div>
  );
}
