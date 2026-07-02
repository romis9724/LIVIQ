"""공유 상태 컨테이너.

전역 재할당(global) 대신 단일 가변 객체를 모듈 간 참조로 공유한다.
load_sheet_data 가 채우고, tools/sheets 가 읽는다.
"""

from dataclasses import dataclass, field


@dataclass
class FeeStore:
    mgmt_rows: list[dict] = field(default_factory=list)
    resident_rows: list[dict] = field(default_factory=list)
    ho_list: list[str] = field(default_factory=list)
