"""generate_demo_docs.py — 문서관리 데모 PDF 생성기 (로컬 전용).

scripts/data/documents_demo.py의 문서 33건(회의록 23 · 지침·매뉴얼 10)을 한글 PDF로
렌더한다. **로컬에서만 돌리는 도구**라 fpdf2를 프로젝트 의존성에 넣지 않고 실행 시점에
`--with`로 주입한다. 산출물은 커밋하지 않는다(.gitignore).

실행:

    cd apps/api
    uv run --no-sync --with fpdf2 python scripts/generate_demo_docs.py
    uv run --no-sync --with fpdf2 python scripts/generate_demo_docs.py \\
        --out /tmp/docs --font /path/to/NanumGothic.ttf

한글 폰트가 없으면 글자가 깨지므로 폰트 파일을 필수로 검사한다. 기본값은 macOS에 기본
설치된 Arial Unicode(TrueType glyf)이며, 리눅스에서는 `--font`로 나눔고딕 등 TTF를
지정한다. 폰트 선택 함정 두 가지:

  - AppleGothic.ttf·AppleMyungjo.ttf는 OS/2 테이블이 없어 fpdf2가 읽지 못한다.
  - AppleSDGothicNeo.ttc는 CFF 기반(CIDFontType0)이라 렌더는 되지만 pypdf 추출 결과에
    글자마다 NUL(\\x00)이 섞인다 — ai-worker 인제스트(pypdf)가 그대로 깨지므로 쓰지 않는다.
    glyf 아웃라인 TTF를 쓰면 Identity-H로 실려 추출이 정상이다.

생성한 PDF는 scripts/seed_documents_demo.py가 `--dir`로 읽어 DB·MinIO에 적재한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# scripts/data는 패키지가 아니라 폴더(namespace package, seed_floor_plans.py와 동일 관례).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.documents_demo import COMPLEX_NAME, DEMO_DOCS, DemoDoc  # noqa: E402

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "data" / "generated_docs"
# macOS 기본 한글 폰트 중 glyf 아웃라인 + OS/2를 가진 것(= pypdf 추출이 정상인 것).
DEFAULT_FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

FONT_FAMILY = "KoreanBody"
TITLE_SIZE = 16
META_SIZE = 9
HEADING_SIZE = 12
BODY_SIZE = 10.5
BODY_LINE_H = 6.2
HEADING_LINE_H = 7.0
MARGIN_MM = 20


def _paragraph(pdf: Any, height: float, textline: str) -> None:
    """줄바꿈 단락 출력 — 다음 줄 시작을 왼쪽 여백으로 되돌린다.

    fpdf2 multi_cell 기본값은 new_x=RIGHT라 커서가 오른쪽 끝에 남고, 이어지는
    폭 자동(w=0) 호출이 "Not enough horizontal space"로 실패한다.
    """
    pdf.multi_cell(0, height, textline, new_x="LMARGIN", new_y="NEXT")


def _render(doc: DemoDoc, font_path: Path) -> bytes:
    """문서 1건을 A4 PDF 바이트로 렌더 — 머리글(제목·단지·작성일) + 절별 본문."""
    # 프로젝트 의존성이 아니다(`--with fpdf2`로 주입) — 타입 스텁도 없다.
    from fpdf import FPDF  # type: ignore[import-untyped]

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
    # 폰트 1종만 등록한다 — bold 스타일을 쓰면 등록되지 않은 스타일로 예외가 난다.
    pdf.add_font(FONT_FAMILY, "", str(font_path))
    pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
    pdf.set_title(doc.title)
    pdf.add_page()

    pdf.set_font(FONT_FAMILY, "", TITLE_SIZE)
    _paragraph(pdf, 9, doc.title)
    pdf.ln(1)
    pdf.set_font(FONT_FAMILY, "", META_SIZE)
    _paragraph(pdf, 5, f"{COMPLEX_NAME}   ·   작성일 {doc.doc_date:%Y년 %m월 %d일}")
    _paragraph(pdf, 5, f"분류 {doc.category}   ·   공개범위 {doc.visibility}")
    pdf.ln(3)

    for section in doc.sections:
        pdf.set_font(FONT_FAMILY, "", HEADING_SIZE)
        _paragraph(pdf, HEADING_LINE_H, section.heading)
        pdf.ln(1)
        pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
        for paragraph in section.paragraphs:
            _paragraph(pdf, BODY_LINE_H, paragraph)
            pdf.ln(2)
        pdf.ln(2)

    return bytes(pdf.output())


def _run(out_dir: Path, font_path: Path) -> None:
    if not font_path.is_file():
        raise SystemExit(
            f"한글 폰트를 찾을 수 없습니다: {font_path}\n"
            "  --font 로 TTF 경로를 지정하세요(예: 나눔고딕 NanumGothic.ttf)."
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    for doc in DEMO_DOCS:
        data = _render(doc, font_path)
        (out_dir / doc.filename).write_bytes(data)
        total_bytes += len(data)

    print(f"PDF {len(DEMO_DOCS)}건 생성 · 총 {total_bytes / 1024 / 1024:.1f}MB → {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="문서관리 데모 PDF 생성(로컬 전용)")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help=f"출력 디렉터리(기본: {DEFAULT_OUT_DIR})"
    )
    parser.add_argument(
        "--font", type=Path, default=DEFAULT_FONT, help=f"한글 TTF 경로(기본: {DEFAULT_FONT})"
    )
    args = parser.parse_args()
    _run(args.out, args.font)


if __name__ == "__main__":
    main()
