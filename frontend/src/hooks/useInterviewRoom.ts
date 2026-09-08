/**
 * 통화 연결 — 방 접속, 1:1 트랙 구독, 녹화
 *
 * 녹화는 LiveKit Egress로 서버에서 수행한다.
 * 클라이언트 MediaRecorder는 쓰지 않는다 — 브라우저가 닫히면 유실되고,
 * stream(전사) 연결과 무관하게 녹화가 유지돼야 한다.
 *
 * 카메라·마이크 권한은 usePermissionCheck 가 접속 전에 확인한다.
 * 여기서는 그 트랙을 발행하기만 한다 — 권한 프롬프트를 두 번 띄우지 않기 위해서다.
 */

import {
  RemoteParticipant,
  Room,
  RoomEvent,
  Track,
  type LocalAudioTrack,
  type LocalVideoTrack,
  type RemoteTrack,
  type RemoteTrackPublication,
} from 'livekit-client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError } from '../api/client';
import { endSession, joinSession } from '../api/interview';
import { useInterviewStore } from '../stores/interviewStore';
import type { Role } from '../types/interview';
import { AUDIO_CAPTURE, VIDEO_CAPTURE } from './usePermissionCheck';

interface UseInterviewRoomOptions {
  /** 초대 링크에서 받은 세션 식별자. join 이 이걸로 토큰을 발급한다 */
  sessionId: string;
  /** 입장 권한. 현재는 클라이언트가 선언한다 (인증 도입 전 임시 구조) */
  role: Role;
  /** 지원자 비디오를 붙일 요소 */
  videoRef: RefObject<HTMLVideoElement | null>;
  /** 지원자 오디오를 붙일 요소 */
  audioRef: RefObject<HTMLAudioElement | null>;
  /**
   * 발행할 트랙이 준비됐을 때만 true. false 면 접속하지 않는다.
   * 권한이 거부된 채로 방에 들어가면 아무것도 발행하지 못하면서
   * 정원 2명 중 한 자리를 차지한다.
   */
  ready: boolean;
  /** 프리뷰에서 확보한 트랙 — 다시 요청하지 않고 그대로 발행한다 */
  videoTrack: LocalVideoTrack | null;
  audioTrack: LocalAudioTrack | null;
  /** 발행 성공 시 호출 — 트랙 소유권이 Room 으로 넘어갔음을 알린다 */
  onTracksPublished: () => void;
}

