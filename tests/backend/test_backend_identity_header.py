"""Issue 45: the API identifies itself so the frontend proxy can refuse other services."""

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_every_api_response_carries_the_cricatlas_identity_header() -> None:
    client = TestClient(create_app())
    for path in ("/health", "/api/players/search?q=kohli", "/api/does-not-exist"):
        response = client.get(path)
        assert response.headers.get("x-cricatlas-backend") == "1", path
