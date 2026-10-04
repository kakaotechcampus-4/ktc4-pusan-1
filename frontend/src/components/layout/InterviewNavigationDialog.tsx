import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getInterview, getSessionState } from '../../api/interview';
import { ApiError } from '../../api/client';
import type { Role } from '../../types/interview';

export function InterviewNavigationDialog({
  mode,
  onClose,
}: {
  mode: 'room' | 'summary' | 'review';
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelled = useRef(false);
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const [role, setRole] = useState<Role>('INTERVIEWER');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const title = mode === 'room' ? '면접 입장' : mode === 'summary' ? '면접 요약' : '면접 기록';

  useEffect(() => {
    cancelled.current = false;
    dialog.current?.showModal();
    return () => {
      cancelled.current = true;
    };
  }, []);

  const open = async () => {
    setBusy(true);
    setError('');
    try {
      const raw = value.trim();
      // 새 면접을 만들지 않는다. 기존 초대·기록 링크나 화면에 표시된 ID만 조회한다.
      const url = new URL(raw, window.location.origin);
      const linked = /^\/(interview|review)\/([^/]+)(?:\/summary)?\/?$/.exec(url.pathname);
      const id = linked ? decodeURIComponent(linked[2]) : raw;
      if (!id || /[\s/\\?#]/.test(id)) throw new Error('초대 링크 또는 면접 ID를 확인해주세요.');
      let path: string;
      if (mode === 'review' && (linked?.[1] === 'review' || id.startsWith('int_'))) {
        await getInterview(id);
        path = `/review/${encodeURIComponent(id)}`;
      } else {
        const session = await getSessionState(id);
        if (mode === 'room') {
          if (session.status === 'ENDED') throw new Error('이미 종료된 면접입니다.');
          path = `/interview/${encodeURIComponent(id)}${role === 'INTERVIEWER' ? '?role=interviewer' : ''}`;
        } else if (mode === 'summary') {
          if (session.status !== 'ENDED')
            throw new Error('면접이 종료된 뒤 요약을 확인할 수 있습니다.');
          path = `/interview/${encodeURIComponent(id)}/summary`;
        } else {
          path = `/review/${encodeURIComponent(session.interviewId)}`;
        }
      }
      if (cancelled.current) return;
      onClose();
      void navigate(path);
    } catch (e) {
      if (cancelled.current) return;
      setError(
        e instanceof ApiError
          ? e.status === 404
            ? '면접 정보를 찾을 수 없습니다.'
            : '면접 정보를 확인하지 못했습니다. 다시 시도해주세요.'
          : e instanceof Error
            ? e.message
            : '링크를 확인해주세요.',
      );
    } finally {
      if (!cancelled.current) setBusy(false);
    }
  };

  return (
    <dialog
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="interview-navigation-title"
      className="border-border-base bg-surface-panel text-ink m-auto w-[min(440px,calc(100%-32px))] rounded-xl border p-6 backdrop:bg-black/70"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void open();
        }}
        className="flex flex-col gap-4"
      >
        <h2 id="interview-navigation-title" className="text-lg font-semibold">
          {title}
        </h2>
        <label className="flex flex-col gap-2 text-sm">
          {mode === 'review' ? '초대 링크·기록 링크 또는 면접 ID' : '초대 링크 또는 세션 ID'}
          <input
            autoFocus
            required
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError('');
            }}
            className="border-border-base bg-surface-input rounded-lg border px-3 py-2.5"
          />
        </label>
        {mode === 'room' && (
          <label className="flex flex-col gap-2 text-sm">
            입장 역할
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="border-border-base bg-surface-input rounded-lg border px-3 py-2.5"
            >
              <option value="INTERVIEWER">면접관</option>
              <option value="CANDIDATE">지원자</option>
            </select>
          </label>
        )}
        <p role="status" className="text-sm text-[#FFC46B]">
          {error}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="border-border-base rounded-lg border px-4 py-2"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={busy}
            className="bg-brand rounded-lg px-4 py-2 text-white disabled:opacity-50"
          >
            {busy ? '확인 중…' : '열기'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
