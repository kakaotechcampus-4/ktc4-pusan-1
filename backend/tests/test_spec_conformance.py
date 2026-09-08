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
        "request": {"interviewerId"},
        "response": {"interviewId", "interviewerId", "createdAt"},
        "statuses": {"201", "422"},
    },
    ("get", "/api/v1/interviews/{interviewId}"): {
        "path_params": ["interviewId"],
        "response": {"interviewId", "interviewerId", "createdAt"},
        "statuses": {"200", "404"},
    },
    ("post", "/api/v1/interviews/{interviewId}/sessions"): {
        "path_params": ["interviewId"],
        "response": {"sessionId", "interviewId", "status", "inviteUrl", "createdAt"},
        "statuses": {"201", "404"},
    },
    ("get", "/api/v1/sessions/{sessionId}"): {
        "path_params": ["sessionId"],
        "response": {"sessionId", "interviewId", "status", "startedAt", "endedAt"},
        "statuses": {"200", "404"},
    },
    ("post", "/api/v1/sessions/{sessionId}/join"): {
        "path_params": ["sessionId"],
        "request": {"role"},
        "response": {"sessionId", "livekitUrl", "token", "roomName"},
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
}

# 명세의 상태·역할 값 (대문자)
SESSION_STATUS = {"WAITING", "INTERVIEWING", "ENDED"}
ROLE = {"INTERVIEWER", "CANDIDATE"}


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
    content = op["responses"][success]["content"]["application/json"]["schema"]

    assert _props(schema, content) == SPEC[(method, path)]["response"]


@pytest.mark.parametrize(("method", "path"), sorted(SPEC))
def test_request_fields_match_spec(method: str, path: str, schema: dict[str, Any]):
    expected = SPEC[(method, path)].get("request")
    body = schema["paths"][path][method].get("requestBody")

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
