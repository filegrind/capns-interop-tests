.PHONY: all plugins hosts relay-hosts build-rust build-python build-swift build-go \
       build-rust-host build-python-host build-swift-host build-go-host \
       build-rust-relay-host build-python-relay-host build-swift-relay-host build-go-relay-host \
       clean test test-matrix test-quick test-throughput test-relay test-multi-host

# Build everything
all: plugins hosts relay-hosts

# Build all plugins
plugins: build-rust build-python build-swift build-go

# Build all hosts
hosts: build-rust-host build-python-host build-swift-host build-go-host

# Build all relay hosts
relay-hosts: build-rust-relay-host build-python-relay-host build-swift-relay-host build-go-relay-host

# --- Plugins ---

build-rust:
	@echo "Building Rust plugin..."
	cd src/capns_interop/plugins/rust && cargo build --release
	mkdir -p artifacts/build/rust
	cp src/capns_interop/plugins/rust/target/release/capns-interop-plugin-rust artifacts/build/rust/

build-python:
	@echo "Preparing Python plugin..."
	mkdir -p artifacts/build/python
	cp src/capns_interop/plugins/python/plugin.py artifacts/build/python/
	chmod +x artifacts/build/python/plugin.py

build-swift:
	@echo "Building Swift plugin..."
	cd src/capns_interop/plugins/swift && swift build -c release
	mkdir -p artifacts/build/swift
	cp src/capns_interop/plugins/swift/.build/release/capns-interop-plugin-swift artifacts/build/swift/

build-go:
	@echo "Building Go plugin..."
	cd src/capns_interop/plugins/go && go build -o capns-interop-plugin-go .
	mkdir -p artifacts/build/go
	cp src/capns_interop/plugins/go/capns-interop-plugin-go artifacts/build/go/

# --- Hosts ---

build-rust-host:
	@echo "Building Rust host..."
	cd src/capns_interop/hosts/rust && cargo build --release
	mkdir -p artifacts/build/rust-host
	cp src/capns_interop/hosts/rust/target/release/capns-interop-host-rust artifacts/build/rust-host/

build-python-host:
	@echo "Preparing Python host..."
	@# Python host runs from source — no build needed

build-swift-host:
	@echo "Building Swift host..."
	cd src/capns_interop/hosts/swift && swift build -c release
	mkdir -p artifacts/build/swift-host
	cp src/capns_interop/hosts/swift/.build/release/capns-interop-host-swift artifacts/build/swift-host/

build-go-host:
	@echo "Building Go host..."
	cd src/capns_interop/hosts/go && go build -o capns-interop-host-go .
	mkdir -p artifacts/build/go-host
	cp src/capns_interop/hosts/go/capns-interop-host-go artifacts/build/go-host/

# --- Relay Hosts ---

build-rust-relay-host:
	@echo "Building Rust relay host..."
	cd src/capns_interop/hosts/rust-relay && cargo build --release
	mkdir -p artifacts/build/rust-relay-host
	cp src/capns_interop/hosts/rust-relay/target/release/capns-interop-relay-host-rust artifacts/build/rust-relay-host/

build-python-relay-host:
	@echo "Preparing Python relay host..."
	@# Python relay host runs from source — no build needed

build-swift-relay-host:
	@echo "Building Swift relay host..."
	cd src/capns_interop/hosts/swift-relay && swift build -c release
	mkdir -p artifacts/build/swift-relay-host
	cp src/capns_interop/hosts/swift-relay/.build/release/capns-interop-relay-host-swift artifacts/build/swift-relay-host/

build-go-relay-host:
	@echo "Building Go relay host..."
	cd src/capns_interop/hosts/go-relay && go build -o capns-interop-relay-host-go .
	mkdir -p artifacts/build/go-relay-host
	cp src/capns_interop/hosts/go-relay/capns-interop-relay-host-go artifacts/build/go-relay-host/

# --- Clean ---

clean:
	rm -rf artifacts/
	cd src/capns_interop/plugins/rust && cargo clean || true
	cd src/capns_interop/plugins/swift && swift package clean || true
	cd src/capns_interop/hosts/rust && cargo clean || true
	cd src/capns_interop/hosts/swift && swift package clean || true
	rm -f src/capns_interop/plugins/go/capns-interop-plugin-go
	rm -f src/capns_interop/hosts/go/capns-interop-host-go

# --- Test targets ---

test: all
	PYTHONPATH=src pytest tests/ -v

test-matrix: all
	PYTHONPATH=src pytest tests/test_host_matrix.py -v

test-throughput: all
	PYTHONPATH=src pytest tests/test_throughput_matrix.py -v -s --timeout=120

test-relay: all
	PYTHONPATH=src pytest tests/test_relay_interop.py -v --timeout=60

test-multi-host: all
	PYTHONPATH=src pytest tests/test_multi_host_interop.py -v --timeout=60

test-quick:
	PYTHONPATH=src pytest tests/ -v
