#!/usr/bin/env python3
"""
Load runner for agent-memory-server simulation testing.

Runs concurrent replay sessions against the server and collects metrics.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx


@dataclass
class SessionMetrics:
    """Metrics collected for a single session."""

    session_id: str
    client_id: int
    scenario: str
    turns_replayed: int = 0
    put_latencies_ms: list[float] = field(default_factory=list)
    get_latencies_ms: list[float] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    summary_first_seen_turn: int | None = None
    final_visible_message_count: int = 0
    final_context_present: bool = False
    final_context_length: int = 0
    message_order_violations: int = 0
    missing_recent_messages: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    # Enhanced failure tracking
    recent_messages_lost: list[dict[str, Any]] = field(default_factory=list)
    ordering_errors: list[dict[str, Any]] = field(default_factory=list)
    summary_issues: list[dict[str, Any]] = field(default_factory=list)
    consistency_errors: list[dict[str, Any]] = field(default_factory=list)
    expected_summary_at_turn: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "scenario": self.scenario,
            "turns_replayed": self.turns_replayed,
            "put_latency": summarize_latencies(self.put_latencies_ms),
            "get_latency": summarize_latencies(self.get_latencies_ms),
            "error_count": len(self.errors),
            "errors": self.errors[:10],  # First 10 errors
            "summary_first_seen_turn": self.summary_first_seen_turn,
            "final_visible_message_count": self.final_visible_message_count,
            "final_context_present": self.final_context_present,
            "final_context_length": self.final_context_length,
            "message_order_violations": self.message_order_violations,
            "missing_recent_messages": self.missing_recent_messages,
            "total_runtime_ms": (self.end_time - self.start_time) * 1000,
            # Enhanced failure details
            "failure_details": {
                "recent_messages_lost": self.recent_messages_lost[:10],
                "ordering_errors": self.ordering_errors[:10],
                "summary_issues": self.summary_issues[:10],
                "consistency_errors": self.consistency_errors[:10],
            },
            "expected_summary_at_turn": self.expected_summary_at_turn,
        }


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize_latencies(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "min_ms": 0.0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "count": len(values),
        "min_ms": round(min(values), 2),
        "avg_ms": round(sum(values) / len(values), 2),
        "p50_ms": round(percentile(values, 0.50), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
        "p99_ms": round(percentile(values, 0.99), 2),
        "max_ms": round(max(values), 2),
    }


def generate_conversation(
    num_messages: int, message_size: str = "normal"
) -> list[dict[str, Any]]:
    """Generate a synthetic conversation with the specified number of messages."""
    messages = []
    topics = [
        "project planning",
        "code review",
        "debugging",
        "architecture",
        "testing",
        "deployment",
        "documentation",
        "performance",
    ]

    size_map = {"small": 50, "normal": 200, "large": 1000}
    content_length = size_map.get(message_size, 200)

    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        topic = topics[i % len(topics)]
        content = f"Message {i+1} about {topic}. " + (
            "Context details. " * (content_length // 20)
        )
        messages.append(
            {
                "id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": role,
                "content": content[:content_length],
            }
        )
    return messages


def load_or_generate_dataset(path: Path | None, num_messages: int) -> dict[str, Any]:
    """Load dataset from file or generate synthetic one."""
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "data": {"dataset_id": f"synthetic-{num_messages}"},
        "namespace": "simulation",
        "user_id": "sim-user",
        "messages": generate_conversation(num_messages),
    }


async def run_session(
    client_id: int,
    base_url: str,
    dataset: dict[str, Any],
    scenario: str,
    context_window_max: int | None = None,
    sleep_between_turns: float = 0.0,
    timeout: float = 60.0,
) -> SessionMetrics:
    """Run a single session replay and collect metrics."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    session_id = f"sim-{scenario}-{client_id}-{timestamp}-{uuid.uuid4().hex[:6]}"
    namespace = dataset.get("namespace", "simulation")
    user_id = dataset.get("user_id", "sim-user")
    messages = dataset.get("messages", [])

    metrics = SessionMetrics(
        session_id=session_id, client_id=client_id, scenario=scenario
    )
    metrics.start_time = perf_counter()

    previous_message_ids: list[str] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as http_client:
        # Reset session first
        try:
            await http_client.delete(
                f"/v1/working-memory/{session_id}", params={"namespace": namespace}
            )
        except Exception:
            pass

        for turn_index, _message in enumerate(messages, 1):
            try:
                # Build payload with messages up to this turn
                payload = {
                    "messages": messages[:turn_index],
                    "namespace": namespace,
                    "user_id": user_id,
                }
                # Query params for PUT (no user_id needed, it's in body)
                put_params = {"namespace": namespace}
                if context_window_max:
                    put_params["context_window_max"] = str(context_window_max)

                # Query params for GET (must include user_id for key matching)
                get_params = {"namespace": namespace, "user_id": user_id}
                if context_window_max:
                    get_params["context_window_max"] = str(context_window_max)

                # PUT request
                start = perf_counter()
                put_resp = await http_client.put(
                    f"/v1/working-memory/{session_id}", json=payload, params=put_params
                )
                put_latency = (perf_counter() - start) * 1000
                put_resp.raise_for_status()
                metrics.put_latencies_ms.append(put_latency)

                # GET request
                start = perf_counter()
                get_resp = await http_client.get(
                    f"/v1/working-memory/{session_id}", params=get_params
                )
                get_latency = (perf_counter() - start) * 1000
                get_resp.raise_for_status()
                metrics.get_latencies_ms.append(get_latency)

                state = get_resp.json()
                visible_messages = state.get("messages") or []
                context = state.get("context") or ""

                # === FAILURE MODE 1: Recent messages getting lost ===
                # The N most recent messages we just sent should be in visible_messages
                sent_messages = messages[:turn_index]
                sent_contents = [m.get("content", "") for m in sent_messages]
                visible_contents = [m.get("content", "") for m in visible_messages]

                # Check the last few messages (recent window) are present
                # If we have 10+ messages, we expect at least some to be visible
                recent_window = min(10, len(sent_messages))
                recent_sent = sent_contents[-recent_window:]
                missing_recent = [c for c in recent_sent if c not in visible_contents]
                if missing_recent:
                    metrics.missing_recent_messages += len(missing_recent)
                    metrics.recent_messages_lost.append(
                        {
                            "turn": turn_index,
                            "expected_recent": len(recent_sent),
                            "missing_count": len(missing_recent),
                            "missing_preview": [m[:50] for m in missing_recent[:3]],
                        }
                    )

                # === FAILURE MODE 2: Messages coming back in the wrong order ===
                current_ids = [m.get("id") for m in visible_messages if m]
                for prev_id in previous_message_ids:
                    if prev_id in current_ids:
                        prev_idx = previous_message_ids.index(prev_id)
                        curr_idx = current_ids.index(prev_id)
                        for other_id in previous_message_ids[prev_idx + 1 :]:
                            if other_id in current_ids:
                                other_curr_idx = current_ids.index(other_id)
                                if other_curr_idx < curr_idx:
                                    metrics.message_order_violations += 1
                                    metrics.ordering_errors.append(
                                        {
                                            "turn": turn_index,
                                            "expected_before": prev_id,
                                            "expected_after": other_id,
                                            "actual_order": "reversed",
                                        }
                                    )

                # === FAILURE MODE 3: Summaries not appearing or being empty ===
                # Track when we expect summarization to start
                summarization_threshold = context_window_max or 20  # Default threshold
                if turn_index >= summarization_threshold:
                    if metrics.expected_summary_at_turn is None:
                        metrics.expected_summary_at_turn = turn_index

                    # After threshold, context should have content
                    if not context:
                        metrics.summary_issues.append(
                            {
                                "turn": turn_index,
                                "issue": "summary_missing",
                                "detail": f"Expected summary after {summarization_threshold} turns, none found",
                            }
                        )
                    elif len(context.strip()) < 20:
                        metrics.summary_issues.append(
                            {
                                "turn": turn_index,
                                "issue": "summary_empty_or_trivial",
                                "detail": f"Summary too short ({len(context)} chars)",
                                "context_preview": context[:100],
                            }
                        )

                # Check for summary first appearance
                if metrics.summary_first_seen_turn is None and context:
                    metrics.summary_first_seen_turn = turn_index

                # === FAILURE MODE 4: Session reads becoming inconsistent ===
                # Compare the PUT response with immediate GET response
                put_state = put_resp.json()
                put_msg_count = len(put_state.get("messages") or [])
                get_msg_count = len(visible_messages)

                # After PUT, GET should return same or similar state
                if abs(put_msg_count - get_msg_count) > 1:
                    metrics.consistency_errors.append(
                        {
                            "turn": turn_index,
                            "issue": "read_after_write_mismatch",
                            "put_message_count": put_msg_count,
                            "get_message_count": get_msg_count,
                            "difference": abs(put_msg_count - get_msg_count),
                        }
                    )

                previous_message_ids = current_ids
                metrics.turns_replayed = turn_index
                metrics.final_visible_message_count = len(visible_messages)
                metrics.final_context_present = bool(context)
                metrics.final_context_length = len(context) if context else 0

                if sleep_between_turns > 0:
                    await asyncio.sleep(sleep_between_turns)

            except Exception as e:
                metrics.errors.append(
                    {
                        "turn": turn_index,
                        "error": str(e),
                        "type": type(e).__name__,
                    }
                )

    metrics.end_time = perf_counter()
    return metrics


