.PHONY: all build-rust build-python build-swift clean test test-matrix test-quick

# Build all plugins
all: build-rust build-python build-swift

# Rust plugin
build-rust:
	@echo "Building Rust plugin..."
	cd src/capns_interop/plugins/rust && cargo build --release
	mkdir -p artifacts/build/rust
	cp src/capns_interop/plugins/rust/target/release/capns-interop-plugin-rust artifacts/build/rust/

# Python plugin (just copy)
build-python:
	@echo "Preparing Python plugin..."
	mkdir -p artifacts/build/python
	cp src/capns_interop/plugins/python/plugin.py artifacts/build/python/
	chmod +x artifacts/build/python/plugin.py

# Swift plugin
build-swift:
	@echo "Building Swift plugin..."
	cd src/capns_interop/plugins/swift && swift build -c release
	mkdir -p artifacts/build/swift
	cp src/capns_interop/plugins/swift/.build/release/capns-interop-plugin-swift artifacts/build/swift/

# Clean build artifacts
clean:
	rm -rf artifacts/
	cd src/capns_interop/plugins/rust && cargo clean || true
	cd src/capns_interop/plugins/swift && swift package clean || true

# Run tests (builds first)
test: all
	PYTHONPATH=src pytest tests/ -v

# Run full matrix
test-matrix: all
	PYTHONPATH=src pytest tests/test_matrix.py -v

# Quick test (skip build)
test-quick:
	PYTHONPATH=src pytest tests/ -v

# Build and run specific test
test-basic: build-rust
	PYTHONPATH=src pytest tests/test_basic_interop.py -v
