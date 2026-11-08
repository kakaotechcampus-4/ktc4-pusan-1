/**
 * 본문 바로가기 (KWCAG 반복 영역 건너뛰기).
 *
 * 화면 맨 앞에 두고 평소에는 숨기며 Tab 으로 들어오면 보인다. 주소에 #이 붙어
 * 라우터 기록이 늘지 않도록 이동은 직접 하고, 본문(`#main-content`)에 초점을 준다.
 */
export function SkipLink() {
  return (
    <a
      href="#main-content"
      onClick={(event) => {
        const main = document.getElementById('main-content');
        if (!main) return;
        event.preventDefault();
        main.focus();
        main.scrollIntoView();
      }}
      className="focus:bg-brand sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[100] focus:rounded-lg focus:px-4 focus:py-2.5 focus:text-sm focus:font-semibold focus:text-white"
    >
      본문 바로가기
    </a>
  );
}
