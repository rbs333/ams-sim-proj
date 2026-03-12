#!/usr/bin/env python3
"""Analyze heatmap results and generate report."""
import json
import sys
from pathlib import Path


def load_heatmap(filepath: Path) -> dict:
    return json.loads(filepath.read_text())


def print_matrix(results: list, field: str, title: str):
    """Print a matrix view of a field."""
    lengths = sorted(set(r['session_length'] for r in results))
    sessions = sorted(set(r['concurrent_sessions'] for r in results))
    
    print(f"\n{title}")
    header = 'Length\\Sess'.ljust(12) + ''.join(str(s).rjust(10) for s in sessions)
    print(header)
    print('-' * len(header))
    
    for length in lengths:
        row = str(length).ljust(12)
        for sess in sessions:
            r = next((x for x in results if x['session_length'] == length 
                     and x['concurrent_sessions'] == sess), None)
            if r:
                val = r.get(field, 0)
                if isinstance(val, float):
                    if val > 1000:
                        cell = f'{val/1000:.1f}s'
                    else:
                        cell = f'{val:.0f}'
                else:
                    cell = str(val)
                
                # Add status markers
                if r['status'] == 'FAIL':
                    cell = f'[{cell}]'
                elif r['status'] == 'WARNING':
                    cell = f'({cell})'
            else:
                cell = '-'
            row += cell.rjust(10)
        print(row)


def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('simulation_results/heatmap_data.json')
    
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)
    
    data = load_heatmap(filepath)
    results = data['results']
    
    print('=' * 80)
    print('HEATMAP ANALYSIS - Long Conversation Memory Stress Test')
    print('=' * 80)
    print(f"Timestamp: {data['timestamp']}")
    print(f"Grid: {len(data['grid']['session_lengths'])} lengths × {len(data['grid']['concurrent_sessions'])} concurrency levels")
    
    # Print matrices
    print_matrix(results, 'put_p95_ms', 'PUT p95 Latency (ms) - [FAIL] (WARNING) PASS')
    print_matrix(results, 'get_p95_ms', 'GET p95 Latency (ms)')
    print_matrix(results, 'error_rate_pct', 'Error Rate (%)')
    print_matrix(results, 'summary_issues', 'Summary Issues Count')
    
    # Status matrix
    print("\nStatus Matrix:")
    lengths = sorted(set(r['session_length'] for r in results))
    sessions = sorted(set(r['concurrent_sessions'] for r in results))
    header = 'Length\\Sess'.ljust(12) + ''.join(str(s).rjust(10) for s in sessions)
    print(header)
    print('-' * len(header))
    for length in lengths:
        row = str(length).ljust(12)
        for sess in sessions:
            r = next((x for x in results if x['session_length'] == length 
                     and x['concurrent_sessions'] == sess), None)
            status = r['status'] if r else '-'
            row += status.rjust(10)
        print(row)
    
    # Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    
    passed = [r for r in results if r['status'] == 'PASS']
    warned = [r for r in results if r['status'] == 'WARNING']
    failed = [r for r in results if r['status'] == 'FAIL']
    
    print(f"PASS: {len(passed)}/{len(results)} scenarios")
    print(f"WARNING: {len(warned)}/{len(results)} scenarios")
    print(f"FAIL: {len(failed)}/{len(results)} scenarios")
    
    # Find breaking points
    print("\n" + "=" * 80)
    print("BREAKING POINTS IDENTIFIED")
    print("=" * 80)
    
    # Latency breaking point (>500ms)
    high_latency = [r for r in results if r['put_p95_ms'] > 500 or r['get_p95_ms'] > 500]
    if high_latency:
        print("\n⚠️  High Latency (>500ms p95):")
        for r in sorted(high_latency, key=lambda x: x['put_p95_ms']):
            print(f"   {r['session_length']} msgs × {r['concurrent_sessions']} sessions: "
                  f"PUT={r['put_p95_ms']:.0f}ms, GET={r['get_p95_ms']:.0f}ms")
    
    # Error breaking point
    with_errors = [r for r in results if r['error_rate_pct'] > 0]
    if with_errors:
        print("\n❌ Scenarios with Errors:")
        for r in sorted(with_errors, key=lambda x: x['error_rate_pct'], reverse=True):
            print(f"   {r['session_length']} msgs × {r['concurrent_sessions']} sessions: "
                  f"{r['error_rate_pct']:.1f}% error rate")
    
    # Summary issues (expected - no API key configured)
    print("\n📝 Summary Generation:")
    print("   Note: Summary issues detected when sessions exceed 20 messages")
    print("   This is expected without LLM API keys configured for summarization")
    
    # Find the "safe zone"
    print("\n" + "=" * 80)
    print("RECOMMENDED OPERATIONAL LIMITS")
    print("=" * 80)
    
    # Find max safe config (PASS status, <200ms latency)
    safe = [r for r in results if r['status'] == 'PASS' and r['put_p95_ms'] < 200]
    if safe:
        max_safe = max(safe, key=lambda x: x['session_length'] * x['concurrent_sessions'])
        print(f"\n✅ Safe Zone (PASS, <200ms):")
        print(f"   Up to {max_safe['session_length']} messages × {max_safe['concurrent_sessions']} concurrent sessions")
        print(f"   Total throughput: {max_safe['session_length'] * max_safe['concurrent_sessions']} msgs/batch")
    
    # Find max warning config (<500ms latency)
    warning = [r for r in results if r['status'] in ('PASS', 'WARNING') and r['put_p95_ms'] < 500]
    if warning:
        max_warning = max(warning, key=lambda x: x['session_length'] * x['concurrent_sessions'])
        print(f"\n⚠️  Warning Zone (<500ms, may have summary issues):")
        print(f"   Up to {max_warning['session_length']} messages × {max_warning['concurrent_sessions']} concurrent sessions")
        print(f"   Total throughput: {max_warning['session_length'] * max_warning['concurrent_sessions']} msgs/batch")


if __name__ == '__main__':
    main()

