from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IRYA API"
    app_env: str = "local"

    # 테크스펙 §2 의 Base URL 은 /v1 이지만, 단일 도메인 배포 시
    # FE 라우트(/join 등)와 구분하기 위해 /api/v1 을 쓴다.
    # /health 는 이 prefix 밖에 둔다 — LB·오케스트레이터가 부르고 버전과 무관하다.
    api_prefix: str = "/api/v1"

    # 쉼표로 구분한다. pydantic-settings 는 list[str] 을 JSON 으로만 받으므로
    # .env 에 적기 좋은 형태를 쓰고 아래에서 쪼갠다.
    cors_origins: str = "http://localhost:5173"

    # 토큰은 접속하는 순간에만 검증되고, 붙은 뒤에는 LiveKit 서버가 5분마다 갱신해 준다
    # (livekit_rtc.proto 의 SignalResponse.refresh_token). 길게 줄 이유가 없다.
    token_ttl_minutes: int = 15

    # 면접관 + 지원자. Agent·Egress 는 LiveKit 이 정원 계산에서 제외한다.
    room_max_participants: int = 2

    # 초대 링크를 만들 FE 주소. BE 가 프론트 도메인을 아는 건 명세의 요구다
    # (Session 생성이 "지원자 초대 링크를 발급").
    frontend_origin: str = "http://localhost:5173"
    invite_path: str = "/interview"

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # RoomService(Twirp) 호출 주소. 비우면 livekit_url 을 쓴다.
    # BE 와 LiveKit 이 같은 compose 네트워크에 있으면 http://livekit:7880 을
    # 넣는다 — 공개 도메인을 쓰면 바로 옆 컨테이너를 부르려고 인터넷을 한 바퀴
    # 돌고, Caddy 에 /twirp 를 열어야 한다.
    livekit_internal_url: str = ""

    # 비우면 인메모리 저장소를 쓴다. 로컬 개발과 테스트가 DB 없이 돌아야 한다.
    # 예: postgresql://irya:<password>@db:5432/irya
    database_url: str = ""

    # Agent 가 /internal/v1 에 붙을 때 쓰는 공유 비밀.
    #
    # 비우면 검사하지 않는다. Agent 쪽도 키가 없으면 Authorization 헤더를 아예
    # 보내지 않으므로(`irya_ai.backend.auth_headers`), 양쪽이 비어 있으면 로컬에서
    # 자격증명을 지어내지 않고 그대로 붙는다. 서버에서는 반드시 채운다 —
    # 비워 두면 /internal/v1 이 누구에게나 열린다.
    internal_api_key: str = ""

    # 면접이 끝난 뒤 요약을 기다리는 한도. 넘기면 FAILED 로 넘긴다.
    #
    # FE 는 PROCESSING 동안만 다시 조회하므로 **종료 상태가 반드시 와야 한다.**
    # 그 마감을 서버가 쥐는 이유는, 클라이언트가 경과 시간으로 추측하면
    # 정상적으로 오래 걸린 요약을 못 보게 되기 때문이다.
    #
    # 기본 3분은 AI 쪽 상한에서 잡았다 — `analysis_timeout_seconds` 가
    # `le=120` 이라 분석 자체는 2분을 넘을 수 없고(`ai/src/irya_ai/config.py`),
    # 거기에 결과를 보내는 시간과 재시도 여유를 더한 값이다. 늦게 온 결과도
    # 받으므로(`PUT .../review`), 짧게 잡아 틀리는 쪽이 복구된다.
    summary_timeout_seconds: float = Field(default=180, gt=0, le=1800)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def livekit_api_url(self) -> str:
        """RoomService 를 부를 주소."""
        return self.livekit_internal_url or self.livekit_url

    @property
    def summary_timeout(self) -> timedelta:
        return timedelta(seconds=self.summary_timeout_seconds)

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


settings = Settings()
