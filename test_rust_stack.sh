#!/bin/bash
# Test script for full Rust stack: Router → Host → Plugin
# Uses new multi-host architecture with Unix sockets

set -e

cd "$(dirname "$0")"

SOCKET_PATH="/tmp/capns_test_rust_stack_$$.sock"

echo "Testing Rust 3-tier stack (multi-host architecture)..."
echo "  Router: artifacts/build/rust-router/capns-interop-router-rust"
echo "  Host:   artifacts/build/rust-relay/capns-interop-relay-host-rust"
echo "  Plugin: artifacts/build/rust/capns-interop-plugin-rust"
echo "  Socket: $SOCKET_PATH"
echo ""

# Clean up socket on exit
trap "rm -f $SOCKET_PATH" EXIT

# Start relay host in background listening on socket
echo "Starting relay host..."
artifacts/build/rust-relay/capns-interop-relay-host-rust \
  --listen "$SOCKET_PATH" \
  --spawn artifacts/build/rust/capns-interop-plugin-rust \
  --relay &
HOST_PID=$!

# Wait for socket to be created
echo "Waiting for socket..."
for i in {1..50}; do
  if [ -S "$SOCKET_PATH" ]; then
    echo "Socket ready"
    break
  fi
  sleep 0.1
done

if [ ! -S "$SOCKET_PATH" ]; then
  echo "ERROR: Socket not created after 5 seconds"
  kill $HOST_PID 2>/dev/null || true
  exit 1
fi

# Start router connecting to host socket
echo "Starting router..."
gtimeout 30 artifacts/build/rust-router/capns-interop-router-rust \
  --connect "$SOCKET_PATH" \
  </dev/null

echo "Router exited"

# Clean up host process
kill $HOST_PID 2>/dev/null || true
wait $HOST_PID 2>/dev/null || true
