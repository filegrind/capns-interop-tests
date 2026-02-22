#!/usr/bin/env python3
"""Display throughput matrix from test results.

Reads artifacts/throughput_matrix.json and displays a formatted matrix
showing MB/s for each host-plugin combination.

Usage:
    python show_throughput_matrix.py
    python show_throughput_matrix.py artifacts/throughput_matrix.json
"""

import json
import sys
from pathlib import Path


def print_throughput_matrix(json_file):
    """Print formatted throughput matrix."""
    if not Path(json_file).exists():
        print(f"No throughput matrix found at: {json_file}")
        print("Run: pytest tests/test_performance.py::test_large_payload_throughput")
        return

    with open(json_file) as f:
        data = json.load(f)

    langs = ["rust", "go", "python", "swift"]

    # Header
    print()
    print("="*80)
    print("THROUGHPUT MATRIX (MB/s)")
    print("="*80)
    print()
    print(f"  {'host ↓ \\ plugin →':>20}", end="")
    for p in langs:
        print(f"  {p:>8}", end="")
    print()
    print(f"  {'─' * 20}", end="")
    for _ in langs:
        print(f"  {'─' * 8}", end="")
    print()

    # Rows
    rows = []
    for h in langs:
        print(f"  {h:>20}", end="")
        for p in langs:
            cell = data.get(h, {}).get(p)
            if cell is None:
                print(f"  {'--':>8}", end="")
            elif cell.get("status") == "pass" and cell.get("mb_per_sec") is not None:
                mb_s = cell["mb_per_sec"]
                print(f"  {mb_s:>8.2f}", end="")
                rows.append((f"{h}-{p}", mb_s))
            else:
                print(f"  {'X':>8}", end="")
                rows.append((f"{h}-{p}", None))
        print()

    # Sorted ranking
    print()
    print("="*80)
    print("RANKING (fastest to slowest)")
    print("="*80)
    print()
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    for label, val in rows:
        if val is not None:
            print(f"  {label:<20} {val:>8.2f} MB/s")
        else:
            print(f"  {label:<20} {'FAIL':>8}")
    print()


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "artifacts/throughput_matrix.json"
    print_throughput_matrix(json_file)
