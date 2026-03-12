# System Simulation Test Harness

## Overview

This document specifies a **monkey wrench testing harness** for the agent-memory-server. The goal is to stress test the system by running many concurrent clients with varying session lengths to identify breaking points and production-level concerns.

## Objectives

1. **Identify breaking points**: Determine where the system starts to fail as we scale:
   - Session length (number of messages per session)
   - Number of concurrent active sessions
   - Combined load (session length × concurrent sessions)

2. **Create a heat map**: Map the relationship between session length and concurrent sessions to identify:
   - Latency degradation thresholds
   - Memory/resource exhaustion points
   - Summarization failures
   - Message ordering issues
   - Session read inconsistencies

3. **Validate long conversation memory behavior** (per `long_conversation_memory.md`):
   - Recent messages getting lost
   - Messages coming back in wrong order
   - Summaries not appearing or being empty
   - Session reads becoming inconsistent after many updates

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Redis 8    │  │  API Server  │  │ Task Worker  │          │
│  │   (redis)    │  │    (api)     │  │(task-worker) │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         │                 │                 │                   │
│         └─────────────────┴─────────────────┘                   │
│                           │                                      │
│  ┌────────────────────────┴────────────────────────┐            │
│  │              Load Test Orchestrator              │            │
│  │           (simulation-orchestrator)              │            │
│  └──────────────────────────────────────────────────┘            │
│                           │                                      │
│         ┌─────────────────┼─────────────────┐                   │
│         ▼                 ▼                 ▼                   │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐            │
│  │  Client 1  │    │  Client 2  │    │  Client N  │            │
│  │ (sim-1)    │    │ (sim-2)    │    │ (sim-N)    │            │
│  └────────────┘    └────────────┘    └────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Test Scenarios

### Scenario Matrix

| Scenario | Session Length | Concurrent Sessions | Purpose |
|----------|---------------|---------------------|---------|
| Baseline | 10 messages | 1 | Establish baseline latency |
| Short-Light | 10 messages | 10 | Light concurrent load |
| Short-Heavy | 10 messages | 50 | Heavy concurrent load, short sessions |
| Medium-Light | 50 messages | 10 | Medium sessions, light load |
| Medium-Heavy | 50 messages | 25 | Medium sessions, moderate load |
| Long-Light | 200 messages | 5 | Long sessions, light load |
| Long-Heavy | 200 messages | 15 | Long sessions, moderate load |
| Very-Long | 500 messages | 5 | Very long sessions (summarization stress) |
| Extreme | 100 messages | 50 | Maximum concurrent load |

### Conversation Types

1. **Short conversation** (10 messages): Quick Q&A exchanges
2. **Medium conversation** (50 messages): Extended discussion with context
3. **Long conversation** (200 messages): Full session requiring summarization
4. **Very long conversation** (500 messages): Stress test for summarization

## Metrics Collected

### Per-Turn Metrics
- `put_latency_ms`: Time to write a message
- `get_latency_ms`: Time to read session state
- `visible_message_count`: Number of messages returned
- `context_present`: Whether summarization has occurred
- `context_length`: Length of summary context

### Aggregate Metrics
- `p50_latency`, `p95_latency`, `p99_latency`, `max_latency`
- `error_count`: Number of failed requests
- `summary_first_seen_turn`: When summarization kicked in
- `message_order_violations`: Messages returned out of order
- `missing_recent_messages`: Expected messages not present

### Heat Map Dimensions
- X-axis: Number of concurrent sessions (1, 5, 10, 25, 50)
- Y-axis: Session length (10, 50, 100, 200, 500 messages)
- Z-axis (color): Metric value (latency, error rate, etc.)

## Expected Failure Modes

Based on `long_conversation_memory.md`:

1. **Recent messages lost**: Last N messages not appearing in GET response
2. **Message ordering issues**: Messages returned in wrong order
3. **Empty summaries**: Summarization triggered but context is empty
4. **Inconsistent reads**: Same session returns different data on consecutive reads
5. **Latency spikes**: PUT/GET latency exceeds acceptable thresholds (>1000ms)
6. **Timeouts**: Requests timing out under load
7. **Worker backlog**: Background tasks falling behind

## Pass Criteria

| Metric | Acceptable | Warning | Failure |
|--------|-----------|---------|---------|
| p95 PUT latency | <500ms | 500-1000ms | >1000ms |
| p95 GET latency | <200ms | 200-500ms | >500ms |
| Error rate | 0% | <1% | >1% |
| Message order violations | 0 | 0 | >0 |
| Missing recent messages | 0 | 0 | >0 |
| Summary present (long sessions) | Yes | - | No |

## Usage

### Quick Start

```bash
# Start the full simulation stack
docker-compose -f docker-compose-simulation.yml up

# Run specific scenario
docker-compose -f docker-compose-simulation.yml run --rm orchestrator \
  --scenario medium-heavy \
  --output-dir /results

# Scale to specific number of clients
docker-compose -f docker-compose-simulation.yml up --scale sim-client=25
```

### Custom Configuration

```bash
# Run with custom parameters
docker-compose -f docker-compose-simulation.yml run --rm orchestrator \
  --concurrent-sessions 30 \
  --session-length 150 \
  --context-window-max 4000 \
  --output-dir /results
```

### View Results

Results are written to `./simulation_results/` including:
- `summary.json`: Aggregate metrics and pass/fail status
- `heatmap_data.json`: Data for generating heat maps
- `per_session_snapshots/`: Detailed per-turn data for each session
- `errors.log`: Any errors encountered

## Files

| File | Purpose |
|------|---------|
| `docker-compose-simulation.yml` | Docker Compose for simulation stack |
| `simulation/Dockerfile` | Dockerfile for simulation clients |
| `simulation/orchestrator.py` | Main orchestration script |
| `simulation/load_runner.py` | Concurrent session runner |
| `simulation/datasets/` | Conversation fixtures |
| `simulation/analysis.py` | Results analysis and heat map generation |

## Implementation Notes

### Session Isolation
Each concurrent client uses a unique session ID to avoid conflicts:
```
session_id = f"sim-{scenario}-{client_id}-{timestamp}"
```

### Graceful Degradation Testing
The harness includes options to:
- Gradually increase load until failure
- Hold at specific load levels
- Ramp down after peak

### Resource Monitoring
The orchestrator can optionally collect:
- Redis memory usage
- API server CPU/memory
- Task worker queue depth