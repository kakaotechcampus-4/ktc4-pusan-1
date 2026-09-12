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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


settings = Settings()
