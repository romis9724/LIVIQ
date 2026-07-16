"""OpenAPI 스키마를 결정적 JSON으로 내보낸다(docs/02 §7).

실행: uv run --no-sync python scripts/export_openapi.py [출력경로]
경로 생략 시 stdout. sort_keys로 재실행 diff 0을 보장한다.
"""

from __future__ import annotations

import json
import os
import sys

# 스키마는 코드에서만 결정된다(env 무관). 부팅 검증만 통과시키는 더미값.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9002")
os.environ.setdefault("S3_ACCESS_KEY_ID", "x")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "x")

from app.main import create_app  # noqa: E402


def main() -> None:
    schema = create_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
