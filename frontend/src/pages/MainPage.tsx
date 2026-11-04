/**
 * 대시보드 — 로그인 후 첫 화면 (#232).
 *
 * 「지금 무엇을 하면 되는지」를 먼저 보여 준다. 할 일은 서버 값에서 고른다.
 *   - 기업 설정에 등록된 문서가 없으면 → 설정하러 가기
 *   - 정리가 끝났는데 확정하지 않은 면접 → 검토하러 가기
 *   - AI 가 아직 정리 중인 면접 → 기다리면 된다는 안내
 * 그 아래에 숫자 셋과 최근 면접 몇 건을 둔다. 전체 목록은 지원자 화면이 맡는다.
 *
 * 기업 설정은 선택이다. 문서가 없어도 면접을 만들 수 있게 두고, 권하기만 한다.
 */

import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getMe } from '../api/auth';
import { getCurrentContext } from '../api/context';
import { listInterviews } from '../api/interview';
import emptyInterviews from '../assets/illustrations/empty-interviews.webp';
import emptyReview from '../assets/illustrations/empty-review.webp';
import { Badge } from '../components/ui/Badge';
import { buttonClass } from '../components/ui/buttonClass';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { Skeleton } from '../components/ui/Skeleton';
import { useAccessToken } from '../hooks/useAccessToken';
import { FALLBACK_CANDIDATE } from '../lib/candidateName';
import { STATUS_LABEL, STATUS_TONE } from '../lib/interviewList';
import type { InterviewListItem } from '../types/interview';

/** 최근 면접은 몇 건만 — 더 보려면 지원자 화면으로 간다 */
const RECENT = 5;

const dateLabel = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));

/** 정리는 끝났고(실패 포함) 면접관이 아직 확정하지 않은 면접 — 검토할 차례다 */
const needsReview = (item: InterviewListItem) =>
  (item.summaryStatus === 'READY' || item.summaryStatus === 'FAILED') &&
  item.reviewStatus !== 'CONFIRMED';

