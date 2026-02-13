#!/bin/bash
# Test script for full Rust stack: Router → Host → Plugin

set -e

cd "$(dirname "$0")"

echo "Testing Rust 3-tier stack..."
echo "  Router: artifacts/build/rust-router/capns-interop-router-rust"
echo "  Host:   artifacts/build/rust-relay/capns-interop-relay-host-rust"
echo "  Plugin: artifacts/build/rust/capns-interop-plugin-rust"
echo ""

# Start the router with the host (which will spawn the plugin)
echo "Starting router..."
artifacts/build/rust-router/capns-interop-router-rust \
  --spawn-host "artifacts/build/rust-relay/capns-interop-relay-host-rust --spawn artifacts/build/rust/capns-interop-plugin-rust --relay" \
  </dev/null

echo "Router exited"
