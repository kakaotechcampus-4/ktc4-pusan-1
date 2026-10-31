/**
 * 랜딩 — 로그인하지 않은 사람이 `/` 에서 보는 화면 (#232).
 *
 * 무엇을 하는 서비스인지(면접 전 · 중 · 후), 어떻게 쓰는지(3단계)를 보여 주고
 * 로그인으로 보낸다. 레퍼런스는 brighthire.com — 밝은 바탕에 인디고 · 민트.
 * 숫자 실적이나 고객 로고처럼 근거 없는 말은 쓰지 않는다.
 */

import { Link } from 'react-router-dom';
import evidenceImg from '../assets/illustrations/feature-evidence.webp';
import liveImg from '../assets/illustrations/feature-live.webp';
import prepImg from '../assets/illustrations/feature-prep.webp';
import reviewImg from '../assets/illustrations/feature-review.webp';
import createIcon from '../assets/illustrations/flow-create.webp';
import interviewIcon from '../assets/illustrations/flow-interview.webp';
import reviewIcon from '../assets/illustrations/flow-review.webp';
import heroImg from '../assets/illustrations/hero.webp';
import { buttonClass } from '../components/ui/buttonClass';
import { Logo } from '../components/ui/Logo';

const REPO_URL = 'https://github.com/kakaotechcampus-4/ktc4-pusan-1';

const PRINCIPLES = [
  { icon: 'gavel', text: '합격 여부는 판단하지 않습니다' },
  { icon: 'link', text: '모든 요약에 실제 발화와 시점을 연결합니다' },
  { icon: 'how_to_reg', text: '최종 결정은 면접관이 합니다' },
];

const FEATURES = [
  {
    when: '면접 전',
    title: '이력서와 직무를 미리 읽어 둡니다',
    body: '이력서의 주장과 직무 역량을 뽑아, 면접에서 확인할 거리를 정리해 둡니다.',
    image: prepImg,
  },
  {
    when: '면접 중',
    title: '실시간 자막과 꼬리질문',
    body: '대화를 받아 적고, 더 물어볼 만한 질문을 면접관 화면에만 조용히 제안합니다.',
    image: liveImg,
  },
  {
    when: '면접 후',
    title: '근거가 연결된 면접 기록',
    body: '요약의 항목마다 근거가 된 발화와 녹화 시점을 붙여, 누르면 그 장면으로 이동합니다.',
    image: evidenceImg,
  },
  {
    when: '검토',
    title: '판단은 면접관이',
    body: 'AI 가 짚은 항목을 채택하거나 반려하고, 메모와 함께 검토를 확정합니다.',
    image: reviewImg,
  },
];

const STEPS = [
  {
    icon: createIcon,
    title: '면접 만들기',
    body: '지원자 이름과 이력서를 넣으면 초대 링크가 만들어집니다.',
  },
  {
    icon: interviewIcon,
    title: '화상 면접',
    body: '지원자는 링크로 바로 입장합니다. 설치도 가입도 필요 없습니다.',
  },
  {
    icon: reviewIcon,
    title: '기록 검토',
    body: '녹화 · 타임라인 · AI 검토 항목을 보며 판단을 남깁니다.',
  },
];

