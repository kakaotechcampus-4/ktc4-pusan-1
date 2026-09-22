/**
 * 기업 컨텍스트 설정 (S0-1)
 *
 * 조직 하나가 공유하는 면접 기준을 모아 둔다 — 회사 이름, 기본 직무, JD·사내 문서,
 * 추가 인재상. AI 면접관이 질문과 평가를 만들 때 근거로 쓴다.
 *
 * ⚠️ BE 에 이 엔드포인트들이 없어 목으로 동작한다.
 * 시안의 상단 내비게이션·프로필, 엔진 준비도·동기화 면접방 수, 실시간 적용 프리뷰(질문
 * 가중치)는 우리 서버에 그 데이터가 없어 넣지 않았다.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { deleteDoc, getContext, uploadDoc } from '../api/context';
import { updateContextSettings } from '../api/contextSettings';
import { DocCard } from '../components/context/DocCard';
import { DropZone } from '../components/context/DropZone';
import { checkFile } from '../lib/docFile';
import type { CompanyContext, ContextDoc, UploadRejection } from '../types/interview';

/**
 * ⚠️ 설정은 조직당 하나인데 조직 컨텍스트를 알려주는 API 가 없다.
 * 조회 API 가 생기면 이 상수를 없애고 그 값을 쓴다.
 */
const CONTEXT_ID = 'ctx_demo';

/** 파싱 중인 문서가 있을 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 2000;

/** 인재상 입력 길이 상한. 프롬프트에 그대로 실리는 글이라 한도를 둔다 */
const TALENT_MAX = 2000;

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'unsupported-type': 'PDF 와 DOCX 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

/** 문서를 어느 칸에 올렸는가 */
type DocCategory = 'jd' | 'internal';

/** 업로드가 끝나기 전의 문서. 서버는 아직 이 문서를 모른다. */
interface PendingDoc extends ContextDoc {
  status: 'uploading';
}

interface SettingsForm {
  company: string;
  role: string;
  talentProfile: string;
}

