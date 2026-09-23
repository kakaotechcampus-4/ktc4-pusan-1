"""Notion `API 기본 명세서` 적합성.

각 엔드포인트 문서의 Request/Response 표와 Status 표를 데이터로 옮겨두고
OpenAPI 스키마와 대조한다. 구현이 명세에서 벗어나면 여기서 걸린다.

명세가 바뀌면 이 표를 먼저 고치고 구현을 따라오게 한다.
"""

from typing import Any

import pytest

from app.main import app

SPEC: dict[tuple[str, str], dict[str, Any]] = {
    ("get", "/health"): {
        "response": {"status"},
        "statuses": {"200"},
    },
    ("post", "/api/v1/interviews"): {
        "request": {"interviewerId", "candidateName"},
        "response": {"interviewId", "interviewerId", "candidateName", "createdAt"},
        "statuses": {"201", "422"},
    },
    ("get", "/api/v1/interviews/{interviewId}"): {
        "path_params": ["interviewId"],
        "response": {"interviewId", "interviewerId", "candidateName", "createdAt"},
        "statuses": {"200", "404"},
    },
    # ⚠️ 세 파트 합의 전이다. 응답은 지금 PROCESSING 한 갈래만 나간다.
    # READY 쪽 필드는 모델로만 선언해 두고 여기서는 잠그지 않는다 —
    # 합의되면 그때 이 표에 옮긴다.
    ("get", "/api/v1/interviews/{interviewId}/review"): {
        "path_params": ["interviewId"],
        "response": {"status", "etaSec"},
        "statuses": {"202", "404"},
    },
    ("post", "/api/v1/interviews/{interviewId}/sessions"): {
        "path_params": ["interviewId"],
        "response": {
            "sessionId",
            "interviewId",
            "candidateName",
            "status",
            "inviteUrl",
            "createdAt",
        },
        "statuses": {"201", "404"},
    },
    ("get", "/api/v1/sessions/{sessionId}"): {
        "path_params": ["sessionId"],
        "response": {
            "sessionId",
            "interviewId",
            "candidateName",
            "status",
            "startedAt",
            "endedAt",
            "transcriptOriginAt",
        },
        "statuses": {"200", "404"},
    },
    ("post", "/api/v1/sessions/{sessionId}/join"): {
        "path_params": ["sessionId"],
        "request": {"role"},
        "response": {"sessionId", "candidateName", "livekitUrl", "token", "roomName"},
        "statuses": {"200", "404", "409"},
    },
    ("post", "/api/v1/sessions/{sessionId}/start"): {
        "path_params": ["sessionId"],
        "response": {"sessionId", "status", "startedAt"},
        "statuses": {"200", "404", "409"},
    },
    ("post", "/api/v1/sessions/{sessionId}/end"): {
        "path_params": ["sessionId"],
        "response": {"sessionId", "status", "endedAt"},
        "statuses": {"200", "404", "409"},
    },
    # ⚠️ 기업 컨텍스트는 Notion 명세에 아직 없다. FE 가 화면을 먼저 만들면서
    # 형태를 정했고(#79·#81), BE 가 그 모양에 맞춰 세운 것이다. 명세에 옮기는 일은
    # #24 에 걸려 있다 — 여기 표가 그때까지의 기준이다.
    #
    # `talentProfile` 은 FE 의 `CompanyContext` 에 없는 필드다. FE 가 저장만 하고
    # 다시 못 읽어 새로 고치면 빈 칸이 된다고 적어 둬서(#81), 조회에 실어 보낸다.
    # ⚠️ Notion 명세에 없다. FE 가 형태를 먼저 정했다(#81 의 `api/resume.ts`).
    # 응답은 기업 컨텍스트 문서와 같은 모양이다 — FE 가 같은 카드로 그린다.
    ("post", "/api/v1/interviews/{interviewId}/resume"): {
        "path_params": ["interviewId"],
        "multipart": True,
        "response": {"id", "name", "kind", "sizeBytes", "status"},
        "statuses": {"201", "404", "413", "415", "422"},
    },
    ("get", "/api/v1/contexts/current"): {
        "response": {"id", "company", "team", "role", "talentProfile", "docs"},
        "statuses": {"200"},
    },
    ("get", "/api/v1/contexts/{contextId}"): {
        "path_params": ["contextId"],
        "response": {"id", "company", "team", "role", "talentProfile", "docs"},
        "statuses": {"200", "404"},
    },
    ("patch", "/api/v1/contexts/{contextId}"): {
        "path_params": ["contextId"],
        "request": {"company", "team", "role", "talentProfile"},
        "response": {"id", "company", "team", "role", "talentProfile", "docs"},
        "statuses": {"200", "404", "422"},
    },
    ("post", "/api/v1/contexts/{contextId}/docs"): {
        "path_params": ["contextId"],
        # 본문이 JSON 이 아니라 파일이다. 필드 표 대신 형식만 잠근다.
        "multipart": True,
        "response": {"id", "name", "kind", "sizeBytes", "status"},
        "statuses": {"201", "404", "413", "415", "422"},
    },
    ("delete", "/api/v1/contexts/{contextId}/docs/{docId}"): {
        "path_params": ["contextId", "docId"],
        "statuses": {"204", "404"},
    },
}

