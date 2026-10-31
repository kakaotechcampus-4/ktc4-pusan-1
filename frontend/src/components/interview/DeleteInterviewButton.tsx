/**
 * 면접 삭제 버튼 (#246)
 *
 * 되돌릴 수 없으니 두 단계로 받는다 — 버튼을 누르면 무엇이 같이 사라지는지 적힌 창이
 * 열리고, 거기서 한 번 더 눌러야 지운다.
 *
 * 목록(S4)과 면접 기록(S3)이 같이 쓴다. 지운 뒤 할 일은 화면마다 달라서(목록은
 * 미리보기를 닫고, 기록은 목록으로 나간다) `onDeleted` 로 받는다.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { deleteInterview } from '../../api/interview';
import { DELETE_FAILURE_MESSAGE, deleteFailure } from '../../lib/interviewDelete';
import { toast, type ToastTone } from '../../lib/toast';
import { buttonClass, type ButtonSize } from '../ui/buttonClass';

interface Props {
  interviewId: string;
  /** 확인 창에 적을 이름. 어느 면접을 지우는지 알려주는 유일한 단서다. */
  candidateName: string;
  size?: ButtonSize;
  className?: string;
  onDeleted?: () => void;
}

export function DeleteInterviewButton({
  interviewId,
  candidateName,
  size = 'sm',
  className = '',
  onDeleted,
}: Props) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setAsking(true)}
        className={`${buttonClass('danger', size)} ${className}`}
      >
        <span aria-hidden className="material-symbols-outlined text-[18px]">
          delete
        </span>
        면접 삭제
      </button>
      {/* 열 때 새로 올린다 — `showModal()` 이 한 번만 돌게 (`InterviewNavigationDialog`). */}
      {asking && (
        <ConfirmDialog
          interviewId={interviewId}
          candidateName={candidateName}
          onClose={() => setAsking(false)}
          onDeleted={onDeleted}
        />
      )}
    </>
  );
}

function ConfirmDialog({
  interviewId,
  candidateName,
  onClose,
  onDeleted,
}: {
  interviewId: string;
  candidateName: string;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  /**
   * 목록을 다시 받고 창을 닫는다. 지운 면접의 캐시는 버린다 — 남겨 두면 뒤로 가기로
   * 기록 화면에 돌아왔을 때 지운 면접이 먼저 그려진다.
   */
  const finish = (message: string, tone: ToastTone = 'success') => {
    void queryClient.invalidateQueries({ queryKey: ['interviews'] });
    queryClient.removeQueries({ queryKey: ['review', interviewId] });
    queryClient.removeQueries({ queryKey: ['interview', interviewId] });
    toast(message, tone);
    onClose();
    onDeleted?.();
  };

  const remove = useMutation({
    mutationFn: () => deleteInterview(interviewId),
    onSuccess: () => finish('면접을 지웠습니다.'),
    onError: (e) => {
      const failure = deleteFailure(e instanceof ApiError ? e.status : undefined);
      // 이미 없는 면접이면 지운 것과 결과가 같다. 목록만 맞추고 끝낸다.
      if (failure === 'gone') {
        finish(DELETE_FAILURE_MESSAGE.gone, 'info');
        return;
      }
      setError(DELETE_FAILURE_MESSAGE[failure]);
    },
  });

  return (
    <dialog
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="delete-interview-title"
      className="border-border-base bg-surface-panel text-ink shadow-pop backdrop:bg-ink/30 m-auto w-[min(440px,calc(100%-32px))] rounded-2xl border p-6"
    >
      <h2 id="delete-interview-title" className="text-ink text-[18px] font-bold">
        면접을 지울까요?
      </h2>
      <p className="text-ink-muted mt-2 text-[14px] leading-relaxed">
        <span className="text-ink font-semibold">{candidateName}</span> 면접의 녹화 · 문답 · 요약 ·
        메모가 모두 지워집니다. 되돌릴 수 없습니다.
      </p>
      {error && (
        <p role="status" className="text-warning mt-3 text-sm">
          {error}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={remove.isPending}
          className={buttonClass('secondary', 'sm')}
        >
          취소
        </button>
        <button
          type="button"
          onClick={() => {
            setError(null);
            remove.mutate();
          }}
          disabled={remove.isPending}
          className={buttonClass('danger', 'sm')}
        >
          {remove.isPending ? '지우는 중…' : '지우기'}
        </button>
      </div>
    </dialog>
  );
}
