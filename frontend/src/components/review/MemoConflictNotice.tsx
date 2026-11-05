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
      <p>
        서버 메모와 저장 기준을 확인해야 합니다. 입력 내용은 현재 화면에 남아 있습니다. 충돌 해결
        전까지 입력은 자동저장되지 않습니다.
      </p>
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
      <button
        type="button"
        disabled={busy}
        onClick={() => void run(reapply)}
        className="ml-3 min-h-11 px-1 underline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        작성한 내용으로 다시 저장
      </button>
      {failed && (
        <p>메모를 확인하거나 저장하지 못했습니다. 입력 내용을 유지한 채 다시 시도해 주세요.</p>
      )}
    </div>
  );
}
