# Capns Interoperability Testing Framework

Comprehensive cross-language integration testing for the capns ecosystem.

## Overview

Tests all viable capns implementations (Rust, Python, Swift, Go) against each other in both host and plugin roles, ensuring bulletproof protocol compliance across:
- Simple request/response
- Streaming responses
- Stream multiplexing
- Heartbeat mechanisms
- Bidirectional invocations
- Error handling
- Performance benchmarks


## Quick Start

```bash
# Build all test plugins
make all

# Run full test suite
pytest tests/ -v

# Run full matrix (252+ tests)
pytest tests/test_matrix.py -v
```

## Architecture

- **Python orchestrator** uses `PluginHostRuntime` to test plugins in different languages
- **Test plugins** implement identical 13 capabilities across Rust/Python/Swift
- **9 language-pair configurations**: 3 languages × 3 languages
- **28 scenarios** covering all protocol features

## Requirements

- Python 3.10+
- Rust toolchain (cargo)
- Swift toolchain (swift build)
- capns-py package (../capns-py)

## Test Matrix

```
       rust-plugin  python-plugin  swift-plugin
rust-host     ✓           ✓              ✓
python-host   ✓           ✓              ✓
swift-host    ✓           ✓              ✓
```

## Project Structure

- `src/capns_interop/framework/` - Core orchestration
- `src/capns_interop/scenarios/` - Test scenarios
- `src/capns_interop/plugins/` - Test plugin sources (Rust/Python/Swift)
- `tests/` - pytest test suite
- `artifacts/` - Build outputs and reports

## Adding New Languages

When Go/JavaScript implement CBOR runtimes:
1. Add plugin implementation in `src/capns_interop/plugins/{go,javascript}/`
2. Add Makefile build target
3. Update `SUPPORTED_LANGUAGES` constant
4. Matrix automatically expands from 9 to 25 configurations

## Usage

```bash
# Run all interop tests
PYTHONPATH=src python -m pytest tests/ -v

# For a summary view (less verbose)
PYTHONPATH=src python -m pytest tests/ -v --tb=short

# To see timing
PYTHONPATH=src python -m pytest tests/ -v --durations=10

# Run performance benchmarks and generate throughput matrix
PYTHONPATH=src python -m pytest tests/test_performance.py::test_large_payload_throughput -v

# Display throughput matrix
python3 show_throughput_matrix.py
```

## Throughput Matrix

Performance tests generate a 3D throughput matrix showing MB/s for each router-host-plugin combination.

One matrix is displayed per router, showing host × plugin performance:

```
================================================================================
THROUGHPUT MATRIX (MB/s) - Router: RUST
================================================================================

     host ↓ \ plugin →      rust        go    python     swift
  ────────────────────  ────────  ────────  ────────  ────────
                  rust    108.12    101.16      2.68     20.36
                    go     95.52     85.26      4.56     20.60
                 swift    107.81     95.99      4.43     19.97

================================================================================
THROUGHPUT MATRIX (MB/s) - Router: SWIFT
================================================================================

     host ↓ \ plugin →      rust        go    python     swift
  ────────────────────  ────────  ────────  ────────  ────────
                  rust     17.22     16.62      5.00     10.30
                    go     16.89     16.66      2.36     10.11
                 swift     16.63     16.32      2.77     10.06

================================================================================
RANKING (fastest to slowest)
================================================================================

  rust-rust-rust                   108.12 MB/s
  rust-swift-rust                  107.81 MB/s
  rust-rust-go                     101.16 MB/s
  ...
```

The matrix is automatically generated when running performance tests and displayed at the end of test runs via `test.sh`.

## Building

Note: Tests require all plugins to be built first.

```bash
make all  # Builds all plugins (Rust, Go, Python, Swift)

# Or build individually:
make build-rust
make build-go
make build-python
make build-swift
```

