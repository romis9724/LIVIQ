"""H0-8 헬스체크 + env 검증(fail-closed) 테스트."""

import pytest
from app.config import ApiSettings
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_fail_closed_without_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValidationError):
        ApiSettings(_env_file=None)  # type: ignore[call-arg]
