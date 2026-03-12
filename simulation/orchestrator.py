#!/usr/bin/env python3
"""
Orchestrator for running simulation scenarios against agent-memory-server.

Runs predefined scenarios or custom configurations and generates heat map data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from load_runner import (
    aggregate_results,
    load_or_generate_dataset,
    run_concurrent_sessions,
)

# Predefined scenarios: (session_length, concurrent_sessions)
SCENARIOS = {
    "baseline": (10, 1),
    "short-light": (10, 10),
    "short-heavy": (10, 50),
    "medium-light": (50, 10),
    "medium-heavy": (50, 25),
    "long-light": (200, 5),
    "long-heavy": (200, 15),
    "very-long": (500, 5),
    "extreme": (100, 50),
}

# Heat map grid for comprehensive testing
HEATMAP_GRID = {
    "session_lengths": [10, 25, 50, 100, 200, 500],
    "concurrent_sessions": [1, 5, 10, 25, 50],
}


def evaluate_results(results: dict[str, Any]) -> dict[str, str]:
    """Evaluate results against pass criteria."""
    put_p95 = results["aggregate_put_latency"]["p95_ms"]
    get_p95 = results["aggregate_get_latency"]["p95_ms"]
    error_rate = results["error_rate_pct"]
    order_violations = results["total_order_violations"]

    status = {}

    # PUT latency
    if put_p95 < 500:
        status["put_latency"] = "PASS"
    elif put_p95 < 1000:
        status["put_latency"] = "WARNING"
    else:
        status["put_latency"] = "FAIL"

    # GET latency
    if get_p95 < 200:
        status["get_latency"] = "PASS"
    elif get_p95 < 500:
        status["get_latency"] = "WARNING"
    else:
        status["get_latency"] = "FAIL"

    # Error rate
    if error_rate == 0:
        status["errors"] = "PASS"
    elif error_rate < 1:
        status["errors"] = "WARNING"
    else:
        status["errors"] = "FAIL"

    # Order violations
    status["ordering"] = "PASS" if order_violations == 0 else "FAIL"

    # Enhanced failure checks
    failure_summary = results.get("failure_summary", {})

    # Recent messages lost
    recent_lost = failure_summary.get("recent_messages_lost", 0)
    status["recent_messages"] = "PASS" if recent_lost == 0 else "FAIL"

    # Summary issues
    summary_issues = failure_summary.get("summary_issues", 0)
    status["summaries"] = "PASS" if summary_issues == 0 else "WARNING"

    # Consistency errors
    consistency_errors = failure_summary.get("consistency_errors", 0)
    status["consistency"] = "PASS" if consistency_errors == 0 else "FAIL"

    # Overall
    if all(v == "PASS" for v in status.values()):
        status["overall"] = "PASS"
    elif any(v == "FAIL" for v in status.values()):
        status["overall"] = "FAIL"
    else:
        status["overall"] = "WARNING"

    return status


async def run_scenario(
    name: str,
    session_length: int,
    concurrent_sessions: int,
    base_url: str,
    context_window_max: int | None = None,
) -> dict[str, Any]:
    """Run a single scenario and return results."""
    print(f"\n{'='*60}")
    print(f"Running scenario: {name}")
    print(f"  Sessions: {concurrent_sessions}, Length: {session_length} messages")
    print(f"{'='*60}")

    dataset = load_or_generate_dataset(None, session_length)

    results = await run_concurrent_sessions(
        num_sessions=concurrent_sessions,
        base_url=base_url,
        dataset=dataset,
        scenario=name,
        context_window_max=context_window_max,
    )

    summary = aggregate_results(results, name)
    summary["session_length"] = session_length
    summary["concurrent_sessions"] = concurrent_sessions
    summary["evaluation"] = evaluate_results(summary)

    # Print standard metrics
    print(f"  PUT p95: {summary['aggregate_put_latency']['p95_ms']}ms")
    print(f"  GET p95: {summary['aggregate_get_latency']['p95_ms']}ms")
    print(f"  Errors: {summary['total_errors']}")

    # Print failure breakdown
    fs = summary.get("failure_summary", {})
    if fs.get("total_issues", 0) > 0:
        print(f"  --- Failure Breakdown ---")
        if fs.get("recent_messages_lost", 0) > 0:
            print(f"  ❌ Recent messages lost: {fs['recent_messages_lost']}")
        if fs.get("ordering_errors", 0) > 0:
            print(f"  ❌ Ordering errors: {fs['ordering_errors']}")
        if fs.get("summary_issues", 0) > 0:
            print(f"  ⚠️  Summary issues: {fs['summary_issues']}")
        if fs.get("consistency_errors", 0) > 0:
            print(f"  ❌ Consistency errors: {fs['consistency_errors']}")

    print(f"  Status: {summary['evaluation']['overall']}")

    return summary


async def run_heatmap(base_url: str, output_dir: Path) -> dict[str, Any]:
    """Run full heat map grid and save results."""
    heatmap_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "grid": HEATMAP_GRID,
        "results": [],
    }

    for length in HEATMAP_GRID["session_lengths"]:
        for sessions in HEATMAP_GRID["concurrent_sessions"]:
            name = f"heatmap-{length}x{sessions}"
            result = await run_scenario(name, length, sessions, base_url)
            fs = result.get("failure_summary", {})
            heatmap_data["results"].append(
                {
                    "session_length": length,
                    "concurrent_sessions": sessions,
                    "put_p95_ms": result["aggregate_put_latency"]["p95_ms"],
                    "get_p95_ms": result["aggregate_get_latency"]["p95_ms"],
                    "error_rate_pct": result["error_rate_pct"],
                    "order_violations": result["total_order_violations"],
                    "recent_messages_lost": fs.get("recent_messages_lost", 0),
                    "summary_issues": fs.get("summary_issues", 0),
                    "consistency_errors": fs.get("consistency_errors", 0),
                    "status": result["evaluation"]["overall"],
                }
            )

    output_file = output_dir / "heatmap_data.json"
    output_file.write_text(json.dumps(heatmap_data, indent=2))
    print(f"\nHeat map data saved to: {output_file}")

    return heatmap_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orchestrate simulation scenarios")
    parser.add_argument(
        "--base-url", default=os.getenv("API_BASE_URL", "http://api:8000")
    )
    parser.add_argument(
        "--scenario", choices=list(SCENARIOS.keys()) + ["all", "heatmap"]
    )
    parser.add_argument(
        "--concurrent-sessions", type=int, help="Override concurrent sessions"
    )
    parser.add_argument("--session-length", type=int, help="Override session length")
    parser.add_argument("--context-window-max", type=int, default=4000)
    parser.add_argument("--output-dir", type=Path, default=Path("/results"))
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_results = []

    if args.scenario == "heatmap":
        await run_heatmap(args.base_url, args.output_dir)
    elif args.scenario == "all":
        for name, (length, sessions) in SCENARIOS.items():
            result = await run_scenario(
                name, length, sessions, args.base_url, args.context_window_max
            )
            all_results.append(result)
    elif args.scenario:
        length, sessions = SCENARIOS[args.scenario]
        if args.session_length:
            length = args.session_length
        if args.concurrent_sessions:
            sessions = args.concurrent_sessions
        result = await run_scenario(
            args.scenario, length, sessions, args.base_url, args.context_window_max
        )
        all_results.append(result)
    else:
        # Custom run
        length = args.session_length or 50
        sessions = args.concurrent_sessions or 5
        result = await run_scenario(
            "custom", length, sessions, args.base_url, args.context_window_max
        )
        all_results.append(result)

    if all_results:
        summary_file = (
            args.output_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        summary_file.write_text(json.dumps(all_results, indent=2))
        print(f"\nSummary saved to: {summary_file}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
