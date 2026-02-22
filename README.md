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

Performance tests generate a throughput matrix showing MB/s for each host-plugin combination:

```
THROUGHPUT MATRIX (MB/s)

     host ↓ \ plugin →      rust        go    python     swift
  ────────────────────  ────────  ────────  ────────  ────────
                  rust    106.96     97.99      6.43     20.44
                    go         X         X         X         X
                python        --        --        --        --
                 swift    101.35    105.44      6.46     20.65

RANKING (fastest to slowest)

  rust-rust              106.96 MB/s
  swift-go               105.44 MB/s
  swift-rust             101.35 MB/s
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

