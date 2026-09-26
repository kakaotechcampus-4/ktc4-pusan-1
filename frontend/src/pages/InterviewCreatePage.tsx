/**
 * 면접 만들기 — 지원자 정보 · 이력서 · 초대 링크 발급 (면접관)
 *
 * 기획의 1·2·3 단계를 한 화면에서 끝낸다. 서버 쪽은 세 번의 호출이다.
 *
 *   POST /api/v1/interviews                  면접 정보 생성
 *   POST /api/v1/interviews/{id}/resume      이력서 업로드 (⚠️ 명세에 없음 · 목)
 *   POST /api/v1/interviews/{id}/sessions    Session 생성 + 초대 링크 발급
 *
 * 사용자에게는 버튼 하나다. 이력서는 interviewId 가 있어야 올릴 수 있어서
 * 파일을 미리 받아 두고, 버튼을 누를 때 면접 생성 직후에 올린다.
 *
 * 중간에 실패하면 면접만 만들어지고 Session 이 없는 상태가 되는데,
 * 그때는 다시 누르면 새 면접이 생긴다 — 기존 InterviewSetupPage 와 같은 방침이다.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getContext } from '../api/context';
import { createInterview, createSession } from '../api/interview';
import { uploadResume } from '../api/resume';
import { DocCard } from '../components/context/DocCard';
import { DropZone } from '../components/context/DropZone';
import { normalizeCandidateName } from '../lib/candidateName';
import { checkFile } from '../lib/docFile';
import type { ContextDoc, UploadRejection } from '../types/interview';

/** ⚠️ 인증이 없어 면접관 ID 를 클라이언트가 정한다. 로그인 도입 시 사라진다. */
const MOCK_INTERVIEWER_ID = 'user_demo';
const CONTEXT_ID = 'ctx_demo';

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'unsupported-type': 'PDF 와 DOCX 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