# 명세의 상태·역할 값 (대문자)
SESSION_STATUS = {"WAITING", "INTERVIEWING", "ENDED"}
ROLE = {"INTERVIEWER", "CANDIDATE"}

# 클라이언트가 분기에 쓰는 에러 코드. 추가하면 명세도 같이 고쳐야 한다.
ERROR_CODE = {
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "INTERNAL_ERROR",
    "INTERVIEW_NOT_FOUND",
    "SESSION_NOT_FOUND",
    "SESSION_ENDED",
    "INVALID_SESSION_STATE",
    "ROOM_FULL",
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return app.openapi()


def _props(schema: dict[str, Any], ref: dict[str, Any]) -> set[str]:
    name = ref["$ref"].rsplit("/", 1)[-1]
    return set(schema["components"]["schemas"][name]["properties"])


def test_endpoint_set_matches_spec(schema: dict[str, Any]):
    actual = {(m, p) for p, ops in schema["paths"].items() for m in ops}

    assert actual == set(SPEC)


@pytest.mark.parametrize(("method", "path"), sorted(SPEC))
def test_response_fields_match_spec(method: str, path: str, schema: dict[str, Any]):
    op = schema["paths"][path][method]
    success = next(c for c in op["responses"] if c.startswith("2"))
    expected = SPEC[(method, path)].get("response")

    if expected is None:
        # 204 처럼 본문이 없는 것. 없다는 사실 자체를 잠근다 — 나중에 본문이
        # 생기면 명세를 먼저 고치게 된다.
        assert "content" not in op["responses"][success]
        return

    content = op["responses"][success]["content"]["application/json"]["schema"]
    assert _props(schema, content) == expected


@pytest.mark.parametrize(("method", "path"), sorted(SPEC))
def test_request_fields_match_spec(method: str, path: str, schema: dict[str, Any]):
    entry = SPEC[(method, path)]
    expected = entry.get("request")
    body = schema["paths"][path][method].get("requestBody")

    if entry.get("multipart"):
        # 파일 업로드다. 필드 표로 잠글 수 있는 모양이 아니라 형식만 본다.
        assert body is not None
        assert set(body["content"]) == {"multipart/form-data"}
        return
    if expected is None:
        # 명세상 Request Body 가 없거나 {} 인 것들
        assert body is None
        return
    ref = body["content"]["application/json"]["schema"]
    assert _props(schema, ref) == expected


@pytest.mark.parametrize(("method", "path"), sorted(SPEC))
def test_path_parameter_names_match_spec(
    method: str, path: str, schema: dict[str, Any]
):
    expected = SPEC[(method, path)].get("path_params", [])
    params = schema["paths"][path][method].get("parameters", [])

    assert [p["name"] for p in params if p["in"] == "path"] == expected


@pytest.mark.parametrize(("method", "path"), sorted(SPEC))
def test_documented_statuses_match_spec(method: str, path: str, schema: dict[str, Any]):
    """명세 Status 표의 코드가 Swagger 에 그대로 나와야 한다.

    FastAPI 는 path 파라미터나 body 가 있는 라우트에 422 를 자동으로 붙인다.
    명세 표에 없더라도 실제로 가능한 응답이므로 그것만 예외로 둔다.
    """
    documented = set(schema["paths"][path][method]["responses"])
    expected = SPEC[(method, path)]["statuses"]

    assert expected <= documented, (
        f"명세에 있는데 문서화 안 됨: {expected - documented}"
    )
    assert documented - expected <= {"422"}, (
        f"명세에 없는 응답: {documented - expected}"
    )


def test_enum_values_match_spec(schema: dict[str, Any]):
    schemas = schema["components"]["schemas"]

    assert set(schemas["SessionStatus"]["enum"]) == SESSION_STATUS
    assert set(schemas["Role"]["enum"]) == ROLE
    assert set(schemas["ErrorCode"]["enum"]) == ERROR_CODE
