import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getInterview } from '../../api/interview';
import { useState } from 'react';

export function InvitationActions({ interviewId }: { interviewId: string }) {
  const { data, isError, refetch } = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId),
  });
  const [copyFailed, setCopyFailed] = useState(false);
  const [copied, setCopied] = useState(false);
  const session = data?.latestSession;
  if (isError)
    return (
      <p role="alert" className="text-danger text-sm">
        초대 정보를 읽지 못했습니다.{' '}
        <button type="button" className="underline" onClick={() => void refetch()}>
          다시 확인
        </button>
      </p>
    );
  if (!data)
    return (
      <p role="status" className="text-ink-muted text-sm">
        초대 정보를 확인하고 있습니다.
      </p>
    );
  if (!session) return <p className="text-ink-muted text-sm">아직 발급된 초대 링크가 없습니다.</p>;
  return (
    <section className="border-border-base rounded-xl border p-4">
      <h3 className="text-ink text-sm font-semibold">지원자 초대 링크</h3>
      <input
        readOnly
        aria-label="지원자 초대 링크"
        value={session.inviteUrl}
        onFocus={(event) => event.currentTarget.select()}
        className="border-border-input text-ink mt-2 w-full rounded-lg border p-2 text-sm"
      />
      <div className="mt-3 flex flex-wrap gap-3 text-sm">
        <button
          type="button"
          className="text-brand underline"
          onClick={() => {
            void navigator.clipboard
              .writeText(session.inviteUrl)
              .then(() => {
                setCopied(true);
                setCopyFailed(false);
              })
              .catch(() => setCopyFailed(true));
          }}
        >
          {copied ? '복사했습니다' : '링크 복사'}
        </button>
        {session.status !== 'ENDED' ? (
          <>
            <a href={session.inviteUrl} className="text-brand underline">
              지원자 입장
            </a>
            <Link
              to={`/interview/${session.sessionId}?role=interviewer`}
              className="text-brand underline"
            >
              면접관 입장
            </Link>
          </>
        ) : (
          <span className="text-ink-muted">종료된 면접입니다.</span>
        )}
      </div>
      {copyFailed && (
        <p role="status" className="text-warning mt-2 text-xs">
          링크를 선택해 직접 복사해 주세요.
        </p>
      )}
    </section>
  );
}