export default function InterviewCreatePage() {
  const [candidateName, setCandidateName] = useState('');
  const {
    data: context,
    isError: contextError,
    isLoading: contextLoading,
  } = useQuery({
    queryKey: ['context', CONTEXT_ID],
    queryFn: () => getContext(CONTEXT_ID),
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

  // 세 요청이 이어지지만 사용자에게는 한 번의 동작이므로 하나의 뮤테이션으로 묶는다.
  const create = useMutation({
    mutationFn: async () => {
      // 이름은 서버 계약으로 전달한다 (#39). 브라우저에 따로 보관하지 않는다.
      const interview = await createInterview(
        MOCK_INTERVIEWER_ID,
        normalizeCandidateName(candidateName),
      );

      if (resume) {
        setDoc((prev) => prev && { ...prev, status: 'uploading', progress: 0 });
        try {
          await uploadResume(interview.interviewId, resume, (ratio) =>
            setDoc((prev) => prev && { ...prev, progress: ratio }),
          );
          setDoc((prev) => prev && { ...prev, status: 'ready', progress: undefined });
        } catch {
          // 이력서 하나 때문에 링크 발급까지 막지 않는다. 면접은 그대로 만들고 실패만 알린다.
          setDoc((prev) => prev && { ...prev, status: 'failed', progress: undefined });
          setNotice('이력서를 올리지 못했습니다. 면접은 그대로 만들었습니다.');
        }
      }

      return createSession(interview.interviewId);
    },
  });

  const session = create.data;
  // 생성 실패가 나머지보다 중요하다. 겹치면 생성 쪽을 보여준다.
  const error = create.isError ? '면접을 만들지 못했습니다. 잠시 후 다시 시도해주세요.' : copyError;
  const uploading = doc?.status === 'uploading';
  const canCreate = candidateName.trim().length > 0 && !create.isPending;

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
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한이 없거나 보안 컨텍스트가 아니면 실패한다.
      // 링크는 화면에 그대로 보이므로 직접 선택해 복사할 수 있다.
      setCopyError('자동 복사에 실패했습니다. 링크를 직접 선택해 복사해주세요.');
    }
  };

  return (
    <div className="bg-surface min-h-full px-5 py-10 sm:px-8">
      <div className="mx-auto w-full max-w-3xl">
        <header>
          <div className="text-ink-muted flex items-center gap-2 text-[13px] tracking-wider uppercase">
            <span aria-hidden className="bg-brand h-2 w-2 rounded-full" />
            <span>신규 면접</span>
          </div>
          <h1 className="text-ink mt-1.5 text-2xl font-bold">면접 만들기</h1>
          <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">
            지원자 정보와 이력서를 등록하면 면접 세션이 만들어지고, 지원자에게 보낼 초대 링크가
            발급됩니다.
          </p>
        </header>

        {!session && (
          <>
            <SectionCard icon="person" title="지원자 기본 정보" badge="필수 입력 항목">
              <Field label="지원자 이름" htmlFor="candidate-name" required>
                <div className="relative">
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
                      className="material-symbols-outlined absolute top-2.5 right-3 text-[18px] text-emerald-400"
                    >
                      check_circle
                    </span>
                  )}
                </div>
                <p className="text-ink-dim mt-1.5 text-[13px]">
                  면접관 화면에 표시됩니다. 지원자에게는 보이지 않습니다.
                </p>
              </Field>

              {/* ⚠️ 회사·직무를 실어 보낼 필드가 면접 생성 계약에 없다.
                  지금은 화면에만 남고 서버로 가지 않는다 — BE 스키마가 생기면 함께 넘긴다. */}
              {/* 회사와 기본 직무는 읽기 전용으로 보여주고, 값 수정은 기업 설정에서 한다. */}
              <div className="border-border-base bg-surface-container mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
                <div>
                  <p className="text-ink-muted text-[12px]">기업 컨텍스트</p>
                  <p className="text-ink mt-0.5 text-[14px] font-medium">
                    {contextLoading
                      ? '불러오는 중…'
                      : context
                        ? `${context.company} · ${context.role}`
                        : contextError
                          ? '설정을 불러오지 못했습니다.'
                          : '아직 등록된 설정이 없습니다.'}
                  </p>
                  <p className="text-ink-dim mt-1 text-[12px]">
                    회사와 기본 직무는 기업 설정에서 관리합니다.
                  </p>
                </div>
                <Link
                  to="/settings/context"
                  className="text-brand-soft text-[13px] font-medium hover:underline"
                >
                  설정 확인
                </Link>
              </div>
            </SectionCard>

            <SectionCard icon="upload_file" title="지원자 이력서" badge="PDF · DOCX · 50MB 이하">
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
                  label="지원자 이력서를 끌어다 놓으세요"
                />
              )}
              <p className="text-ink-dim mt-3 text-[13px] leading-relaxed">
                AI 가 이력서를 근거로 질문을 만듭니다. 파일은 면접 생성과 함께 업로드됩니다.
              </p>
            </SectionCard>

            <section className="border-border-base bg-surface-panel mt-5 flex flex-col items-start justify-between gap-4 rounded-xl border p-6 shadow-xl sm:flex-row sm:items-center">
              <div className="flex items-center gap-3">
                <span
                  aria-hidden
                  className="border-border-input bg-surface-input text-ink-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-full border"
                >
                  <span className="material-symbols-outlined text-[20px]">link</span>
                </span>
                <div>
                  <p className="text-ink text-[15px] font-semibold">지원자 전용 링크 발급</p>
                  <p className="text-ink-muted mt-0.5 text-[13px] leading-relaxed">
                    생성 후 나오는 링크를 지원자에게 전달하면 그 링크로 면접에 입장합니다.
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => create.mutate()}
                disabled={!canCreate}
                className="group bg-brand disabled:bg-surface-bright disabled:text-ink-dim flex w-full shrink-0 items-center justify-center gap-2 rounded-lg px-6 py-3 text-[15px] font-bold text-white transition hover:bg-blue-700 sm:w-auto"
              >
                <span>
                  {create.isPending
                    ? uploading
                      ? '이력서 올리는 중…'
                      : '만드는 중…'
                    : '면접 세션 생성 및 링크 발급'}
                </span>
                <span
                  aria-hidden
                  className="material-symbols-outlined text-[20px] transition-transform group-hover:translate-x-1"
                >
                  arrow_forward
                </span>
              </button>
            </section>

            {!canCreate && !create.isPending && (
              <p className="text-ink-dim mt-2 text-center text-[13px]">
                지원자 이름을 입력해주세요.
              </p>
            )}
          </>
        )}

        {session && (
          <SectionCard icon="check_circle" title="면접 세션이 만들어졌습니다">
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Summary label="지원자" value={session.candidateName ?? candidateName} />
              <Summary label="회사 설정" value={context?.company ?? '—'} />
              <Summary label="직무 설정" value={context?.role ?? '—'} />
            </dl>

            <dl className="border-border-input bg-surface-input mt-4 rounded-xl border p-5 font-mono text-[13px]">
              <Row label="면접 ID" value={session.interviewId} />
              <Row label="Session ID" value={session.sessionId} />
              <Row label="상태" value={session.status} accent />
              <Row label="이력서" value={doc?.name ?? '첨부 없음'} />
            </dl>

            <p className="text-ink mt-6 text-[15px] font-medium">지원자 초대 링크</p>
            <div className="mt-2 flex gap-2">
              <input
                readOnly
                value={session.inviteUrl}
                aria-label="지원자 초대 링크"
                onFocus={(e) => e.currentTarget.select()}
                className="border-border-input bg-surface-input text-brand-soft min-w-0 flex-1 rounded-lg border px-4 py-3 font-mono text-[13px]"
              />
              <button
                type="button"
                onClick={() => void handleCopy()}
                className="border-border-input bg-surface-bright text-ink hover:bg-border-base shrink-0 rounded-lg border px-4 py-3 text-sm font-medium transition"
              >
                {copied ? '복사됨' : '복사'}
              </button>
            </div>
            <p className="text-ink-dim mt-2 text-[13px]">
              이 링크를 다른 탭이나 다른 기기에서 열면 지원자로 입장합니다.
            </p>

            <Link
              to={`/interview/${session.sessionId}?role=interviewer`}
              className="bg-brand mt-6 block rounded-lg py-3.5 text-center text-[15px] font-bold text-white transition hover:bg-blue-700"
            >
              면접방 입장
            </Link>
          </SectionCard>
        )}

        <div aria-live="polite" className="mt-4 min-h-[20px]">
          {error && <p className="text-sm text-red-400">{error}</p>}
          {!error && notice && <p className="text-sm text-amber-300">{notice}</p>}
        </div>
      </div>
    </div>
  );
}

