"""graph 소유 env — Neo4j 접속 (docs/09 §2, docs/11 §4).

ai-core 전체 config(AiCoreSettings)와 분리해 **지연 로드**한다: api처럼 그래프를
쓰지 않는 프로세스가 ai-core를 import해도 NEO4J_* 누락으로 부팅 실패하지 않게 한다.
그래프 드라이버를 실제로 생성할 때만 인스턴스화된다(fail-closed는 그 시점).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    neo4j_uri: str = Field(..., validation_alias="NEO4J_URI")
    neo4j_user: str = Field(..., validation_alias="NEO4J_USER")
    neo4j_password: str = Field(..., validation_alias="NEO4J_PASSWORD")


@lru_cache
def get_graph_settings() -> GraphSettings:
    return GraphSettings()  # type: ignore[call-arg]