async def run_concurrent_sessions(
    num_sessions: int,
    base_url: str,
    dataset: dict[str, Any],
    scenario: str,
    context_window_max: int | None = None,
    stagger_start_ms: float = 100.0,
) -> list[SessionMetrics]:
    """Run multiple sessions concurrently with staggered starts."""
    tasks = []
    for i in range(num_sessions):
        if i > 0 and stagger_start_ms > 0:
            await asyncio.sleep(stagger_start_ms / 1000)
        task = asyncio.create_task(
            run_session(i, base_url, dataset, scenario, context_window_max)
        )
        tasks.append(task)

    return await asyncio.gather(*tasks, return_exceptions=False)


def aggregate_results(results: list[SessionMetrics], scenario: str) -> dict[str, Any]:
    """Aggregate metrics from multiple sessions."""
    all_put = [lat for r in results for lat in r.put_latencies_ms]
    all_get = [lat for r in results for lat in r.get_latencies_ms]
    total_errors = sum(len(r.errors) for r in results)
    total_order_violations = sum(r.message_order_violations for r in results)

    # Aggregate failure details
    total_recent_lost = sum(r.missing_recent_messages for r in results)
    total_ordering_errors = sum(len(r.ordering_errors) for r in results)
    total_summary_issues = sum(len(r.summary_issues) for r in results)
    total_consistency_errors = sum(len(r.consistency_errors) for r in results)

    # Collect sample errors for reporting
    sample_recent_lost = [e for r in results for e in r.recent_messages_lost[:2]][:10]
    sample_ordering = [e for r in results for e in r.ordering_errors[:2]][:10]
    sample_summary = [e for r in results for e in r.summary_issues[:2]][:10]
    sample_consistency = [e for r in results for e in r.consistency_errors[:2]][:10]

    return {
        "scenario": scenario,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_sessions": len(results),
        "total_turns": sum(r.turns_replayed for r in results),
        "aggregate_put_latency": summarize_latencies(all_put),
        "aggregate_get_latency": summarize_latencies(all_get),
        "total_errors": total_errors,
        "error_rate_pct": round(
            total_errors / max(1, sum(r.turns_replayed for r in results)) * 100, 4
        ),
        "total_order_violations": total_order_violations,
        "sessions_with_summary": sum(1 for r in results if r.final_context_present),
        # Enhanced failure tracking
        "failure_summary": {
            "recent_messages_lost": total_recent_lost,
            "ordering_errors": total_ordering_errors,
            "summary_issues": total_summary_issues,
            "consistency_errors": total_consistency_errors,
            "total_issues": (
                total_recent_lost
                + total_ordering_errors
                + total_summary_issues
                + total_consistency_errors
            ),
        },
        "failure_samples": {
            "recent_messages_lost": sample_recent_lost,
            "ordering_errors": sample_ordering,
            "summary_issues": sample_summary,
            "consistency_errors": sample_consistency,
        },
        "per_session": [r.to_dict() for r in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run concurrent load test sessions")
    parser.add_argument(
        "--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--concurrent-sessions",
        type=int,
        default=int(os.getenv("CONCURRENT_SESSIONS", "5")),
    )
    parser.add_argument(
        "--session-length", type=int, default=int(os.getenv("SESSION_LENGTH", "50"))
    )
    parser.add_argument("--scenario", default=os.getenv("SCENARIO", "custom"))
    parser.add_argument("--context-window-max", type=int, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("/results"))
    parser.add_argument("--stagger-ms", type=float, default=100.0)
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()

    print(
        f"Starting load test: {args.concurrent_sessions} sessions, {args.session_length} messages each"
    )
    print(f"Target: {args.base_url}")

    dataset = load_or_generate_dataset(args.dataset, args.session_length)

    start = perf_counter()
    results = await run_concurrent_sessions(
        num_sessions=args.concurrent_sessions,
        base_url=args.base_url,
        dataset=dataset,
        scenario=args.scenario,
        context_window_max=args.context_window_max,
        stagger_start_ms=args.stagger_ms,
    )
    total_time = perf_counter() - start

    summary = aggregate_results(results, args.scenario)
    summary["total_runtime_seconds"] = round(total_time, 2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {args.scenario}")
    print(f"{'='*60}")
    print(f"Sessions: {summary['num_sessions']}, Total turns: {summary['total_turns']}")
    print(f"Runtime: {summary['total_runtime_seconds']}s")
    print(f"PUT p95: {summary['aggregate_put_latency']['p95_ms']}ms")
    print(f"GET p95: {summary['aggregate_get_latency']['p95_ms']}ms")
    print(f"Errors: {summary['total_errors']} ({summary['error_rate_pct']}%)")
    print(f"Order violations: {summary['total_order_violations']}")

    # Save results
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_file = (
        args.output_dir
        / f"results_{args.scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_file.write_text(json.dumps(summary, indent=2))
    print(f"\nResults saved to: {output_file}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
