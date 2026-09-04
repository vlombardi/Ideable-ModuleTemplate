#!/usr/bin/env python3
"""Constant-concurrency load generator that reports throughput AND status codes over time.

Written for the horizontal-scale work's acceptance criteria, which cannot be answered by a throughput number alone:

- "throughput >=2.5x the single-replica figure" needs requests/second;
- "zero 5xx for the entire deploy" needs the status breakdown *per second*, because a rolling deploy
  that drops requests for one second looks fine in a total that is 99.9% 2xx;
- "docker kill on one replica -> no client-visible errors" needs the same, aligned to when the kill
  happened.

`ab` reports totals only, and `hey` is not installed here. Deliberately dependency-free (stdlib
asyncio + urllib in threads) so it runs anywhere the repo's own tooling runs.

Usage:
    scripts/dev/loadtest.py URL --seconds 30 --concurrency 50 [--header "Authorization: Bearer …"]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--header", action="append", default=[])
    ap.add_argument("--json", action="store_true", help="emit the summary as JSON")
    # The client timeout must be able to exceed the SERVER's pool timeout, or the two failure modes
    # cannot be told apart. With both at 10s (the default DB_POOL_TIMEOUT), a saturated backend
    # produces client TimeoutErrors at the same instant it would produce pool-exhaustion 500s, and
    # "no 5xx observed" then means "we stopped watching", not "the server coped".
    ap.add_argument("--timeout", type=float, default=10.0,
                    help="per-request client timeout in seconds (raise above DB_POOL_TIMEOUT to "
                         "distinguish server pool exhaustion from client impatience)")
    args = ap.parse_args()

    headers = {}
    for raw in args.header:
        key, _, value = raw.partition(":")
        headers[key.strip()] = value.strip()

    stop = threading.Event()
    lock = threading.Lock()
    codes: Counter[str] = Counter()
    per_second: defaultdict[int, Counter[str]] = defaultdict(Counter)
    latencies: list[float] = []
    started = time.monotonic()

    def worker() -> None:
        while not stop.is_set():
            request = urllib.request.Request(args.url, headers=headers)
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=args.timeout) as response:
                    response.read()
                    code = str(response.status)
            except urllib.error.HTTPError as exc:
                code = str(exc.code)
            except Exception as exc:  # noqa: BLE001 — a dropped connection IS the finding
                code = type(exc).__name__
            elapsed = time.monotonic() - t0
            bucket = int(time.monotonic() - started)
            with lock:
                codes[code] += 1
                per_second[bucket][code] += 1
                latencies.append(elapsed)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(args.concurrency)]
    for thread in threads:
        thread.start()
    time.sleep(args.seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=args.timeout + 2)

    duration = time.monotonic() - started
    total = sum(codes.values())
    latencies.sort()

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))] * 1000 if latencies else 0.0

    # "Bad" is anything that is not a 2xx/3xx: a 5xx, a refused connection, a timeout. A rolling
    # deploy claim is about all of those, not only about HTTP 500s.
    bad = {code: n for code, n in codes.items() if not code.startswith(("2", "3"))}
    summary = {
        "url": args.url,
        "seconds": round(duration, 2),
        "concurrency": args.concurrency,
        "client_timeout_s": args.timeout,
        "requests": total,
        "rps": round(total / duration, 1) if duration else 0.0,
        "p50_ms": round(pct(0.50), 1),
        "p95_ms": round(pct(0.95), 1),
        # p99 too: Appendix B of the scalability plan asks for both, and a p95 alone hides the tail
        # that actually pages someone. Adding it here rather than post-processing keeps every
        # measurement in the plan comparable, taken by the same tool.
        "p99_ms": round(pct(0.99), 1),
        "codes": dict(codes),
        "bad": bad,
        "bad_total": sum(bad.values()),
        "seconds_with_bad": sorted(
            second for second, counter in per_second.items()
            if any(not c.startswith(("2", "3")) for c in counter)
        ),
    }
    if args.json:
        print(json.dumps(summary))
    else:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
