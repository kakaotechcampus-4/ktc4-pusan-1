/**
 * 통화 연결 — 방 접속, 1:1 트랙 구독, 녹화
 *
 * 녹화는 LiveKit Egress로 서버에서 수행한다.
 * 클라이언트 MediaRecorder는 쓰지 않는다 — 브라우저가 닫히면 유실되고,
 * stream(전사) 연결과 무관하게 녹화가 유지돼야 한다.
 */

import {
  RemoteParticipant,
  Room,
  RoomEvent,
  Track,
  type RemoteTrack,
  type RemoteTrackPublication,
} from 'livekit-client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError } from '../api/client';
import { endSession, startInterview } from '../api/interview';
import { useInterviewStore } from '../stores/interviewStore';
import type { StreamEvent } from '../types/interview';

interface UseInterviewRoomOptions {
  interviewId: string;
  /** 지원자 비디오를 붙일 요소 */
  videoRef: RefObject<HTMLVideoElement | null>;
  /** 지원자 오디오를 붙일 요소 */
  audioRef: RefObject<HTMLAudioElement | null>;
}

export function useInterviewRoom({ interviewId, videoRef, audioRef }: UseInterviewRoomOptions) {
  const roomRef = useRef<Room | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 액션은 참조가 고정되어 있다. 구독하면 전사 델타마다 화면 전체가 리렌더되므로
    // 훅에서는 getState() 로 꺼내 쓰고 스토어를 구독하지 않는다.
    const { setSession, setConnection, setCandidateJoined, setSpeaking, applyStreamEvent, reset } =
      useInterviewStore.getState();

    let cancelled = false;
    let stream: WebSocket | null = null;

    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
      // 면접관은 지원자를 크게 보므로 원본 해상도를 유지한다.
      videoCaptureDefaults: { resolution: { width: 1280, height: 720 } },
      audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true },
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
        const { sessionId, media, stream: streamCfg } = await startInterview(interviewId);
        if (cancelled) return;
        setSession(sessionId);

        /* --- 방 접속 --- */
        await room.connect(media.roomUrl, media.token);
        if (cancelled) return;

        /* 면접관 트랙 발행. 자기 화면은 렌더하지 않고 지원자에게만 보낸다. */
        await room.localParticipant.enableCameraAndMicrophone();

        /* 이미 들어와 있는 지원자 트랙 구독 */
        room.remoteParticipants.forEach((p) => {
          setCandidateJoined(true);
          p.trackPublications.forEach((pub: RemoteTrackPublication) => {
            if (pub.track) attach(pub.track);
          });
        });

        /* --- 전사·추천 질문 연결 (통화와 분리) --- */
        stream = new WebSocket(streamCfg.url);
        stream.onmessage = (ev) => applyStreamEvent(JSON.parse(ev.data) as StreamEvent);
        stream.onerror = () =>
          applyStreamEvent({ type: 'stream.degraded', reason: 'STT_UNAVAILABLE' });
        stream.onclose = (ev) => {
          // 정상 종료(1000)가 아니면 전사만 중단 표시. 통화는 그대로 둔다.
          if (ev.code !== 1000) {
            applyStreamEvent({ type: 'stream.degraded', reason: 'STT_UNAVAILABLE' });
          }
        };
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.code : 'CONNECT_FAILED');
        }
      }
    })();

    return () => {
      cancelled = true;
      stream?.close(1000);
      room.removeAllListeners();
      void room.disconnect();
      reset();
    };
  }, [interviewId, videoRef, audioRef]);

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
