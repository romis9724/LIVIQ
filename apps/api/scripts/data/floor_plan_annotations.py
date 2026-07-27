"""TYPE_A 평면도 어노테이션 이식 (apt-facility-finder/annotations.js, H13-3).

JS를 파싱하지 않고 데이터를 파이썬 dict로 그대로 옮긴 것 — 원본 이미지 923x676 픽셀
좌표계. B타입은 좌우반전 미러(원본의 mirrorType 로직, seed_floor_plans.py가 적용)로
파생하므로 A타입만 여기 보유한다. 원본과의 항목 수 일치는 seed_floor_plans.py 리포트로
확인한다(rooms 14 + elements 40).
"""

from __future__ import annotations

from typing import Any

IMAGE_FILE = "아파트 도면_clean.jpg"
IMAGE_WIDTH = 923
IMAGE_HEIGHT = 676

ROOMS: list[dict[str, Any]] = [
    {"name": "거실", "x": 490, "y": 425},
    {"name": "주방", "x": 490, "y": 200},
    {"name": "안방", "x": 720, "y": 395},
    {"name": "침실1", "x": 105, "y": 445},
    {"name": "침실2", "x": 283, "y": 445},
    {"name": "욕실1", "x": 75, "y": 335},
    {"name": "욕실2", "x": 700, "y": 240},
    {"name": "현관", "x": 213, "y": 262},
    {"name": "팬트리", "x": 345, "y": 262},
    {"name": "다용도실", "x": 400, "y": 118},
    {"name": "발코니(전면)", "x": 400, "y": 545},
    {"name": "발코니(후면)", "x": 600, "y": 100},
    {"name": "발코니(측면)", "x": 850, "y": 322},
    {"name": "실외기실", "x": 840, "y": 545},
]

ELEMENTS: list[dict[str, Any]] = [
    {"type": "콘센트", "room": "거실", "x": 430, "y": 510, "dir": "down"},
    {"type": "콘센트", "room": "거실", "x": 620, "y": 430, "dir": "right"},
    {"type": "콘센트", "room": "거실", "x": 360, "y": 435, "dir": "left"},
    {"type": "콘센트", "room": "주방", "x": 435, "y": 235, "dir": "left"},
    {"type": "콘센트", "room": "주방", "x": 540, "y": 40, "dir": "up"},
    {"type": "콘센트", "room": "안방", "x": 625, "y": 400, "dir": "left"},
    {"type": "콘센트", "room": "안방", "x": 760, "y": 500, "dir": "down"},
    {"type": "콘센트", "room": "안방", "x": 815, "y": 350, "dir": "right"},
    {"type": "콘센트", "room": "침실1", "x": 28, "y": 430, "dir": "left"},
    {"type": "콘센트", "room": "침실1", "x": 120, "y": 500, "dir": "down"},
    {"type": "콘센트", "room": "침실2", "x": 205, "y": 430, "dir": "left"},
    {"type": "콘센트", "room": "침실2", "x": 300, "y": 500, "dir": "down"},
    {"type": "콘센트", "room": "욕실1", "x": 28, "y": 318, "dir": "left"},
    {"type": "콘센트", "room": "욕실2", "x": 655, "y": 245, "dir": "left"},
    {"type": "콘센트", "room": "팬트리", "x": 300, "y": 260, "dir": "left"},
    {"type": "콘센트", "room": "다용도실", "x": 330, "y": 130, "dir": "left"},
    {"type": "콘센트", "room": "발코니(전면)", "x": 500, "y": 512, "dir": "up"},
    {"type": "분전함", "room": "현관", "x": 250, "y": 230, "dir": "right"},
    {"type": "통신단자함", "room": "현관", "x": 250, "y": 285, "dir": "right"},
    {"type": "TV·인터넷 단자", "room": "거실", "x": 560, "y": 510, "dir": "down"},
    {"type": "TV·인터넷 단자", "room": "안방", "x": 625, "y": 445, "dir": "left"},
    {"type": "TV·인터넷 단자", "room": "침실1", "x": 28, "y": 465, "dir": "left"},
    {"type": "TV·인터넷 단자", "room": "침실2", "x": 205, "y": 465, "dir": "left"},
    {"type": "가스밸브", "room": "주방", "x": 490, "y": 40, "dir": "up"},
    {"type": "수도 차단밸브", "room": "주방", "x": 395, "y": 258, "dir": "left"},
    {"type": "수도 차단밸브", "room": "다용도실", "x": 435, "y": 120, "dir": "right"},
    {"type": "보일러", "room": "다용도실", "x": 365, "y": 92, "dir": "up"},
    {"type": "난방 분배기", "room": "주방", "x": 415, "y": 300, "dir": "down"},
    {"type": "온도조절기", "room": "거실", "x": 360, "y": 485, "dir": "left"},
    {"type": "에어컨 배관", "room": "거실", "x": 600, "y": 510, "dir": "down"},
    {"type": "에어컨 배관", "room": "안방", "x": 790, "y": 500, "dir": "down"},
    {"type": "소화기", "room": "주방", "x": 620, "y": 250, "dir": "right"},
    {"type": "소화기", "room": "현관", "x": 175, "y": 260, "dir": "left"},
    {"type": "화재감지기", "room": "거실", "x": 490, "y": 430, "dir": None},
    {"type": "화재감지기", "room": "주방", "x": 505, "y": 170, "dir": None},
    {"type": "화재감지기", "room": "안방", "x": 720, "y": 400, "dir": None},
    {"type": "화재감지기", "room": "침실1", "x": 100, "y": 445, "dir": None},
    {"type": "화재감지기", "room": "침실2", "x": 275, "y": 445, "dir": None},
    {"type": "경량칸막이", "room": "발코니(전면)", "x": 28, "y": 545, "dir": "left"},
    {"type": "월패드", "room": "거실", "x": 360, "y": 405, "dir": "left"},
]
