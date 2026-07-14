import pytest
from pydantic import ValidationError

from ai_worker.config import WorkerSettings


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("REDIS_URL", "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_settings_fail_closed_without_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValidationError):
        WorkerSettings(_env_file=None)  # type: ignore[call-arg]


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6381")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9002")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "s")
    settings = WorkerSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.s3_bucket == "liviq"  # 기본값
    assert settings.redis_url.startswith("redis://")
