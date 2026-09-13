/**
 * 기업 컨텍스트 — 문서 업로드 (S1)
 *
 * 면접에 쓸 JD·회사 문서를 올린다. AI 가 이 문서를 근거로 질문과 요약을 만든다.
 *
 * ⚠️ BE 에 이 엔드포인트가 없어 목으로 동작한다.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { deleteDoc, getContext, uploadDoc } from '../api/context';
import { DocCard } from '../components/context/DocCard';
import { DropZone } from '../components/context/DropZone';
import { checkFile } from '../lib/docFile';
import type { CompanyContext, ContextDoc, UploadRejection } from '../types/interview';

/** 파싱 중인 문서가 있을 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 2000;

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'unsupported-type': 'PDF 와 DOCX 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

/** 업로드가 끝나기 전의 문서. 서버는 아직 이 문서를 모른다. */
interface PendingDoc extends ContextDoc {
  status: 'uploading';
}

export default function CompanyContextPage() {
  const { contextId = 'ctx_demo' } = useParams<{ contextId: string }>();
  const qc = useQueryClient();
  const queryKey = ['context', contextId];

  const [pending, setPending] = useState<PendingDoc[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => getContext(contextId),
    // 읽는 중인 문서가 하나라도 있으면 완료될 때까지 다시 묻는다.
    refetchInterval: (q) =>
      q.state.data?.docs.some((d) => d.status === 'parsing') ? POLL_INTERVAL_MS : false,
  });

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
    mutationFn: async ({ file, tempId }: { file: File; tempId: string }) =>
      uploadDoc(contextId, file, (ratio) =>
        setPending((prev) => prev.map((d) => (d.id === tempId ? { ...d, progress: ratio } : d))),
      ),
    onSettled: (_data, _error, { tempId }) => {
      setPending((prev) => prev.filter((d) => d.id !== tempId));
      void qc.invalidateQueries({ queryKey });
    },
    onError: () => setNotice('올리지 못했습니다. 잠시 후 다시 시도해주세요.'),
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

  const handleFiles = (files: File[]) => {
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
          progress: 0,
        },
      ]);
      upload.mutate({ file, tempId });
    }
  };

  const docs: ContextDoc[] = [...(data?.docs ?? []), ...pending];
  const uploading = pending.length > 0;
  // 읽기가 끝난 문서가 하나는 있어야 면접을 시작할 수 있다.
  const canStart = docs.some((d) => d.status === 'ready') && !uploading;

  return (
    <div className="flex min-h-full justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-2xl">
        <h1 className="text-2xl font-semibold text-white">기업 컨텍스트</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-white/60">
          면접에 쓸 직무 기술서와 회사 문서를 올려주세요. AI 가 이 내용을 근거로 질문과 요약을
          만듭니다.
        </p>

        {isLoading && <p className="mt-8 text-[15px] text-white/45">불러오는 중…</p>}

        {data && (
          <>
            <dl className="mt-7 grid grid-cols-2 gap-3">
              <Field label="회사 · 팀" value={`${data.company} · ${data.team}`} />
              <Field label="직무" value={data.role} />
            </dl>

            <section className="mt-7">
              <h2 className="text-[15px] font-medium text-white">문서</h2>

              {docs.length > 0 && (
                <div className="mt-3 flex flex-col gap-2.5">
                  {docs.map((doc) => (
                    <DocCard
                      key={doc.id}
                      doc={doc}
                      // 업로드 중인 문서는 서버가 모르므로 지울 수 없다.
                      onDelete={
                        doc.status === 'uploading' ? undefined : () => remove.mutate(doc.id)
                      }
                    />
                  ))}
                </div>
              )}

              <div className="mt-3">
                <DropZone onFiles={handleFiles} disabled={uploading} />
              </div>
            </section>

            <div aria-live="polite" className="mt-4 min-h-[20px]">
              {notice && <p className="text-sm text-[#FFC46B]">{notice}</p>}
            </div>

            <button
              type="button"
              disabled={!canStart}
              className="mt-4 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
            >
              면접 준비로
            </button>
            {!canStart && !uploading && (
              <p className="mt-2 text-center text-[13px] text-white/35">
                문서를 하나 이상 올려주세요.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/[0.06] px-5 py-4">
      <dt className="text-[13px] text-white/45">{label}</dt>
      <dd className="mt-1 text-[15px] text-white">{value}</dd>
    </div>
  );
}