export default function LandingPage() {
  return (
    <div className="bg-surface-panel text-ink min-h-full">
      <header className="border-border-base/70 bg-surface-panel/80 sticky top-0 z-30 border-b backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/" aria-label="IRYA 홈">
            <Logo />
          </Link>
          <nav aria-label="랜딩" className="text-ink-muted hidden gap-6 text-[15px] md:flex">
            <a href="#features" className="hover:text-ink">
              기능
            </a>
            <a href="#how" className="hover:text-ink">
              사용 방법
            </a>
          </nav>
          <span className="flex-1" />
          <Link to="/login" className={buttonClass('ghost', 'sm')}>
            로그인
          </Link>
          <Link to="/login" className={buttonClass('primary', 'sm')}>
            시작하기
          </Link>
        </div>
      </header>

      <main>
        {/* 히어로 — 그림 왼쪽이 비어 있어 글을 그 위에 얹는다. 좁은 화면에서는 글 아래로 내린다. */}
        <section className="from-brand-tint via-surface-panel relative overflow-hidden bg-gradient-to-br to-[#effbf8]">
          <div className="mx-auto grid max-w-6xl items-center gap-8 px-4 pt-14 pb-10 sm:px-6 lg:grid-cols-[1fr_1.15fr] lg:pt-20 lg:pb-16">
            <div>
              <p className="border-brand/15 text-brand-strong inline-flex items-center gap-1.5 rounded-full border bg-white/70 px-3 py-1 text-[13px] font-semibold">
                <span aria-hidden className="material-symbols-outlined text-[16px]">
                  auto_awesome
                </span>
                AI 화상면접 지원 서비스
              </p>
              <h1 className="mt-5 text-[40px] leading-[1.15] font-bold tracking-tight sm:text-[52px]">
                면접은 사람이,
                <br />
                <span className="text-brand">정리는 AI가.</span>
              </h1>
              <p className="text-ink-muted mt-5 max-w-md text-[17px] leading-relaxed">
                이력서 분석부터 실시간 꼬리질문, 근거가 연결된 면접 기록까지. IRYA 가 면접관 곁에서
                기록하고 정리합니다.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link to="/login" className={buttonClass('primary', 'lg')}>
                  시작하기
                  <span aria-hidden className="material-symbols-outlined text-[20px]">
                    arrow_forward
                  </span>
                </Link>
                <a href="#features" className={buttonClass('secondary', 'lg')}>
                  기능 둘러보기
                </a>
              </div>
            </div>
            <img
              src={heroImg}
              alt="면접 녹화 · 타임라인 · 검토 항목이 함께 보이는 IRYA 화면"
              width={1600}
              height={800}
              className="w-full [mask-image:linear-gradient(to_right,transparent,black_18%)] object-cover object-right lg:-mr-24 lg:w-[calc(100%+6rem)] lg:max-w-none"
            />
          </div>
        </section>

        <section aria-label="원칙" className="border-border-base border-y">
          <ul className="mx-auto grid max-w-6xl gap-4 px-4 py-6 sm:grid-cols-3 sm:px-6">
            {PRINCIPLES.map((p) => (
              <li key={p.text} className="text-ink-muted flex items-center gap-3 text-[15px]">
                <span
                  aria-hidden
                  className="material-symbols-outlined bg-accent-tint text-accent-strong rounded-lg p-1.5 text-[20px]"
                >
                  {p.icon}
                </span>
                {p.text}
              </li>
            ))}
          </ul>
        </section>

        <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <SectionTitle
            eyebrow="기능"
            title="면접의 앞뒤를 한 흐름으로"
            body="준비 · 진행 · 정리 · 검토를 한곳에서 이어서 합니다."
          />
          <ul className="mt-12 grid gap-6 md:grid-cols-2">
            {FEATURES.map((f) => (
              <li
                key={f.title}
                className="border-border-base bg-surface shadow-card overflow-hidden rounded-3xl border"
              >
                <img
                  src={f.image}
                  alt=""
                  width={696}
                  height={444}
                  loading="lazy"
                  className="aspect-[3/2] w-full object-cover"
                />
                <div className="p-6">
                  <p className="text-brand text-[13px] font-semibold">{f.when}</p>
                  <h3 className="mt-1.5 text-[20px] font-bold">{f.title}</h3>
                  <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">{f.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section id="how" className="bg-surface scroll-mt-20 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <SectionTitle eyebrow="사용 방법" title="세 단계면 충분합니다" />
            <ol className="mt-12 grid gap-6 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li
                  key={s.title}
                  className="border-border-base bg-surface-panel rounded-3xl border p-6"
                >
                  <img src={s.icon} alt="" width={240} height={244} className="h-20 w-20" />
                  <p className="text-ink-dim mt-5 font-mono text-[13px]">STEP {i + 1}</p>
                  <h3 className="mt-1 text-[20px] font-bold">{s.title}</h3>
                  <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="from-brand to-brand-strong relative overflow-hidden rounded-3xl bg-gradient-to-br px-6 py-14 text-center text-white sm:px-12">
            <div
              aria-hidden
              className="bg-accent/40 absolute -top-20 -right-16 h-64 w-64 rounded-full blur-3xl"
            />
            <h2 className="relative text-[28px] leading-tight font-bold sm:text-[34px]">
              다음 면접부터, 기록은 IRYA 에게
            </h2>
            <p className="relative mt-3 text-[16px] text-white/80">
              카카오 계정으로 바로 시작할 수 있습니다.
            </p>
            <Link
              to="/login"
              className={`${buttonClass('secondary', 'lg')} text-brand-strong relative mt-8 border-transparent`}
            >
              시작하기
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-border-base border-t">
        <div className="text-ink-muted mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-[14px] sm:flex-row sm:items-center sm:px-6">
          <div>
            <Logo size="sm" />
            <p className="mt-2">부산대 1팀 · 카카오테크캠퍼스 4기 프로젝트</p>
          </div>
          <span className="flex-1" />
          <nav aria-label="정책" className="flex flex-wrap gap-x-5 gap-y-2">
            <Link to="/terms" className="hover:text-ink">
              이용약관
            </Link>
            <Link to="/privacy" className="hover:text-ink font-semibold">
              개인정보처리방침
            </Link>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:text-ink">
              GitHub
            </a>
          </nav>
        </div>
        <p className="text-ink-dim mx-auto max-w-6xl px-4 pb-8 text-[13px] sm:px-6">© 2026 IRYA</p>
      </footer>
    </div>
  );
}

function SectionTitle({ eyebrow, title, body }: { eyebrow: string; title: string; body?: string }) {
  return (
    <div className="max-w-2xl">
      <p className="text-brand text-[14px] font-semibold">{eyebrow}</p>
      <h2 className="mt-2 text-[30px] leading-tight font-bold tracking-tight sm:text-[36px]">
        {title}
      </h2>
      {body && <p className="text-ink-muted mt-3 text-[17px]">{body}</p>}
    </div>
  );
}