export default function ContextSettingsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const queryKey = ['context', CONTEXT_ID];

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

  /**
   * 문서 분류.
   *
   * ⚠️ 업로드 API 에 문서 종류 필드가 없어 분류를 화면에만 들고 있다. 새로고침하면
   * 분류가 사라지는데, 목 서버도 문서 목록을 메모리에만 두므로 같이 사라진다.
   * BE 에 종류 필드가 생기면 이 상태를 없앤다.
   */
  const [categories, setCategories] = useState<Record<string, DocCategory>>({});

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => getContext(CONTEXT_ID),
    // 읽는 중인 문서가 하나라도 있으면 완료될 때까지 다시 묻는다.
    refetchInterval: (q) =>
      q.state.data?.docs.some((d) => d.status === 'parsing') ? POLL_INTERVAL_MS : false,
  });

  // 서버 값 위에 고친 칸을 얹은 것이 지금 화면의 값이다.
  // ⚠️ 조회 응답에 인재상 필드가 없어 그 칸은 늘 빈 값에서 시작한다 (api/contextSettings.ts 참고).
  const form: SettingsForm | null = data
    ? {
        company: draft.company ?? data.company,
        role: draft.role ?? data.role,
        talentProfile: draft.talentProfile ?? '',
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
    mutationFn: async ({ file, tempId }: { file: File; tempId: string; category: DocCategory }) =>
      uploadDoc(CONTEXT_ID, file, (ratio) =>
        setPending((prev) => prev.map((d) => (d.id === tempId ? { ...d, progress: ratio } : d))),
      ),
    onSuccess: (doc, { tempId, category }) => {
      // 임시 id 로 달아 둔 분류를 서버가 준 id 로 옮긴다.
      setCategories((prev) => {
        const next = { ...prev, [doc.id]: category };
        delete next[tempId];
        return next;
      });
      setPending((prev) => prev.filter((d) => d.id !== tempId));
      void qc.invalidateQueries({ queryKey });
    },
    onError: (_e, { tempId }) => {
      // 서버에 올라가지 않았으므로 목록에서 지운다. 임시 id 로 달아 둔 분류도 함께 버린다.
      setPending((prev) => prev.filter((d) => d.id !== tempId));
      setCategories((prev) => {
        const next = { ...prev };
        delete next[tempId];
        return next;
      });
      setNotice('올리지 못했습니다. 잠시 후 다시 시도해주세요.');
    },
  });

  // 낙관적 삭제 — 화면에서 먼저 지우고, 실패하면 되돌린다.
  const remove = useMutation({
    mutationFn: (docId: string) => deleteDoc(CONTEXT_ID, docId),
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
    mutationFn: (values: SettingsForm) => updateContextSettings(CONTEXT_ID, values),
    onSuccess: () => {
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
      setCategories((prev) => ({ ...prev, [tempId]: category }));
      setPending((prev) => [
        ...prev,
        {
          id: tempId,
          name: file.name,
          kind: checked.kind,
          sizeBytes: file.size,
          status: 'uploading',
          progress: 0,
        },
      ]);
      upload.mutate({ file, tempId, category });
    }
  };

  const docs: ContextDoc[] = [...(data?.docs ?? []), ...pending];
  const uploading = pending.length > 0;
  const docsIn = (category: DocCategory) => docs.filter((d) => categories[d.id] === category);
  // 분류를 잃은 문서 — 새로고침 뒤 서버에만 남은 것들이다. 위 categories 주석 참고.
  const unclassified = docs.filter((d) => !categories[d.id]);

  const update = (patch: Partial<SettingsForm>) => {
    // 고치는 순간 "저장했습니다"를 내린다. 저장하지 않은 값에 그 문구가 남아 있으면 안 된다.
    setSaved(false);
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  // 컨텍스트는 선택이다. 문서도 회사 이름도 없이 면접을 보는 경우가 있어 빈 값도 저장을 허용한다.
  // 대신 무엇이 비었는지는 아래 안내로 알려 준다.
  const canSave = !save.isPending && !uploading;
  const empty = Boolean(
    form && !form.company.trim() && !form.role.trim() && !form.talentProfile.trim() && !docs.length,
  );

  return (
    <div className="bg-surface min-h-full px-4 py-8 md:px-8">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
        <header className="flex flex-col gap-2 pb-1">
          <span className="text-ink-dim font-mono text-[13px]">기업 컨텍스트</span>
          <h1 className="text-ink text-2xl font-bold tracking-tight md:text-3xl">
            기업 채용 컨텍스트 설정
          </h1>
          <p className="text-ink-muted max-w-2xl text-[15px] leading-relaxed">
            여기에 등록한 내용은 앞으로 만드는 모든 면접에 함께 적용됩니다. AI 면접관이 질문과
            평가를 만들 때 근거로 씁니다.
          </p>
        </header>

        {isLoading && <p className="text-ink-muted text-[15px]">불러오는 중…</p>}

        {form && (
          <>
            <Section
              icon="corporate_fare"
              step={1}
              title="기본 정보"
              desc="면접을 만들 때 초깃값으로 쓰입니다."
            >
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <TextField
                  id="company"
                  label="회사 이름"
                  value={form.company}
                  onChange={(v) => update({ company: v })}
                  placeholder="예: 엘리스"
                  hint="AI 면접관이 인사할 때 이 이름을 부릅니다."
                />
                <TextField
                  id="role"
                  label="기본 직무"
                  value={form.role}
                  onChange={(v) => update({ role: v })}
                  placeholder="예: 백엔드 엔지니어"
                  hint="면접마다 바꿀 수 있습니다."
                />
              </div>
            </Section>

            <Section
              icon="description"
              step={2}
              title="직무 기술서 (JD)"
              desc="필요 역량과 우대 조건을 읽어 질문을 만듭니다."
            >
              <DocList
                docs={docsIn('jd')}
                onDelete={(id) => remove.mutate(id)}
                empty="아직 올린 JD 가 없습니다."
              />
              <DropZone
                label="직무 기술서를 끌어다 놓으세요"
                onFiles={(files) => handleFiles(files, 'jd')}
                disabled={uploading}
              />
            </Section>

            <Section
              icon="menu_book"
              step={3}
              title="사내 문서"
              desc="컬처 코드, 핵심가치 문서 등을 올리면 조직에 맞춘 질문에 반영합니다."
            >
              <DocList
                docs={docsIn('internal')}
                onDelete={(id) => remove.mutate(id)}
                empty="아직 올린 사내 문서가 없습니다."
              />
              <DropZone
                label="사내 문서를 끌어다 놓으세요"
                onFiles={(files) => handleFiles(files, 'internal')}
                disabled={uploading}
              />

              {unclassified.length > 0 && (
                <div className="flex flex-col gap-2.5">
                  <p className="text-ink-dim text-[13px]">
                    분류가 남아 있지 않은 문서입니다. 면접에는 그대로 쓰입니다.
                  </p>
                  <DocList docs={unclassified} onDelete={(id) => remove.mutate(id)} />
                </div>
              )}
            </Section>

            <Section
              icon="psychology_alt"
              step={4}
              title="추가 기업 인재상"
              desc="문서에 없지만 꼭 확인하고 싶은 점을 적어주세요."
              aside={
                <span className="border-border-base bg-surface-container text-ink-muted rounded-full border px-2.5 py-1 font-mono text-[12px]">
                  {form.talentProfile.length} / {TALENT_MAX.toLocaleString()}자
                </span>
              }
            >
              <textarea
                rows={6}
                maxLength={TALENT_MAX}
                value={form.talentProfile}
                onChange={(e) => update({ talentProfile: e.target.value })}
                placeholder={
                  '예) 주어진 요구사항을 구현한 수준을 넘어, 스스로 문제를 찾아 해결한 경험을 확인해주세요.\n예) 의견이 갈렸을 때 어떤 근거로 설득했는지 물어봐주세요.'
                }
                className="border-border-base bg-surface-panel text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand w-full resize-none rounded-xl border p-4 text-[15px] leading-relaxed transition-colors outline-none focus:ring-1"
              />
            </Section>

            <div className="border-border-base bg-surface-panel flex flex-col gap-4 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between">
              <div aria-live="polite" className="min-h-[20px] text-[13px]">
                {notice ? (
                  <span className="text-[#FFC46B]">{notice}</span>
                ) : saved ? (
                  <span className="text-emerald-400">저장했습니다.</span>
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
                <Link
                  to="/"
                  className="border-border-base text-ink hover:bg-surface-bright flex items-center justify-center rounded-lg border px-4 py-2.5 text-[15px] font-medium transition-colors"
                >
                  나가기
                </Link>
                <button
                  type="button"
                  disabled={!canSave}
                  onClick={() => {
                    setLeaveAfterSave(false);
                    save.mutate(form);
                  }}
                  className="border-border-base text-ink hover:bg-surface-bright disabled:text-ink-dim flex items-center justify-center gap-1.5 rounded-lg border px-4 py-2.5 text-[15px] font-medium transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">save</span>
                  <span>{save.isPending && !leaveAfterSave ? '저장 중…' : '저장'}</span>
                </button>
                <button
                  type="button"
                  disabled={!canSave}
                  onClick={() => {
                    setLeaveAfterSave(true);
                    save.mutate(form);
                  }}
                  className="bg-brand disabled:bg-surface-bright disabled:text-ink-dim flex items-center justify-center gap-1.5 rounded-lg px-5 py-2.5 text-[15px] font-medium text-white transition-colors hover:bg-[#1d4ed8]"
                >
                  <span>{save.isPending && leaveAfterSave ? '저장 중…' : '저장하고 나가기'}</span>
                  <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 번호가 붙은 설정 묶음. 시안의 카드 한 장에 해당한다. */
function Section({
  icon,
  step,
  title,
  desc,
  aside,
  children,
}: {
  /** Material Symbols 이름 */
  icon: string;
  step: number;
  title: string;
  desc: string;
  /** 제목 줄 오른쪽에 붙는 것 (글자 수 등) */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-border-base bg-surface-container rounded-xl border p-5 md:p-6">
      <div className="border-border-base flex flex-col gap-2 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="border-brand/20 bg-brand/10 text-brand-soft flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border"
          >
            <span className="material-symbols-outlined text-[20px]">{icon}</span>
          </span>
          <div>
            <h2 className="text-ink font-semibold">
              {step}. {title}
            </h2>
            <p className="text-ink-muted text-[13px]">{desc}</p>
          </div>
        </div>
        {aside}
      </div>

      <div className="flex flex-col gap-3 pt-4">{children}</div>
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
        {required && <span className="ml-1 text-[#FFC46B]">*</span>}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="border-border-base bg-surface-panel text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand h-11 w-full rounded-lg border px-3.5 text-[15px] transition-colors outline-none focus:ring-1"
      />
      <p className="text-ink-dim text-[12px]">{hint}</p>
    </div>
  );
}

function DocList({
  docs,
  onDelete,
  empty,
}: {
  docs: ContextDoc[];
  onDelete: (docId: string) => void;
  /** 비어 있을 때 보여줄 문구. 없으면 아무것도 그리지 않는다 */
  empty?: string;
}) {
  if (docs.length === 0) {
    return empty ? <p className="text-ink-dim text-[13px]">{empty}</p> : null;
  }

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
