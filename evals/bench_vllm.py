"""vLLM 순수 서빙 지연·동시처리 벤치 (H15-2 부록).

의존성 0(표준 라이브러리만) — 개발서버(사내망)와 맥북(터널)에서 같은 스크립트로 재서 비교한다.
실측: TTFT(첫 토큰), 총응답, 생성 토큰/초. 동시성 1·5·10.

실행: python3 bench_vllm.py <base_url> <model> [label]
"""

from __future__ import annotations

import json
import statistics as st
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPTS = [
    "아파트 관리규약에서 공사 가능 시간을 세 문장으로 설명해줘.",
    "커뮤니티시설 이용 시간과 예약 방법을 정리해줘.",
    "관리비 항목 중 공용전기와 난방비의 차이를 설명해줘.",
    "승강기에 갇혔을 때 대응 절차를 순서대로 알려줘.",
    "재활용 분리배출 요령을 항목별로 정리해줘.",
]
MAX_TOKENS = 200


def one_call(base_url: str, model: str, prompt: str) -> dict:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "temperature": 0.2,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    ttft = None
    tokens = 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0].get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta.get("content"):
                tokens += 1
                if ttft is None:
                    ttft = (time.perf_counter() - started) * 1000
    total = (time.perf_counter() - started) * 1000
    return {"ttft_ms": ttft or total, "total_ms": total, "tokens": tokens}


def run(base_url: str, model: str, concurrency: int, rounds: int = 3) -> dict:
    calls = [PROMPTS[i % len(PROMPTS)] for i in range(concurrency * rounds)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda p: one_call(base_url, model, p), calls))
    wall = time.perf_counter() - started
    ttfts = sorted(r["ttft_ms"] for r in results)
    totals = sorted(r["total_ms"] for r in results)
    toks = sum(r["tokens"] for r in results)

    def p(values: list[float], q: float) -> float:
        return values[min(len(values) - 1, int(len(values) * q))]

    return {
        "concurrency": concurrency,
        "requests": len(results),
        "ttft_p50": round(st.median(ttfts)),
        "ttft_p95": round(p(ttfts, 0.95)),
        "total_p50": round(st.median(totals)),
        "total_p95": round(p(totals, 0.95)),
        "tokens_per_s": round(toks / wall, 1),
        "req_per_min": round(len(results) / wall * 60, 1),
    }


def main() -> None:
    base_url, model = sys.argv[1], sys.argv[2]
    label = sys.argv[3] if len(sys.argv) > 3 else "unlabeled"
    print(f"# {label} · {base_url} · {model}")
    print(f"{'동시':>4} {'요청':>4} {'TTFT p50':>9} {'p95':>7} {'총 p50':>8} {'p95':>8} {'tok/s':>7} {'req/분':>7}")
    out = []
    for c in (1, 5, 10):
        r = run(base_url, model, c)
        out.append(r)
        print(
            f"{r['concurrency']:>4} {r['requests']:>4} {r['ttft_p50']:>9} {r['ttft_p95']:>7} "
            f"{r['total_p50']:>8} {r['total_p95']:>8} {r['tokens_per_s']:>7} {r['req_per_min']:>7}"
        )
    print(json.dumps({"label": label, "results": out}, ensure_ascii=False))


main()
