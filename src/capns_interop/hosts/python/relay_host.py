#!/usr/bin/env python3
"""Multi-plugin relay host test binary for cross-language interop tests.

Creates a PluginHost managing N plugin subprocesses, with optional RelaySlave layer.
Communicates with the test orchestrator via raw CBOR frames on stdin/stdout.

Without --relay:
    stdin/stdout carry raw CBOR frames (PluginHost relay interface).
    Test writes REQ(empty) + STREAM_START/CHUNK/STREAM_END + END
    → PluginHost routes by cap_urn → plugin responds → frames on stdout.

With --relay:
    stdin/stdout carry CBOR frames including relay-specific types.
    RelaySlave sits between stdin/stdout and PluginHost.
    Initial RelayNotify is sent on startup with aggregate manifest + limits.
    RelayState frames are intercepted by slave (never reach PluginHost).
    All other frames pass through transparently.

Usage:
    relay_host.py --spawn /path/to/plugin1 [--spawn /path/to/plugin2 ...]
    relay_host.py --relay --spawn /path/to/plugin1
"""

import argparse
import os
import subprocess
import sys
import threading

# Add capns-py and tagged-urn-py to path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_capns_py_src = os.path.abspath(os.path.join(_script_dir, "..", "..", "..", "..", "capns-py", "src"))
_tagged_urn_py_src = os.path.abspath(os.path.join(_script_dir, "..", "..", "..", "..", "tagged-urn-py", "src"))
sys.path.insert(0, _capns_py_src)
sys.path.insert(0, _tagged_urn_py_src)

from capns.async_plugin_host import PluginHost
from capns.plugin_relay import RelaySlave
from capns.cbor_io import FrameReader, FrameWriter
from capns.cbor_frame import Limits


def spawn_plugin(plugin_path: str):
    """Spawn a plugin subprocess, return (stdout, stdin, process)."""
    if plugin_path.endswith(".py"):
        python_exe = os.environ.get("PYTHON_EXECUTABLE", sys.executable)
        args = [python_exe, plugin_path]
    else:
        args = [plugin_path]

    env = os.environ.copy()
    python_paths = [_capns_py_src, _tagged_urn_py_src]
    if "PYTHONPATH" in env:
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = ":".join(python_paths)

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return proc.stdout, proc.stdin, proc


def drain_stderr(proc):
    """Drain plugin stderr to our stderr in a background thread."""
    def _drain():
        try:
            while True:
                chunk = proc.stderr.read(8192)
                if not chunk:
                    break
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
        except Exception:
            pass
    t = threading.Thread(target=_drain, daemon=True)
    t.start()


def run_direct(host: PluginHost):
    """Run PluginHost directly with stdin/stdout as relay interface."""
    host.run(sys.stdin.buffer, sys.stdout.buffer, resource_fn=lambda: b"")


def run_with_relay(host: PluginHost):
    """Run PluginHost wrapped in RelaySlave, stdin/stdout as master socket.

    Architecture:
        stdin/stdout (master socket) → RelaySlave → internal pipes → PluginHost → plugins

    The RelaySlave intercepts RelayNotify/RelayState. All other frames pass through.
    """
    # Create two pipe pairs for bidirectional communication between slave and host.
    # Each os.pipe() returns (read_fd, write_fd).
    #
    # Pipe A: slave writes → host reads (slave local_writer → host relay_read)
    a_read_fd, a_write_fd = os.pipe()
    # Pipe B: host writes → slave reads (host relay_write → slave local_reader)
    b_read_fd, b_write_fd = os.pipe()

    # Wrap fds into file objects. Each fd is owned by exactly one file object.
    host_relay_read = os.fdopen(a_read_fd, "rb", buffering=0)
    slave_to_host_write = os.fdopen(a_write_fd, "wb", buffering=0)
    host_to_slave_read = os.fdopen(b_read_fd, "rb", buffering=0)
    host_relay_write = os.fdopen(b_write_fd, "wb", buffering=0)

    slave_local_reader = FrameReader(host_to_slave_read)
    slave_local_writer = FrameWriter(slave_to_host_write)

    caps_data = host.capabilities or b"[]"
    limits = Limits()

    host_error = [None]

    def run_host():
        try:
            host.run(host_relay_read, host_relay_write, resource_fn=lambda: b"")
        except Exception as e:
            host_error[0] = e
        finally:
            # Close the host's pipe ends when it exits
            try:
                host_relay_read.close()
            except Exception:
                pass
            try:
                host_relay_write.close()
            except Exception:
                pass

    host_thread = threading.Thread(target=run_host, daemon=True)
    host_thread.start()

    slave = RelaySlave(slave_local_reader, slave_local_writer)
    try:
        slave.run(
            socket_reader=FrameReader(sys.stdin.buffer),
            socket_writer=FrameWriter(sys.stdout.buffer),
            initial_notify=(caps_data, limits),
        )
    except Exception as e:
        print(f"RelaySlave error: {e}", file=sys.stderr)
    finally:
        # Close the slave's pipe ends to unblock PluginHost
        try:
            slave_to_host_write.close()
        except Exception:
            pass
        try:
            host_to_slave_read.close()
        except Exception:
            pass

    host_thread.join(timeout=5.0)
    if host_error[0] is not None:
        print(f"PluginHost error: {host_error[0]}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Multi-plugin relay host")
    parser.add_argument("--spawn", action="append", dest="plugins", default=[],
                        help="Path to plugin binary (repeatable)")
    parser.add_argument("--relay", action="store_true",
                        help="Enable RelaySlave layer")
    args = parser.parse_args()

    if not args.plugins:
        print("ERROR: at least one --spawn required", file=sys.stderr)
        sys.exit(1)

    host = PluginHost()
    processes = []

    for plugin_path in args.plugins:
        stdout, stdin, proc = spawn_plugin(plugin_path)
        processes.append(proc)
        drain_stderr(proc)
        host.attach_plugin(stdout, stdin)

    try:
        if args.relay:
            run_with_relay(host)
        else:
            run_direct(host)
    finally:
        for proc in processes:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass


if __name__ == "__main__":
    main()
