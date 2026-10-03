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

import type { RemoteTrack, RemoteTrackPublication } from 'livekit-client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError } from '../api/client';
import { endSession, getSessionState, joinSession, startSession } from '../api/interview';
import { loadLiveKit } from '../lib/livekit';
import { createTranscriptStreamHandler, TRANSCRIPT_TOPIC } from '../lib/transcriptStream';
import { useInterviewStore } from '../stores/interviewStore';
import type { Role, RoomConnectionState, Speaker } from '../types/interview';

type LiveKitModule = typeof import('livekit-client');
type LiveKitRoom = InstanceType<LiveKitModule['Room']>;

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
  videoTrack: MediaStreamTrack | null;
  audioTrack: MediaStreamTrack | null;
  /**
   * 발행 성공 시 호출 — 트랙 소유권이 Room 으로 넘어갔음을 알린다.
   *
   * 소유권을 호출자가 계속 들고 있으면(App.tsx 의 DeviceGate) 넘기지 않아도 된다.
   */
  onTracksPublished?: () => void;
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
  const roomRef = useRef<LiveKitRoom | null>(null);
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
    const { setSession, setConnection, setRemoteJoined, setSpeaking, applyStreamEvent, reset } =
      useInterviewStore.getState();

    // 1:1 이므로 참가자는 둘뿐이다. 내 역할이 정해지면 상대 역할도 정해진다.
    // Role 과 Speaker 는 표기가 같아 내 화자는 역할 그대로다. 상대만 뒤집는다.
    const localSpeaker: Speaker = role;
    const remoteSpeaker: Speaker = role === 'INTERVIEWER' ? 'CANDIDATE' : 'INTERVIEWER';

    let cancelled = false;
    let room: LiveKitRoom | null = null;

    void (async () => {
      try {
        const { Room, RoomEvent, Track } = await loadLiveKit();
        if (cancelled) return;

        room = new Room({
          adaptiveStream: true,
          dynacast: true,
          // 프리뷰에서 잡은 트랙과 설정이 어긋나지 않게 같은 값을 둔다.
          videoCaptureDefaults: { resolution: { width: 1280, height: 720 } },
          audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true },
        });
        roomRef.current = room;

        /* 상대 참가자의 트랙만 붙인다. AI 워커·녹화 참가자는 제외한다. */
        const attach = (track: RemoteTrack) => {
          if (track.kind === Track.Kind.Video && videoRef.current) {
            track.attach(videoRef.current);
          }
          if (track.kind === Track.Kind.Audio && audioRef.current) {
            track.attach(audioRef.current);
          }
        };

        room
          .on(RoomEvent.ConnectionStateChanged, (state) =>
            setConnection(String(state) as RoomConnectionState),
          )
          .on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
            if (participant.identity === remoteSpeaker) attach(track);
          })
          .on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach())
          .on(RoomEvent.ParticipantConnected, (participant) => {
            // 같은 방의 AI 워커는 통화 상대가 아니다. BE가 역할을 identity로 발급한다.
            if (participant.identity === remoteSpeaker) setRemoteJoined(true);
          })
          .on(RoomEvent.ParticipantDisconnected, (participant) => {
            if (participant.identity !== remoteSpeaker) return;
            setRemoteJoined(false);
            setSpeaking(null);
          })
          // 발화 중 화자 표시. 서버 speech.start와 별개로 즉시 반응한다.
          //
          // 원격 참가자가 누구인지는 내 역할에 따라 뒤집힌다 —
          // 면접관에게 원격은 지원자이고, 지원자에게 원격은 면접관이다.
          .on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
            if (speakers.length === 0) {
              setSpeaking(null);
              return;
            }
            const isRemote = speakers.some((p) => p.identity === remoteSpeaker);
            const isLocal = speakers.some((p) => p === room?.localParticipant);
            setSpeaking(isRemote ? remoteSpeaker : isLocal ? localSpeaker : null);
          })
          .on(RoomEvent.Disconnected, () => setRemoteJoined(false));

        // 워커가 접속 직후 보낼 수 있어 connect 전에 등록한다. 역할 분기는 하지 않는다 —
        // AI가 destination_identities로 면접관만 지정하므로 지원자에게는 전달되지 않는다.
        room.registerTextStreamHandler(
          TRANSCRIPT_TOPIC,
          createTranscriptStreamHandler(applyStreamEvent, () => cancelled),
        );

        // join 이 입장 권한 확인과 LiveKit 접속 정보 발급을 함께 한다.
        // 접속 뒤 상태를 확인하고 새 면접의 시작만 별도로 요청한다.
        const { livekitUrl, token } = await joinSession(sessionId, role);
        if (cancelled) return;
        setSession(sessionId);

        /* --- 방 접속 --- */
        await room.connect(livekitUrl, token);
        if (cancelled) {
          await room.disconnect(false);
          return;
        }

        // 새 면접만 시작한다. 재입장은 INTERVIEWING을 유지하며 시작 시각을 덮지 않는다.
        const state = await getSessionState(sessionId);
        if (cancelled) return;
        // join 토큰을 받은 뒤 종료된 방에 늦게 붙었으면 다시 트랙을 발행하지 않는다.
        if (state.status === 'ENDED') throw new ApiError('SESSION_ENDED', 409);
        if (role === 'INTERVIEWER') {
          if (state.status === 'WAITING') {
            try {
              await startSession(sessionId);
            } catch (e) {
              // 다른 탭이 먼저 시작한 409만 허용한다. 종료·통신 실패는 숨기지 않는다.
              if (!(e instanceof ApiError) || e.code !== 'INVALID_SESSION_STATE') throw e;
              const current = await getSessionState(sessionId);
              if (current.status !== 'INTERVIEWING') throw e;
            }
          }
          if (cancelled) return;
        }

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
            await room.disconnect(false);
            return;
          }

          // 발행 성공을 알린다. DeviceGate가 원본 트랙을 소유한 경로에서는 계속 그쪽이 정리한다.
          onTracksPublished?.();
        } catch (e) {
          // 발행 실패가 통화를 막지는 않는다 — 지원자 영상과 전사는 계속 본다.
          // setError 를 세우면 화면 전체가 실패 오버레이로 덮인다.
          console.warn('로컬 트랙 발행 실패', e);
        }

        /* 이미 들어와 있는 지원자 트랙 구독 */
        room.remoteParticipants.forEach((p) => {
          if (p.identity !== remoteSpeaker) return;
          setRemoteJoined(true);
          p.trackPublications.forEach((pub: RemoteTrackPublication) => {
            if (pub.track) attach(pub.track);
          });
        });
      } catch (e) {
        if (!cancelled) {
          void room?.disconnect(false);
          setError(e instanceof ApiError ? e.code : 'CONNECT_FAILED');
        }
      }
    })();

    return () => {
      cancelled = true;
      room?.unregisterTextStreamHandler(TRANSCRIPT_TOPIC);
      room?.removeAllListeners();
      // 원본 트랙은 DeviceGate 소유다. StrictMode 재접속 때 먼저 stop하면
      // 다음 Room에 끝난 트랙이 전달되므로 최종 이탈 때만 DeviceGate가 회수한다.
      void room?.disconnect(false);
      if (roomRef.current === room) roomRef.current = null;
      reset();
    };
  }, [sessionId, role, videoRef, audioRef, ready]);

  /**
   * 통화에서 나간다.
   *
   * 면접 종료는 면접관만 할 수 있다. 지원자가 나가는 것은 이탈일 뿐이고,
   * 네트워크가 끊겨서 나갔을 수도 있으므로 세션까지 끝내면 안 된다 —
   * 면접관이 아직 방에 남아 있는데 세션이 ENDED 가 되어 재입장이 막힌다.
   */
  const leave = async () => {
    let result = null;
    if (role === 'INTERVIEWER') {
      try {
        // 서버 종료가 실패했으면 방에 남아 재시도할 수 있어야 한다.
        result = await endSession(sessionId);
      } catch (e) {
        // BE는 방 정리 전에 ENDED를 저장한다. 방 정리만 실패했다면 종료는 완료된 것이다.
        const state = await getSessionState(sessionId);
        if (state.status !== 'ENDED' || !state.endedAt) throw e;
        result = { sessionId, status: state.status, endedAt: state.endedAt };
      }
    }
    await roomRef.current?.disconnect(false);
    return result;
  };

  // roomRef.current 를 렌더 중에 읽으면 연결 이후 값이 갱신되지 않는다.
  // ref 자체를 넘겨 이벤트 핸들러·이펙트 안에서 읽게 한다.
  return { roomRef, error, leave };
}
