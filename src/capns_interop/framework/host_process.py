"""Test host subprocess lifecycle management.

A HostProcess wraps a test host binary that speaks the JSON-line protocol
on its stdin/stdout. The host binary in turn spawns and manages a plugin
subprocess using the CBOR protocol.

Architecture:
    Python Orchestrator (pytest)
        | JSON-line commands over stdin/stdout
        v
    Test Host Binary (Rust / Go / Python / Swift)
        | CBOR protocol over stdin/stdout
        v
    Test Plugin Binary (Rust / Go / Python / Swift)
"""

import asyncio
import json
import base64
import sys
from pathlib import Path
from typing import Optional


class HostProcessError(Exception):
    """Error from host process communication."""
    pass


class HostProcess:
    """Manages lifecycle of a test host subprocess that speaks JSON-line protocol."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr_buffer = bytearray()

    async def start(self):
        """Spawn the test host binary."""
        if self.binary_path.suffix == ".py":
            cmd = [sys.executable, str(self.binary_path)]
        else:
            cmd = [str(self.binary_path)]

        # Pass current Python executable to child process so non-Python hosts
        # can spawn Python plugins using the correct interpreter (with cbor2 etc.)
        import os
        env = os.environ.copy()
        env["PYTHON_EXECUTABLE"] = sys.executable

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024,  # 64MB for large base64 JSON lines
            env=env,
        )

        if not self.process.stdin or not self.process.stdout:
            if self.process.stderr:
                stderr_data = await self.process.stderr.read()
                raise HostProcessError(
                    f"Failed to create stdin/stdout pipes. Stderr: {stderr_data.decode()}"
                )
            raise HostProcessError("Failed to create stdin/stdout pipes")

        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def send_command(self, cmd: dict) -> dict:
        """Send a JSON-line command and read the JSON-line response.

        Args:
            cmd: Command dict to send (will be JSON-serialized + newline)

        Returns:
            Response dict parsed from JSON

        Raises:
            HostProcessError: If communication fails or response is invalid
        """
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise HostProcessError("Host process not started")

        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

        response_line = await self.process.stdout.readline()
        if not response_line:
            stderr = await self.get_stderr()
            raise HostProcessError(
                f"Host process returned empty response (EOF). Stderr:\n{stderr}"
            )

        try:
            return json.loads(response_line.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise HostProcessError(
                f"Invalid JSON response from host: {response_line!r}: {e}"
            )

    async def _drain_stderr(self):
        """Continuously read stderr to prevent pipe buffer blocking."""
        if not self.process or not self.process.stderr:
            return
        try:
            while True:
                chunk = await self.process.stderr.read(8192)
                if not chunk:
                    break
                self._stderr_buffer.extend(chunk)
        except Exception:
            pass

    async def get_stderr(self) -> str:
        """Return accumulated stderr output."""
        return self._stderr_buffer.decode("utf-8", errors="replace")

    async def stop(self, timeout: float = 5.0):
        """Gracefully stop host process."""
        if not self.process:
            return

        if self.process.stdin:
            self.process.stdin.close()
            try:
                await self.process.stdin.wait_closed()
            except Exception:
                pass

        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()

        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

    async def kill(self):
        """Force kill immediately."""
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
        if self.process:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass

    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process is not None and self.process.returncode is None
