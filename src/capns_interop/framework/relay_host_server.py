"""Relay host server helper for independent relay host processes.

Spawns a relay host that listens on a Unix socket for router connections.
This decouples the relay host lifecycle from the router lifecycle.

Architecture:
  Test → Router (connects via socket) → RelayHost (listens on socket) → Plugin
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


class RelayHostServer:
    """Wrapper for an independent relay host server process.

    The relay host listens on a Unix socket for router connections.
    This allows the router to connect/disconnect/reconnect without killing the host.
    """

    def __init__(self, host_binary_path: str, plugin_paths: list[str], socket_path: Optional[str] = None):
        """Create a relay host server.

        Args:
            host_binary_path: Path to relay host binary
            plugin_paths: List of paths to plugin binaries
            socket_path: Optional path for Unix socket. If None, creates temp socket.
        """
        self.host_path = Path(host_binary_path)
        self.plugin_paths = [Path(p) for p in plugin_paths]

        # Create temp socket path if not provided
        if socket_path is None:
            temp_dir = tempfile.gettempdir()
            self.socket_path = os.path.join(temp_dir, f"capns_relay_host_{os.getpid()}.sock")
        else:
            self.socket_path = socket_path

        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> str:
        """Start the relay host server listening on the socket.

        Returns:
            socket_path: Path to the Unix socket the host is listening on
        """
        # Remove existing socket if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Build command: <host-binary> --listen <socket-path> --spawn <plugin1> --spawn <plugin2> ...
        plugin_args = []
        for plugin_path in self.plugin_paths:
            plugin_args.extend(["--spawn", str(plugin_path)])

        cmd = [
            str(self.host_path),
            "--listen", self.socket_path,
            *plugin_args,
            "--relay",
        ]

        print(f"[RelayHostServer] Starting: {' '.join(cmd)}", file=sys.stderr)

        self.proc = subprocess.Popen(
            cmd,
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

        print(f"[RelayHostServer] Host listening on {self.socket_path}", file=sys.stderr)
        return self.socket_path

    def stop(self, timeout: float = 5.0):
        """Stop the relay host server."""
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"[RelayHostServer] Timeout waiting for host, killing", file=sys.stderr)
                self.proc.kill()
                self.proc.wait()
            except Exception as e:
                print(f"[RelayHostServer] Error stopping: {e}", file=sys.stderr)
                if self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.wait()

        # Clean up socket
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
