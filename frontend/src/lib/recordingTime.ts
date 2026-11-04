/**
 * 전사 시각 ↔ 녹화 재생 위치 변환.
 *
 * 두 시간축이 다르다. 타임라인의 `atSec` 은 전사 원점(t=0) 기준이고, `<video>` 의
 * `currentTime` 은 녹화 파일의 0초 기준이다. 녹화는 LiveKit Egress 가 키프레임을
 * 기다린 뒤 시작하므로 전사보다 늦게 열린다 — 그 차이가 `offsetMs` 다.
 *
 * 명세: 「녹화의 0초가 전사 원점보다 얼마나 뒤인가. 전사 시각 t(ms) 의 장면은
 * 녹화의 `t − offsetMs` 에 있다.」
 *
 * 보정을 빼먹으면 모든 질문이 오프셋만큼 뒤 장면으로 재생된다. 눈에 잘 띄지 않는
 * 종류의 어긋남이라(몇 초 차이) 계산만 따로 떼어 테스트로 묶어 둔다.
 */

/** 전사 기준 초 → 녹화 재생 위치(초) */
export function toVideoSec(atSec: number, offsetMs: number): number {
  // 녹화가 그 장면보다 늦게 시작했으면 파일 안에 없다. 0 으로 당겨 맨 앞을 보여준다 —
  // 음수를 넣으면 브라우저가 무시해 재생 위치가 엉뚱한 곳에 남는다.
  return Math.max(0, atSec - offsetMs / 1000);
}

/** 녹화 재생 위치(초) → 전사 기준 초. 화면에 적는 시각은 전사 기준으로 맞춘다 */
export function toTranscriptSec(videoSec: number, offsetMs: number): number {
  return Math.max(0, videoSec + offsetMs / 1000);
}
