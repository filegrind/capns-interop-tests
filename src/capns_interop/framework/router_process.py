"""Router process helper for 3-tier interoperability tests.

Router = RelaySwitch + RelayMaster in a subprocess.
Communicates with test orchestration via stdin/stdout.
Connects to independent relay host processes via Unix sockets.

Architecture:
  Test (Engine) → Router (subprocess) ←socket→ Host (subprocess) → Plugin (subprocess)

Router and Host are independent siblings (not parent-child).
Relay connection is non-fatal - if broken, router continues running.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from capns_interop.framework.frame_test_helper import FrameReader, FrameWriter


class RouterProcess:
    """Wrapper for router subprocess (RelaySwitch + RelayMaster).

    The router connects to independent relay host processes via Unix sockets.
    Test communicates with router via CBOR frames on stdin/stdout.

    Router and relay hosts run as independent processes (siblings, not parent-child).
    This decouples their lifecycles - relay connection loss is non-fatal.
    """

    def __init__(self, router_binary_path: str, host_binary_path: str, plugin_paths: List[str]):
        """Create a router process.

        Args:
            router_binary_path: Path to router binary (e.g., capns-interop-router-rust)
            host_binary_path: Path to relay host binary (e.g., capns-interop-relay-host-rust)
            plugin_paths: List of paths to plugin binaries
        """
        self.router_path = Path(router_binary_path)
        self.host_path = Path(host_binary_path)
        self.plugin_paths = [Path(p) for p in plugin_paths]
        self.router_proc: Optional[subprocess.Popen] = None
        self.host_proc: Optional[subprocess.Popen] = None
        self.socket_path: Optional[str] = None
        self.reader: Optional[FrameReader] = None
        self.writer: Optional[FrameWriter] = None

    def start(self):
        """Start the relay host and router subprocesses.

        Returns:
            (reader, writer) tuple for communicating with router via CBOR frames
        """
        # Create temp socket path
        temp_dir = tempfile.gettempdir()
        self.socket_path = os.path.join(temp_dir, f"capns_relay_test_{os.getpid()}.sock")

        # Remove existing socket if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Step 1: Start relay host listening on socket
        # Host command: <host-binary> --listen <socket> --spawn <plugin1> --spawn <plugin2> ... --relay
        plugin_args = []
        for plugin_path in self.plugin_paths:
            plugin_args.extend(["--spawn", str(plugin_path)])

        host_cmd = [
            str(self.host_path),
            "--listen", self.socket_path,
            *plugin_args,
            "--relay",
        ]

        print(f"[RouterProcess] Starting relay host: {' '.join(host_cmd)}", file=sys.stderr)

        self.host_proc = subprocess.Popen(
            host_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,  # Forward stderr for debugging
        )

        # Wait for socket to be created (host is ready)
        max_wait = 5.0
        start_time = time.time()
        while not os.path.exists(self.socket_path):
            if time.time() - start_time > max_wait:
                self.stop()
                raise RuntimeError(f"Relay host failed to create socket: {self.socket_path}")
            time.sleep(0.01)

        print(f"[RouterProcess] Relay host listening on {self.socket_path}", file=sys.stderr)

        # Step 2: Start router connecting to host socket
        # Router command: <router-binary> --connect <socket>
        router_cmd = [
            str(self.router_path),
            "--connect", self.socket_path,
        ]

        print(f"[RouterProcess] Starting router: {' '.join(router_cmd)}", file=sys.stderr)

        self.router_proc = subprocess.Popen(
            router_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # Forward stderr for debugging
        )

        # Create frame reader/writer for stdin/stdout
        self.reader = FrameReader(self.router_proc.stdout)
        self.writer = FrameWriter(self.router_proc.stdin)

        # Wait for router to be ready: read RelayNotify frames until we get one with capabilities
        # The router forwards RelayNotify frames from masters to the engine (test)
        # We need to wait for the final RelayNotify with the full capability set
        print(f"[RouterProcess] Waiting for router capabilities...", file=sys.stderr)

        caps_ready = False
        while not caps_ready:
            frame = self.reader.read()
            if frame is None:
                raise RuntimeError("Router closed before sending capabilities")

            if frame.frame_type == 10:  # RelayNotify
                # Check if this RelayNotify has capabilities in the manifest
                manifest_bytes = frame.relay_notify_manifest()
                if manifest_bytes and len(manifest_bytes) > 2:  # More than just "[]"
                    # Parse to verify it's a non-empty capability array
                    import json
                    try:
                        caps = json.loads(manifest_bytes)
                        if isinstance(caps, list) and len(caps) > 0:
                            print(f"[RouterProcess] Router ready with {len(caps)} capabilities", file=sys.stderr)
                            caps_ready = True
                        else:
                            print(f"[RouterProcess] Got empty RelayNotify, waiting for capabilities...", file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"[RouterProcess] Invalid RelayNotify manifest, ignoring", file=sys.stderr)
                else:
                    print(f"[RouterProcess] Got empty RelayNotify, waiting for capabilities...", file=sys.stderr)

        return self.reader, self.writer

    def stop(self, timeout: float = 5.0):
        """Stop the router and relay host processes."""
        # Stop router first (closes connection to host)
        if self.router_proc:
            try:
                # Close stdin to signal EOF
                if self.router_proc.stdin:
                    self.router_proc.stdin.close()

                # Wait for graceful shutdown
                self.router_proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"[RouterProcess] Timeout waiting for router, killing", file=sys.stderr)
                self.router_proc.kill()
                self.router_proc.wait()
            except Exception as e:
                print(f"[RouterProcess] Error stopping router: {e}", file=sys.stderr)
                if self.router_proc.poll() is None:
                    self.router_proc.kill()
                    self.router_proc.wait()

        # Stop relay host (should exit when router closes connection)
        if self.host_proc:
            try:
                self.host_proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"[RouterProcess] Timeout waiting for relay host, killing", file=sys.stderr)
                self.host_proc.kill()
                self.host_proc.wait()
            except Exception as e:
                print(f"[RouterProcess] Error stopping relay host: {e}", file=sys.stderr)
                if self.host_proc.poll() is None:
                    self.host_proc.kill()
                    self.host_proc.wait()

        # Clean up socket
        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
