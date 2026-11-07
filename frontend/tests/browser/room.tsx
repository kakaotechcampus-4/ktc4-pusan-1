import { useEffect, useRef, useState } from 'react';
import type { Room } from 'livekit-client';
import { InterviewRoomView } from '../../src/components/interview/InterviewRoomView';
import { useInterviewRoom } from '../../src/hooks/useInterviewRoom';
import type { Role } from '../../src/types/interview';
import '../../src/index.css';

// 실제 기기·STT 품질 대신 인공 트랙으로 실제 로컬 LiveKit 송수신과 화면 조작을 검증한다.
declare global {
  interface Window {
    __iryaQaRoom?: { current: Room | null };
    __iryaQaRead?: () => unknown;
  }
}
const params = new URLSearchParams(location.search);
const sessionId = params.get('sessionId') || 'ses_qa_live';
const role: Role = params.get('role') === 'CANDIDATE' ? 'CANDIDATE' : 'INTERVIEWER';

function Connected({
  video,
  audio,
  onEnded,
}: {
  video: MediaStreamTrack;
  audio: MediaStreamTrack;
  onEnded: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const connected = useInterviewRoom({
    sessionId,
    role,
    videoRef,
    audioRef,
    ready: true,
    videoTrack: video,
    audioTrack: audio,
    onSessionEnded: onEnded,
  });
  const [ending, setEnding] = useState(false);
  useEffect(() => {
    window.__iryaQaRoom = connected.roomRef;
    window.__iryaQaRead = () => {
      const room = connected.roomRef.current;
      return {
        state: room?.state,
        microphone: room?.localParticipant.isMicrophoneEnabled,
        camera: room?.localParticipant.isCameraEnabled,
        remote: [...(room?.remoteParticipants.values() || [])].map((participant) => ({
          identity: participant.identity,
          microphone: participant.isMicrophoneEnabled,
          camera: participant.isCameraEnabled,
        })),
        videoPlaying: Boolean(videoRef.current?.videoWidth),
        audioMuted: audioRef.current?.muted,
      };
    };
  }, [connected.roomRef]);
  return (
    <InterviewRoomView
      role={role}
      interviewId={connected.interviewId}
      consent={connected.consent}
      remoteName={role === 'INTERVIEWER' ? '검증 지원자' : '검증 면접관'}
      videoRef={videoRef}
      audioRef={audioRef}
      localVideoTrack={connected.previewVideo}
      localAudioTrack={audio}
      error={connected.error}
      ending={ending}
      notice={connected.mediaNotice ?? undefined}
      media={{ ...connected.media, onToggle: (kind) => void connected.toggleMedia(kind) }}
      onEnd={() => {
        setEnding(true);
        void connected
          .leave()
          .then(onEnded)
          .finally(() => setEnding(false));
      }}
    />
  );
}
export default function Fixture() {
  const [tracks, setTracks] = useState<{
    video: MediaStreamTrack;
    audio: MediaStreamTrack;
    cleanup: () => void;
  } | null>(null);
  useEffect(() => () => tracks?.cleanup(), [tracks]);
  const start = async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 960;
    canvas.height = 540;
    const ctx = canvas.getContext('2d')!;
    const draw = () => {
      ctx.fillStyle =
        role === 'CANDIDATE' ? (params.get('scene') === 'dark' ? '#0b0e1c' : '#f7f8fb') : '#25315c';
      ctx.fillRect(0, 0, 960, 540);
      ctx.fillStyle =
        role === 'CANDIDATE' && params.get('scene') !== 'dark' ? '#141826' : '#ffffff';
      ctx.font = '32px sans-serif';
      ctx.fillText(`${role} · local integration`, 45, 100);
      ctx.fillText(new Date().toISOString(), 45, 160);
    };
    draw();
    const timer = setInterval(draw, 150);
    const context = new AudioContext();
    await context.resume();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    gain.gain.value = 0.001;
    const destination = context.createMediaStreamDestination();
    oscillator.connect(gain);
    gain.connect(destination);
    oscillator.start();
    const video = canvas.captureStream(10).getVideoTracks()[0];
    const audio = destination.stream.getAudioTracks()[0];
    setTracks({
      video,
      audio,
      cleanup: () => {
        clearInterval(timer);
        video.stop();
        audio.stop();
        oscillator.stop();
        void context.close();
      },
    });
  };
  return tracks ? (
    <Connected {...tracks} onEnded={() => setTracks(null)} />
  ) : (
    <main style={{ padding: 40 }}>
      <h1>통화 컴포넌트 검증</h1>
      <p>
        로컬 테스트 서버의 인공 음성·영상입니다. 실제 카메라·마이크 또는 STT/LLM 품질 검증이
        아닙니다.
      </p>
      <button type="button" onClick={() => void start()} style={{ padding: 16 }}>
        검증용 트랙으로 연결
      </button>
    </main>
  );
}