export function useInterviewRoom({
  sessionId,
  role,
  videoRef,
  audioRef,
  ready,
  videoTrack,
  audioTrack,
  onTracksPublished,
}: UseInterviewRoomOptions) {
  const roomRef = useRef<Room | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 트랙과 콜백을 deps 에 넣으면 트랙 도착이나 콜백 교체마다 재접속이 일어난다.
  // 최신 값을 ref 로 넘겨 이펙트 안에서만 읽는다.
  const latestRef = useRef({ videoTrack, audioTrack, onTracksPublished });
  useEffect(() => {
    latestRef.current = { videoTrack, audioTrack, onTracksPublished };
  });

  useEffect(() => {
    // 권한 확인이 접속보다 먼저라는 것을 구조로 보장한다.
    if (!ready) return;

    // 액션은 참조가 고정되어 있다. 구독하면 전사 델타마다 화면 전체가 리렌더되므로
    // 훅에서는 getState() 로 꺼내 쓰고 스토어를 구독하지 않는다.
    const { setSession, setConnection, setCandidateJoined, setSpeaking, reset } =
      useInterviewStore.getState();

    let cancelled = false;

    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
      // 프리뷰에서 잡은 트랙과 설정이 어긋나지 않게 같은 상수를 쓴다.
      videoCaptureDefaults: VIDEO_CAPTURE,
      audioCaptureDefaults: AUDIO_CAPTURE,
    });
    roomRef.current = room;

    /* 지원자 트랙 붙이기 — participant는 2명뿐이므로 원격 참가자는 항상 지원자다 */
    const attach = (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Video && videoRef.current) {
        track.attach(videoRef.current);
      }
      if (track.kind === Track.Kind.Audio && audioRef.current) {
        track.attach(audioRef.current);
      }
    };

    room
      .on(RoomEvent.ConnectionStateChanged, setConnection)
      .on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => attach(track))
      .on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach())
      .on(RoomEvent.ParticipantConnected, () => setCandidateJoined(true))
      .on(RoomEvent.ParticipantDisconnected, () => {
        setCandidateJoined(false);
        setSpeaking(null);
      })
      // 발화 중 화자 표시. 서버 speech.start와 별개로 즉시 반응한다.
      .on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        if (speakers.length === 0) {
          setSpeaking(null);
          return;
        }
        const isRemote = speakers.some((p) => p instanceof RemoteParticipant);
        setSpeaking(isRemote ? 'candidate' : 'interviewer');
      })
      .on(RoomEvent.Disconnected, () => setCandidateJoined(false));

    void (async () => {
      try {
        // join 이 입장 권한 확인과 LiveKit 접속 정보 발급을 함께 한다.
        // start 는 상태 전이 전용이라 여기서 부르지 않는다.
        const { livekitUrl, token } = await joinSession(sessionId, role);
        if (cancelled) return;
        setSession(sessionId);

        /* --- 방 접속 --- */
        await room.connect(livekitUrl, token);
        if (cancelled) return;

        /* 면접관 트랙 발행 — 프리뷰에서 이미 얻은 트랙을 재사용한다.
           enableCameraAndMicrophone() 을 쓰면 getUserMedia 가 다시 불려
           권한 프롬프트가 두 번 뜬다. */
        const { videoTrack, audioTrack, onTracksPublished } = latestRef.current;
        try {
          // 오디오를 먼저 올린다 — 대화와 전사가 영상보다 우선이다.
          if (audioTrack) {
            await room.localParticipant.publishTrack(audioTrack, {
              source: Track.Source.Microphone,
            });
          }
          if (videoTrack) {
            await room.localParticipant.publishTrack(videoTrack, {
              source: Track.Source.Camera,
              simulcast: true,
            });
          }

          if (cancelled) {
            // cleanup 의 disconnect() 가 발행 완료보다 먼저 지나갔을 수 있다. 직접 회수한다.
            audioTrack?.stop();
            videoTrack?.stop();
            return;
          }

          // 여기서만 소유권이 넘어간다. 이후 트랙 stop 은 room.disconnect() 가 한다.
          onTracksPublished();
        } catch (e) {
          // 발행 실패가 통화를 막지는 않는다 — 지원자 영상과 전사는 계속 본다.
          // setError 를 세우면 화면 전체가 실패 오버레이로 덮인다.
          console.warn('로컬 트랙 발행 실패', e);
        }

        /* 이미 들어와 있는 지원자 트랙 구독 */
        room.remoteParticipants.forEach((p) => {
          setCandidateJoined(true);
          p.trackPublications.forEach((pub: RemoteTrackPublication) => {
            if (pub.track) attach(pub.track);
          });
        });

        /* --- 전사·추천 질문 연결 ---
           BE 명세(docs/api)에 WebSocket 경로가 없어 아직 연결하지 않는다 (AI #7).
           경로가 생기면 여기서 붙인다 — 통화와 분리해 두어 전사가 죽어도 통화는 유지된다. */
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.code : 'CONNECT_FAILED');
        }
      }
    })();

    return () => {
      cancelled = true;
      room.removeAllListeners();
      void room.disconnect();
      reset();
    };
  }, [sessionId, role, videoRef, audioRef, ready]);

  const leave = async () => {
    const { sessionId } = useInterviewStore.getState();
    await roomRef.current?.disconnect();
    if (sessionId) return endSession(sessionId);
    return null;
  };

  // roomRef.current 를 렌더 중에 읽으면 연결 이후 값이 갱신되지 않는다.
  // ref 자체를 넘겨 이벤트 핸들러·이펙트 안에서 읽게 한다.
  return { roomRef, error, leave };
}
