/**
 * 기업 컨텍스트 설정 (S0-1)
 *
 * 조직 하나가 공유하는 면접 기준을 모아 둔다 — 회사 이름, 기본 직무, JD·사내 문서,
 * 추가 인재상. AI 면접관이 질문과 평가를 만들 때 근거로 쓴다.
 *
 * 시안의 상단 내비게이션·프로필, 엔진 준비도·동기화 면접방 수, 실시간 적용 프리뷰(질문
 * 가중치)는 우리 서버에 그 데이터가 없어 넣지 않았다.
 *
 * 넓은 화면은 왼쪽에 단계 목차와 채운 정도, 오른쪽에 카드 넷을 둔다. 저장 막대는 화면
 * 아래에 붙어 따라온다 (#232).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { deleteDoc, getContext, getCurrentContext, uploadDoc } from '../api/context';
import { ApiError, uploadErrorMessage } from '../api/client';
import { updateContextSettings } from '../api/contextSettings';
import { DocCard } from '../components/context/DocCard';
import { DropZone } from '../components/context/DropZone';
import { buttonClass } from '../components/ui/buttonClass';
import { Skeleton } from '../components/ui/Skeleton';
import { checkFile } from '../lib/docFile';
import type { CompanyContext, ContextDoc, DocCategory, UploadRejection } from '../types/interview';

/** 파싱 중인 문서가 있을 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 2000;

/** 인재상 입력 길이 상한. 프롬프트에 그대로 실리는 글이라 한도를 둔다 */
const TALENT_MAX = 2000;

const STEPS = [
  { id: 'basic', title: '기본 정보' },
  { id: 'jd', title: '직무 기술서 (JD)' },
  { id: 'internal', title: '사내 문서' },
  { id: 'talent', title: '추가 인재상' },
];

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'empty-file': '내용이 있는 파일을 선택해주세요.',
  'unsupported-type': 'PDF 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

/** 업로드가 끝나기 전의 문서. 서버는 아직 이 문서를 모른다. */
interface PendingDoc extends ContextDoc {
  status: 'uploading';
  /** 올리는 중에도 칸을 알아야 해당 칸에 진행률이 보인다. */
  category: DocCategory;
}

interface SettingsForm {
  company: string;
  team: string;
  role: string;
  talentProfile: string;
}