/** 시안의 입력 칸. 카드 배경보다 한 단 어둡게 해서 눌린 것처럼 보이게 한다. */
const INPUT_CLASS =
  'w-full rounded-lg border border-border-input bg-surface-input px-4 py-2.5 text-[15px] text-ink placeholder:text-ink-dim focus:border-brand focus:ring-1 focus:ring-brand focus:outline-none';

/** 아이콘 · 제목 · 오른쪽 배지를 가진 카드. 시안이 섹션마다 같은 모양을 쓴다. */
function SectionCard({
  icon,
  title,
  badge,
  children,
}: {
  icon: string;
  title: string;
  badge?: string;
  children: ReactNode;
}) {
  return (
    <section className="border-border-base bg-surface-panel mt-5 rounded-xl border p-6 shadow-xl">
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-ink flex items-center gap-2 text-[17px] font-bold">
          <span aria-hidden className="material-symbols-outlined text-brand text-[20px]">
            {icon}
          </span>
          {title}
        </h2>
        {badge && (
          <span className="border-border-base bg-surface-input text-ink-muted shrink-0 rounded border px-2 py-0.5 text-[12px]">
            {badge}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  htmlFor,
  required,
  children,
}: {
  label: string;
  htmlFor: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-ink mb-1.5 block text-[14px] font-semibold">
        {label}
        {required && (
          <span aria-hidden className="ml-1 text-red-400">
            *
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

/** 생성 결과 요약 한 칸 */
function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-border-base bg-surface-container rounded-lg border px-4 py-3">
      <dt className="text-ink-muted text-[12px]">{label}</dt>
      <dd className="text-ink mt-0.5 truncate text-[15px] font-semibold">{value}</dd>
    </div>
  );
}

function Row({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="mt-2 flex gap-3 first:mt-0">
      <dt className="text-ink-muted w-24 shrink-0">{label}</dt>
      <dd className={`min-w-0 truncate ${accent ? 'text-amber-300' : 'text-ink'}`}>{value}</dd>
    </div>
  );
}
