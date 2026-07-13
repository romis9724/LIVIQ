"""app.main 임포트 시점의 env 검증을 통과시키기 위한 더미 REDIS_URL.

실제 Redis 연결 없음(H0 빈 앱). 검증 트리거만 만족시킨다.
"""

import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
