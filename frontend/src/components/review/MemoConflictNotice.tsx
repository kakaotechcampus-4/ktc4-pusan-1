import { useState } from 'react';

export function MemoConflictNotice({
  serverMemo,
  readConflict,
  reapply,
}: {
  serverMemo?: string;
  readConflict: () => Promise<void>;
  reapply: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setFailed(false);
    try {
      await action();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div role="alert" className="text-warning mt-2 text-sm">
      <p>다른 창에서 메모가 바뀌었습니다. 작성한 내용은 보관 중입니다.</p>
      {serverMemo !== undefined && (
        <div className="mt-2">
          <p className="font-semibold">현재 서버 메모</p>
          <p className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap">
            {serverMemo || '메모 없음'}
          </p>
        </div>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={() => void run(readConflict)}
        className="min-h-11 px-1 underline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        서버 메모 확인
      </button>
      {serverMemo !== undefined && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void run(reapply)}
          className="ml-3 min-h-11 px-1 underline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          작성한 내용으로 다시 저장
        </button>
      )}
      {failed && <p>메모를 확인하지 못했습니다. 다시 시도해 주세요.</p>}
    </div>
  );
}
