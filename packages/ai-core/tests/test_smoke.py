# ponytail: 임시 스모크 — pytest exit-5(테스트 0개) 방지용. 실 로직 도입 시 대체.
import ai_core


def test_package_imports_and_reports_version() -> None:
    assert ai_core.__version__ == "0.1.0"