export default function ContextSettingsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const queryKey = ['context'];

  const [pending, setPending] = useState<PendingDoc[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  /**
   * 사용자가 고친 칸만 담는다.
   *
   * 서버 값을 state 로 복사해 두면 폴링 응답이 올 때마다 입력 중인 칸을 덮어쓸 위험이 있다.
   * 고친 칸만 들고 있다가 화면을 그릴 때 서버 값 위에 얹는다.
   */
  const [draft, setDraft] = useState<Partial<SettingsForm>>({});

  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey,
    queryFn: async () => {
      // 처음에는 현재 조직을 찾고, 이후에는 확인된 id의 저장·문서 상태를 조회한다.
      const id = qc.getQueryData<CompanyContext>(queryKey)?.id;
      if (!id) return getCurrentContext();
      try {
        return await getContext(id);
      } catch (error) {
        // 로컬 BE가 재시작해 id가 없어졌으면 현재 컨텍스트부터 다시 찾는다.
        if (error instanceof ApiError && error.status === 404) return getCurrentContext();
        throw error;
      }
    },
    // 읽는 중인 문서가 하나라도 있으면 완료될 때까지 다시 묻는다.
    refetchInterval: (q) =>
      q.state.data?.docs.some((d) => d.status === 'parsing') ? POLL_INTERVAL_MS : false,
  });

  /**
   * 문서 업로드·삭제·저장은 실제 컨텍스트 id 가 필요하다.
   *
   * 조회가 끝나기 전에는 빈 문자열이지만, 그 사이에는 화면이 "불러오는 중" 이라
   * 누를 수 있는 버튼이 없다.
   */
  const contextId = data?.id ?? '';

  // 서버 값 위에 고친 칸을 얹은 것이 지금 화면의 값이다.
  //
  // 저장된 인재상도 서버 응답에서 읽는다. 폴링은 입력 중인 draft를 덮지 않는다.
  const form: SettingsForm | null = data
    ? {
        company: draft.company ?? data.company,
        team: draft.team ?? data.team,
        role: draft.role ?? data.role,
        talentProfile: draft.talentProfile ?? data.talentProfile ?? '',
      }
    : null;

  // 브라우저 기본 동작은 파일을 떨어뜨리면 그 파일을 여는 것이다.
  // 드롭존 밖에 놓쳤을 때 페이지가 통째로 사라지는 것을 막는다.
  useEffect(() => {
    const block = (e: DragEvent) => e.preventDefault();
    window.addEventListener('dragover', block);
    window.addEventListener('drop', block);
    return () => {
      window.removeEventListener('dragover', block);
      window.removeEventListener('drop', block);
    };
  }, []);

  const upload = useMutation({
    mutationFn: async ({
      file,
      tempId,
      category,
    }: {
      file: File;
      tempId: string;
      category: DocCategory;
    }) =>
      uploadDoc(
        contextId,
        file,
        (ratio) =>
          setPending((prev) => prev.map((d) => (d.id === tempId ? { ...d, progress: ratio } : d))),
        category,
      ),
    onSuccess: (_doc, { tempId }) => {
      // 분류는 서버가 들고 있다. 다시 조회하면 올린 칸 그대로 돌아온다.
      setPending((prev) => prev.filter((d) => d.id !== tempId));
      void qc.invalidateQueries({ queryKey });
    },
    onError: (error, { tempId }) => {
      // 서버에 올라가지 않았으므로 목록에서 지운다.
      setPending((prev) => prev.filter((d) => d.id !== tempId));
      setNotice(uploadErrorMessage(error));
    },
  });

  // 낙관적 삭제 — 화면에서 먼저 지우고, 실패하면 되돌린다.
  const remove = useMutation({
    mutationFn: (docId: string) => deleteDoc(contextId, docId),
    onMutate: async (docId) => {
      // 진행 중인 조회를 멈춘다. 안 그러면 지운 문서가 폴링 응답으로 되살아난다.
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<CompanyContext>(queryKey);
      if (previous) {
        qc.setQueryData<CompanyContext>(queryKey, {
          ...previous,
          docs: previous.docs.filter((d) => d.id !== docId),
        });
      }
      return { previous };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKey, ctx.previous);
      setNotice('삭제하지 못했습니다.');
    },
    onSettled: () => void qc.invalidateQueries({ queryKey }),
  });

  // 저장 후 바로 나갈지 — "저장하고 나가기" 로 눌렀는지 기억해 둔다.
  const [leaveAfterSave, setLeaveAfterSave] = useState(false);

  const save = useMutation({
    mutationFn: (values: SettingsForm) => updateContextSettings(contextId, values),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey });
      setNotice(null);
      setSaved(true);
      if (leaveAfterSave) void navigate('/');
    },
    onError: () => {
      setSaved(false);
      setNotice('저장하지 못했습니다. 잠시 후 다시 시도해주세요.');
    },
  });

  const handleFiles = (files: File[], category: DocCategory) => {
    setNotice(null);
    for (const file of files) {
      const checked = checkFile(file);
      if (!checked.ok) {
        setNotice(REJECTION_MESSAGE[checked.reason]);
        continue;
      }
      const tempId = `tmp_${Date.now()}_${file.name}`;
      setPending((prev) => [
        ...prev,
        {
          id: tempId,
          name: file.name,
          kind: checked.kind,
          sizeBytes: file.size,
          status: 'uploading',
          category,
          progress: 0,
        },
      ]);
      upload.mutate({ file, tempId, category });
    }
  };

  const docs: ContextDoc[] = [...(data?.docs ?? []), ...pending];
  const uploading = pending.length > 0;
  const docsIn = (category: DocCategory) => docs.filter((d) => d.category === category);

  const update = (patch: Partial<SettingsForm>) => {
    // 고치는 순간 "저장했습니다"를 내린다. 저장하지 않은 값에 그 문구가 남아 있으면 안 된다.
    setSaved(false);
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  // 컨텍스트는 선택이다. 문서도 회사 이름도 없이 면접을 보는 경우가 있어 빈 값도 저장을 허용한다.
  // 대신 무엇이 비었는지는 아래 안내로 알려 준다.
  const canSave = !save.isPending && !uploading;
  const empty = Boolean(
    form &&
    !form.company.trim() &&
    !form.team.trim() &&
    !form.role.trim() &&
    !form.talentProfile.trim() &&
    !docs.length,
  );

  // 단계마다 무언가 채웠는지. 모두 선택이라 「완료」가 아니라 「채움」을 센다.
  const filled = form
    ? [
        Boolean(form.company.trim() || form.team.trim() || form.role.trim()),
        docsIn('jd').length > 0,
        docsIn('internal').length > 0,
        Boolean(form.talentProfile.trim()),
      ]
    : [false, false, false, false];
  const filledCount = filled.filter(Boolean).length;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-8 sm:px-6 lg:px-10 lg:pt-10">
      <header className="max-w-2xl">
        <h1 className="text-ink text-[26px] font-bold tracking-tight">기업 설정</h1>
        <p className="text-ink-muted mt-1.5 text-[15px] leading-relaxed">
          여기에 등록한 내용은 앞으로 만드는 모든 면접에 함께 적용됩니다. AI 가 질문과 요약을 만들
          때 근거로 씁니다. 모두 선택 항목입니다.
        </p>
      </header>

      {isLoading && (
        <div className="mt-8 flex flex-col gap-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      )}

      {isError && (
        <div role="alert" className="text-ink-muted mt-8 text-[15px]">
          <p>기업 설정을 불러오지 못했습니다.</p>
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

      {form && (
        <div className="mt-8 lg:grid lg:grid-cols-[220px_1fr] lg:gap-10">
          {/* 넓은 화면에서만 — 어디까지 채웠는지와 바로가기 */}
          <nav aria-label="설정 단계" className="hidden lg:block">
            <div className="sticky top-8">
              <p className="text-ink-muted text-[13px]">
                4단계 중 <span className="text-ink font-semibold">{filledCount}</span>개 채움
              </p>
              <div className="bg-surface-bright mt-2 h-1.5 overflow-hidden rounded-full">
                <div
                  className="bg-brand h-full rounded-full transition-[width]"
                  style={{ width: `${(filledCount / 4) * 100}%` }}
                />
              </div>
              <ol className="mt-5 flex flex-col gap-1">
                {STEPS.map((step, i) => (
                  <li key={step.id}>
                    <a
                      href={`#${step.id}`}
                      className="text-ink-muted hover:bg-surface-bright hover:text-ink flex items-center gap-3 rounded-lg px-2 py-2 text-[14px]"
                    >
                      <StepMark n={i + 1} done={filled[i]} />
                      {step.title}
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          </nav>

          <div className="flex min-w-0 flex-col gap-5">
            <Section
              id={STEPS[0].id}
              step={1}
              done={filled[0]}
              title={STEPS[0].title}
              desc="면접을 만들 때 초깃값으로 쓰입니다."
            >
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <TextField
                  id="company"
                  label="회사 이름"
                  value={form.company}
                  onChange={(v) => update({ company: v })}
                  placeholder="예: 엘리스"
                  hint="AI 면접관이 인사할 때 이 이름을 부릅니다."
                />
                <TextField
                  id="team"
                  label="팀"
                  value={form.team}
                  onChange={(v) => update({ team: v })}
                  placeholder="예: 플랫폼 팀"
                  hint="면접을 진행하는 팀입니다."
                />
                <TextField
                  id="role"
                  label="기본 직무"
                  value={form.role}
                  onChange={(v) => update({ role: v })}
                  placeholder="예: 백엔드 엔지니어"
                  hint="면접에서 참고할 기본 직무입니다."
                />
              </div>
            </Section>

            <Section
              id={STEPS[1].id}
              step={2}
              done={filled[1]}
              title={STEPS[1].title}
              desc="필요 역량과 우대 조건을 읽어 질문을 만듭니다."
            >
              <DocList docs={docsIn('jd')} onDelete={(id) => remove.mutate(id)} />
              <DropZone
                label="직무 기술서를 끌어다 놓거나 눌러서 고르세요"
                onFiles={(files) => handleFiles(files, 'jd')}
                disabled={uploading}
              />
            </Section>

            <Section
              id={STEPS[2].id}
              step={3}
              done={filled[2]}
              title={STEPS[2].title}
              desc="컬처 코드, 핵심가치 문서 등을 올리면 조직에 맞춘 질문에 반영합니다."
            >
              <DocList docs={docsIn('internal')} onDelete={(id) => remove.mutate(id)} />
              <DropZone
                label="사내 문서를 끌어다 놓거나 눌러서 고르세요"
                onFiles={(files) => handleFiles(files, 'internal')}
                disabled={uploading}
              />
            </Section>

            <Section
              id={STEPS[3].id}
              step={4}
              done={filled[3]}
              title={STEPS[3].title}
              desc="문서에 없지만 꼭 확인하고 싶은 점을 적어주세요."
              aside={
                <span className="text-ink-dim font-mono text-[12px]">
                  {form.talentProfile.length} / {TALENT_MAX.toLocaleString()}
                </span>
              }
            >
              <textarea
                aria-label="추가 기업 인재상"
                rows={6}
                maxLength={TALENT_MAX}
                value={form.talentProfile}
                onChange={(e) => update({ talentProfile: e.target.value })}
                placeholder={
                  '예) 주어진 요구사항을 구현한 수준을 넘어, 스스로 문제를 찾아 해결한 경험을 확인해주세요.\n예) 의견이 갈렸을 때 어떤 근거로 설득했는지 물어봐주세요.'
                }
                className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand/20 w-full resize-y rounded-xl border p-4 text-[15px] leading-relaxed transition outline-none focus:ring-4"
              />
            </Section>

            {/* 저장 막대는 화면 아래에 붙어 따라온다. 좁은 화면에서는 아래 탭 위에 선다. */}
            <div className="border-border-base bg-surface-panel/95 shadow-pop sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 -mx-1 mb-6 flex flex-col gap-3 rounded-2xl border p-4 backdrop-blur sm:flex-row sm:items-center lg:bottom-6">
              <div aria-live="polite" className="min-h-[20px] flex-1 text-[14px]">
                {notice ? (
                  <span className="text-danger">{notice}</span>
                ) : saved ? (
                  <span className="text-accent-strong inline-flex items-center gap-1.5 font-semibold">
                    <span aria-hidden className="material-symbols-outlined text-[18px]">
                      check_circle
                    </span>
                    저장했습니다.
                  </span>
                ) : empty ? (
                  <span className="text-ink-dim">
                    비워 두어도 됩니다. 문서 없이도 면접을 만들 수 있습니다.
                  </span>
                ) : (
                  <span className="text-ink-dim">저장하면 다음 면접부터 적용됩니다.</span>
                )}
              </div>

              {/* 나가는 길을 저장 버튼 옆에 둔다. 멀리 떨어져 있으면 저장하고 나가려다
                  브라우저 뒤로 가기를 쓰게 된다. */}
              <div className="flex gap-2">
                <Link to="/" className={`${buttonClass('ghost')} flex-1 sm:flex-none`}>
                  나가기
                </Link>
                <button
                  type="button"
                  disabled={!canSave}
                  onClick={() => {
                    setLeaveAfterSave(false);
                    save.mutate(form);
                  }}
                  className={`${buttonClass('secondary')} flex-1 sm:flex-none`}
                >
                  {save.isPending && !leaveAfterSave ? '저장 중…' : '저장'}
                </button>
                <button
                  type="button"
                  disabled={!canSave}
                  onClick={() => {
                    setLeaveAfterSave(true);
                    save.mutate(form);
                  }}
                  className={`${buttonClass('primary')} flex-1 sm:flex-none`}
                >
                  {save.isPending && leaveAfterSave ? '저장 중…' : '저장하고 나가기'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 단계 번호. 무언가 채웠으면 체크로 바뀐다. */
function StepMark({ n, done }: { n: number; done: boolean }) {
  return (
    <span
      aria-hidden
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${
        done ? 'bg-accent text-white' : 'bg-surface-bright text-ink-muted'
      }`}
    >
      {done ? <span className="material-symbols-outlined text-[17px]">check</span> : n}
    </span>
  );
}

/** 번호가 붙은 설정 묶음 하나 = 카드 한 장. */
function Section({
  id,
  step,
  done,
  title,
  desc,
  aside,
  children,
}: {
  /** 왼쪽 단계 목차가 가리키는 앵커 */
  id: string;
  step: number;
  done: boolean;
  title: string;
  desc: string;
  /** 제목 줄 오른쪽에 붙는 것 (글자 수 등) */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className="border-border-base bg-surface-panel shadow-card scroll-mt-6 rounded-2xl border p-5 sm:p-6"
    >
      <div className="flex items-start gap-3">
        <StepMark n={step} done={done} />
        <div className="min-w-0 flex-1">
          <h2 className="text-ink text-[17px] font-semibold">{title}</h2>
          <p className="text-ink-muted mt-0.5 text-[14px]">{desc}</p>
        </div>
        {aside}
      </div>

      <div className="mt-5 flex flex-col gap-3">{children}</div>
    </section>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
  required,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  hint: string;
  required?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-ink text-[13px] font-semibold">
        {label}
        {required && <span className="text-warning ml-1">*</span>}
      </label>
      <input
        id={id}
        type="text"
        maxLength={100}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand/20 h-11 w-full rounded-xl border px-3.5 text-[15px] transition outline-none focus:ring-4"
      />
      <p className="text-ink-dim text-[12px]">{hint}</p>
    </div>
  );
}

/** 올린 문서들. 비어 있으면 아래 업로드 상자가 그 자리를 대신 말한다. */
function DocList({ docs, onDelete }: { docs: ContextDoc[]; onDelete: (docId: string) => void }) {
  if (docs.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5">
      {docs.map((doc) => (
        <DocCard
          key={doc.id}
          doc={doc}
          // 업로드 중인 문서는 서버가 모르므로 지울 수 없다.
          onDelete={doc.status === 'uploading' ? undefined : () => onDelete(doc.id)}
        />
      ))}
    </div>
  );
}
