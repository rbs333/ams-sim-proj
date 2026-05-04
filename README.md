# Agent Memory Server — Simulation & Load Testing

This repository contains a simulation and load-testing harness for the [agent-memory-server](https://github.com/redis/agent-memory-server). The goal is to stress-test the server under realistic workloads, identify breaking points, and validate that long conversations stay correct and responsive at scale.

---

## What Is This Testing?

The harness simulates many concurrent AI agent sessions, each replaying a conversation turn-by-turn against the live server. Every turn performs a `PUT` (write) followed by a `GET` (read) on the working-memory endpoint and collects latency and correctness metrics.

The core story under test is **long conversation memory**:

> *As an agent, I can keep a long conversation in working memory and still get useful recent context after the session grows large.*

Specifically the tests look for these failure modes:

| Failure Mode | Description |
|---|---|
| Recent messages lost | The last N messages sent are not returned by `GET` |
| Message ordering issues | Messages come back in the wrong order |
| Empty or missing summaries | Summarization triggers but `context` is blank |
| Read-after-write inconsistency | `PUT` and `GET` return different message counts |
| Latency spikes / timeouts | `PUT` p95 > 1 s or `GET` p95 > 500 ms |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Docker Compose Stack                      │
│                                                              │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐        │
│  │   Redis 8   │   │  API Server │   │ Task Worker │        │
│  └─────────────┘   └─────────────┘   └─────────────┘        │
│                            │                                  │
│          ┌─────────────────┴──────────────────┐              │
│          │         Load Test Orchestrator      │              │
│          │         (simulation/orchestrator.py)│              │
│          └───────┬──────────────┬─────────────┘              │
│                  ▼              ▼              ▼              │
│           ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│           │ Client 1 │  │ Client 2 │  │ Client N │          │
│           └──────────┘  └──────────┘  └──────────┘          │
└──────────────────────────────────────────────────────────────┘
```

**Services**

| Service | Role |
|---|---|
| `redis` | Redis 8 persistence layer |
| `api` | agent-memory-server HTTP API |
| `task-worker` | Background summarization worker |
| `orchestrator` | Runs scenarios and writes result JSON |
| `sim-client` | Scalable load client (used with `--scale`) |

---

## Prerequisites

- **Docker** and **Docker Compose** (v2)
- An `.env` file at the repo root with any required API keys (e.g. `OPENAI_API_KEY`). The file is optional — services start without it, but summarization requires a valid LLM key.

```
OPENAI_API_KEY=sk-...
```

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/rbs333/ams-sim-proj.git
cd ams-sim-proj

# 2. (Optional) create .env with your OpenAI key
echo "OPENAI_API_KEY=sk-..." > .env

# 3. Run the full simulation suite (all predefined scenarios)
docker compose -f docker-compose-simulation.yml up

# 4. Results land in ./simulation_results/
```

---

## Running Specific Scenarios

```bash
# Run a single named scenario
docker compose -f docker-compose-simulation.yml run --rm orchestrator \
  --scenario medium-heavy

# Override session count and length for a named scenario
docker compose -f docker-compose-simulation.yml run --rm orchestrator \
  --scenario long-heavy \
  --concurrent-sessions 20 \
  --session-length 100

# Fully custom parameters (no named scenario required)
docker compose -f docker-compose-simulation.yml run --rm orchestrator \
  --concurrent-sessions 30 \
  --session-length 150 \
  --context-window-max 4000

# Run every scenario in sequence
docker compose -f docker-compose-simulation.yml run --rm orchestrator \
  --scenario all

# Generate a full heat-map grid (session_length × concurrent_sessions)
docker compose -f docker-compose-simulation.yml run --rm orchestrator \
  --scenario heatmap
```

### Scale Load Clients Manually

```bash
# Run 25 independent load clients in parallel
docker compose -f docker-compose-simulation.yml up --scale sim-client=25
```

### Optional Debug UI

```bash
# Start Redis Insight on http://localhost:16381
docker compose -f docker-compose-simulation.yml --profile debug up redis-insight
```

---

## Predefined Scenarios

| Scenario | Session Length | Concurrent Sessions | Purpose |
|---|---|---|---|
| `baseline` | 10 | 1 | Establish baseline latency |
| `short-light` | 10 | 10 | Light concurrent load |
| `short-heavy` | 10 | 50 | Heavy concurrent load, short sessions |
| `medium-light` | 50 | 10 | Medium sessions, light load |
| `medium-heavy` | 50 | 25 | Medium sessions, moderate load |
| `long-light` | 200 | 5 | Long sessions, light load |
| `long-heavy` | 200 | 15 | Long sessions, moderate load |
| `very-long` | 500 | 5 | Summarization stress test |
| `extreme` | 100 | 50 | Maximum concurrent load |

---

## Pass / Fail Criteria

| Metric | Pass | Warning | Fail |
|---|---|---|---|
| PUT p95 latency | < 500 ms | 500 – 1000 ms | > 1000 ms |
| GET p95 latency | < 200 ms | 200 – 500 ms | > 500 ms |
| Error rate | 0 % | < 1 % | > 1 % |
| Message order violations | 0 | — | > 0 |
| Recent messages missing | 0 | — | > 0 |
| Summary present (long sessions) | Yes | — | No |

---

## Single-Session Replay

For targeted debugging you can replay one conversation file without Docker:

```bash
pip install httpx

python replay_story1_session.py simulation/datasets/<file>.json \
  --base-url http://localhost:8000 \
  --reset-session \
  --context-window-max 4000 \
  --snapshot-file /tmp/snapshots.jsonl
```

---

## Results

All output lands in `./simulation_results/`:

| File | Contents |
|---|---|
| `summary_<timestamp>.json` | Aggregate metrics and pass/fail status per scenario |
| `heatmap_data.json` | Full grid data for heat-map visualisation |
| `results_<scenario>_<timestamp>.json` | Raw per-session metrics |

Heat-map analysis can be run on existing data:

```bash
python simulation/analyze_heatmap.py simulation_results/heatmap_data.json
```

---

## Repository Layout

```
.
├── docker-compose-simulation.yml   # Full simulation stack
├── replay_story1_session.py        # Single-session replay tool
├── long_conversation_memory.md     # User story: long conversation memory
├── system_simulation_test.md       # Test harness specification
├── simulation/
│   ├── Dockerfile                  # Image for orchestrator and sim-client
│   ├── orchestrator.py             # Scenario runner; writes result JSON
│   ├── load_runner.py              # Concurrent session engine
│   ├── analyze_heatmap.py          # Heat-map analysis script
│   └── datasets/                   # Conversation fixture files
└── simulation_results/             # Output directory (git-ignored)
```