export default function MainPage() {
  const token = useAccessToken();
  // RequireAuth 가 이미 불러 둔 값을 그대로 쓴다 — 같은 키라 요청이 더 나가지 않는다.
  const { data: me } = useQuery({ queryKey: ['me', token], queryFn: getMe });

  const context = useQuery({ queryKey: ['context'], queryFn: getCurrentContext });
  // 지원자 화면과 같은 키다. 오가며 다시 받지 않고, 한쪽에서 바뀌면 같이 바뀐다.
  const interviews = useQuery({ queryKey: ['interviews'], queryFn: listInterviews });

  const items = interviews.data?.items ?? [];
  const toReview = items.filter(needsReview);
  const processing = items.filter((i) => i.summaryStatus === 'PROCESSING');
  // ready는 서버에 등록된 문서다. 본문 추출 완료 여부는 이 응답으로 알 수 없다.
  const contextReady = Boolean(context.data?.docs.some((d) => d.status === 'ready'));
  const contextMissing = context.isSuccess && !contextReady;
  const loading = interviews.isLoading || context.isLoading;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
      <header className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-ink text-[26px] font-bold tracking-tight">
            안녕하세요{me ? `, ${me.nickname}님` : ''}
          </h1>
          <p className="text-ink-muted mt-1 text-[15px]">오늘 할 일을 정리해 두었습니다.</p>
        </div>
        <span className="flex-1" />
        {/* 좁은 화면은 아래 탭, 넓은 화면은 사이드바에 같은 버튼이 있어 그 사이 폭에서만 둔다.
            버튼 클래스의 inline-flex 가 hidden 을 이기므로 보이고 숨기는 일은 감싸개가 한다. */}
        <div className="hidden sm:block lg:hidden">
          <Link to="/interviews/new" className={buttonClass('primary')}>
            <span aria-hidden className="material-symbols-outlined text-[20px]">
              add
            </span>
            새 면접 만들기
          </Link>
        </div>
      </header>

      <dl className="mt-7 grid grid-cols-3 gap-3">
        <Stat label="전체 면접" value={interviews.data && items.length} />
        <Stat label="검토할 면접" value={interviews.data && toReview.length} highlight />
        <Stat
          label="확정"
          value={interviews.data && items.filter((i) => i.reviewStatus === 'CONFIRMED').length}
        />
      </dl>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Card>
            <h2 className="text-ink text-[17px] font-semibold">오늘 할 일</h2>

            {loading ? (
              <div className="mt-4 flex flex-col gap-3">
                <Skeleton className="h-16" />
                <Skeleton className="h-16" />
              </div>
            ) : interviews.isError || context.isError ? (
              <LoadError
                onRetry={() => {
                  void interviews.refetch();
                  void context.refetch();
                }}
              />
            ) : !contextMissing && toReview.length === 0 && processing.length === 0 ? (
              <EmptyState
                image={emptyReview}
                title="지금 할 일이 없습니다"
                description="새 면접을 만들거나, 끝난 면접의 정리가 끝나면 여기에 나타납니다."
              />
            ) : (
              <ul className="mt-4 flex flex-col gap-3">
                {contextMissing && (
                  <Todo
                    to="/settings/context"
                    icon="apartment"
                    tone="warning"
                    title="기업 설정을 마쳐 주세요"
                    body="직무 기술서나 회사 문서를 올리면 AI 가 그 내용을 근거로 질문과 요약을 만듭니다."
                  />
                )}
                {toReview.length > 0 && (
                  <Todo
                    to={
                      toReview.length === 1 ? `/review/${toReview[0].interviewId}` : '/candidates'
                    }
                    icon="fact_check"
                    tone="brand"
                    title={`검토할 면접 ${toReview.length}건`}
                    body={toReview
                      .slice(0, 3)
                      .map((i) => i.candidateName ?? FALLBACK_CANDIDATE)
                      .join(', ')
                      .concat(toReview.length > 3 ? ` 외 ${toReview.length - 3}명` : '')}
                  />
                )}
                {processing.length > 0 && (
                  <Todo
                    icon="hourglass_top"
                    tone="neutral"
                    title={`AI 가 정리 중인 면접 ${processing.length}건`}
                    body="정리가 끝나면 검토할 면접으로 옮겨집니다. 기다리기만 하면 됩니다."
                  />
                )}
              </ul>
            )}
          </Card>

          <Card>
            <div className="flex items-center">
              <h2 className="text-ink text-[17px] font-semibold">최근 면접</h2>
              <span className="flex-1" />
              {items.length > 0 && (
                <Link to="/candidates" className="text-brand -my-1 py-1 text-[14px] font-semibold">
                  전체 보기
                </Link>
              )}
            </div>

            {interviews.isLoading ? (
              <div className="mt-4 flex flex-col gap-2">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </div>
            ) : interviews.data && items.length === 0 ? (
              <EmptyState
                image={emptyInterviews}
                title="아직 만든 면접이 없습니다"
                description="지원자 이름과 이력서를 넣으면 초대 링크가 만들어집니다."
                action={
                  <Link to="/interviews/new" className={buttonClass('primary')}>
                    첫 면접 만들기
                  </Link>
                }
              />
            ) : (
              <ul className="divide-border-base mt-2 divide-y">
                {items.slice(0, RECENT).map((item) => (
                  <li key={item.interviewId}>
                    <Link
                      to={`/review/${item.interviewId}`}
                      className="hover:bg-surface-container -mx-2 flex items-center gap-3 rounded-lg px-2 py-3.5"
                    >
                      <span className="bg-brand-tint text-brand flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[14px] font-bold">
                        {(item.candidateName ?? FALLBACK_CANDIDATE).slice(0, 1)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="text-ink block truncate text-[15px] font-semibold">
                          {item.candidateName ?? FALLBACK_CANDIDATE}
                        </span>
                        <span className="text-ink-dim block truncate text-[13px]">
                          {[
                            item.role,
                            item.interviewedAt ? dateLabel(item.interviewedAt) : '아직 진행 전',
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <Badge tone={STATUS_TONE[item.reviewStatus]}>
                        {STATUS_LABEL[item.reviewStatus]}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card className="self-start">
          <div className="flex items-center gap-2">
            <h2 className="text-ink text-[17px] font-semibold">기업 설정</h2>
            <span className="flex-1" />
            {context.data && (
              <Badge tone={contextReady ? 'accent' : 'warning'}>
                {contextReady ? '준비됨' : '문서 없음'}
              </Badge>
            )}
          </div>
          {context.isLoading ? (
            <Skeleton className="mt-4 h-20" />
          ) : context.data ? (
            <>
              <dl className="mt-4 flex flex-col gap-2.5 text-[14px]">
                <Row label="회사" value={context.data.company} />
                <Row label="팀" value={context.data.team} />
                <Row label="직무" value={context.data.role} />
                <Row label="문서" value={`${context.data.docs.length}개`} />
              </dl>
              <p className="text-ink-dim mt-4 text-[13px] leading-relaxed">
                면접 질문과 요약은 이 설정을 근거로 만들어집니다.
              </p>
            </>
          ) : null}
          <Link to="/settings/context" className={`${buttonClass('secondary', 'sm')} mt-5 w-full`}>
            설정 열기
          </Link>
        </Card>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  /** 아직 모르면 undefined — 0 으로 적으면 「세어 봤더니 없다」로 읽힌다 */
  value: number | undefined;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border p-4 sm:p-5 ${
        highlight ? 'border-brand/20 bg-brand-tint' : 'border-border-base bg-surface-panel'
      }`}
    >
      <dt className={`text-[13px] ${highlight ? 'text-brand-strong' : 'text-ink-muted'}`}>
        {label}
      </dt>
      <dd
        className={`mt-1 text-[26px] font-bold tabular-nums ${highlight ? 'text-brand-strong' : 'text-ink'}`}
      >
        {value ?? '–'}
      </dd>
    </div>
  );
}

const TODO_TONE = {
  warning: 'bg-warning-tint text-warning',
  brand: 'bg-brand-tint text-brand',
  neutral: 'bg-surface-bright text-ink-muted',
};

function Todo({
  to,
  icon,
  tone,
  title,
  body,
}: {
  /** 없으면 할 수 있는 일이 없는 안내라 누를 수 없다 */
  to?: string;
  icon: string;
  tone: keyof typeof TODO_TONE;
  title: string;
  body: string;
}) {
  const inner: ReactNode = (
    <>
      {/* Google Fonts 의 아이콘 CSS 가 inline-block 을 레이어 밖에서 줘서 아이콘에 직접 건
          flex 가 지고 아이콘이 왼쪽 위로 쏠린다. 가운데 맞춤은 감싸개가 한다. */}
      <span
        aria-hidden
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${TODO_TONE[tone]}`}
      >
        <span className="material-symbols-outlined text-[22px]">{icon}</span>
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-ink block text-[15px] font-semibold">{title}</span>
        <span className="text-ink-muted mt-0.5 block text-[14px] leading-relaxed">{body}</span>
      </span>
      {to && (
        <span aria-hidden className="material-symbols-outlined text-ink-dim text-[22px]">
          chevron_right
        </span>
      )}
    </>
  );
  const box = 'border-border-base flex items-center gap-4 rounded-xl border p-4';
  return (
    <li>
      {to ? (
        <Link to={to} className={`${box} hover:bg-surface-container transition-colors`}>
          {inner}
        </Link>
      ) : (
        <div className={box}>{inner}</div>
      )}
    </li>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <dt className="text-ink-dim w-10 shrink-0">{label}</dt>
      <dd className={value ? 'text-ink' : 'text-ink-dim'}>{value || '미입력'}</dd>
    </div>
  );
}

function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="text-ink-muted mt-4 text-[14px]">
      <p>정보를 불러오지 못했습니다.</p>
      <button type="button" onClick={onRetry} className="text-brand mt-2 font-semibold">
        다시 시도
      </button>
    </div>
  );
}
