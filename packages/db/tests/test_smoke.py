# ponytail: 임시 스모크 — pytest exit-5(테스트 0개) 방지용. H0-3에서 실 테스트로 대체.
import liviq_db


def test_package_imports_and_reports_version() -> None:
    assert liviq_db.__version__ == "0.1.0"
