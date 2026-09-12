"""OpenAPI 스키마를 파일로 덤프한다.

커밋된 파일과 코드가 어긋나면 CI 가 실패한다. API 가 바뀌면 PR diff 에 드러나므로
리뷰어가 "이거 FE·AI 에 알렸나" 를 볼 수 있고, AI 팀은 이 파일만 봐도 된다.

    uv run python -m scripts.dump_openapi
"""

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    schema = json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True)
    OUTPUT.write_text(schema + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(Path.cwd().parent)} 갱신")


if __name__ == "__main__":
    main()
