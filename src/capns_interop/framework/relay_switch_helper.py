"""RelaySwitch-based test helper for bidirectional tests.

When tests need to handle peer requests from plugins (plugin → plugin calls),
they must use a RelaySwitch instead of reading frames directly. The RelaySwitch
routes peer REQ frames to the correct plugin and only returns response frames
to the engine.

For bidirectional tests with a single plugin, we use:
  Test (Engine) → RelaySwitch → RelayMaster → (socket) → RelaySlave (relay host) → PluginHost → Plugin

The plugin's peer requests go: Plugin → PluginHost → RelaySlave → RelayMaster → RelaySwitch
The RelaySwitch routes them back to: RelaySwitch → RelayMaster → RelaySlave → PluginHost → Plugin
"""

import sys
from pathlib import Path
from typing import List

# Add capns-py to path
_project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root / "capns-py" / "src"))
sys.path.insert(0, str(_project_root / "tagged-urn-py" / "src"))

from capns.relay_switch import RelaySwitch, SocketPair
from capns_interop.framework.frame_test_helper import HostProcess


class RelaySwitchProcess:
    """Wrapper for HostProcess that uses RelaySwitch for bidirectional routing.

    This allows tests to handle peer requests (plugin → plugin calls) by routing
    them through the RelaySwitch instead of trying to handle them in the test code.
    """

    def __init__(self, host_binary_path: str, plugin_paths: List[str]):
        """Create a RelaySwitch-based test host.

        Args:
            host_binary_path: Path to the relay host binary
            plugin_paths: List of paths to plugin binaries
        """
        self.host = HostProcess(host_binary_path, plugin_paths, relay=True)
        self.switch = None
        self.reader = None
        self.writer = None

    def start(self):
        """Start the host and create RelaySwitch.

        Returns:
            (reader, writer) tuple - these go through the RelaySwitch
        """
        # Start the relay host (RelaySlave in the binary)
        # Don't use the returned reader/writer - we need raw handles for RelaySwitch
        self.host.start()

        # Create RelaySwitch with raw socket handles
        # RelaySwitch constructor performs handshake (reads initial RelayNotify)
        self.switch = RelaySwitch([SocketPair(
            read=self.host.proc.stdout,
            write=self.host.proc.stdin
        )])

        # Wait for plugin to connect and send RelayNotify with capabilities
        # With capability update architecture:
        #   1. RelaySlave sends initial empty RelayNotify
        #   2. PluginHostRuntime spawns plugin, plugin sends HELLO
        #   3. PluginHostRuntime rebuilds capabilities, sends updated RelayNotify
        #   4. RelaySlave forwards updated RelayNotify to RelaySwitch
        import json
        import sys
        import time
        max_wait = 2.0  # Reduced from 5s (should be fast now)
        start = time.time()
        while time.time() - start < max_wait:
            caps_json = json.loads(self.switch.capabilities().decode('utf-8'))
            caps_list = caps_json.get('capabilities', [])
            if caps_list:
                print(f"[RelaySwitch] Received {len(caps_list)} capabilities after {time.time() - start:.3f}s", file=sys.stderr)
                break
            time.sleep(0.01)  # Poll more frequently (10ms vs 50ms)
        else:
            caps_json = json.loads(self.switch.capabilities().decode('utf-8'))
            caps_list = caps_json.get('capabilities', [])
            raise RuntimeError(
                f"No capabilities received after {max_wait}s (got: {caps_list}). "
                f"Check that PluginHostRuntime sends RelayNotify updates and RelaySlave forwards them."
            )

        # Return a simple API that mimics FrameReader/Writer but uses RelaySwitch
        self.reader = RelaySwitchReader(self.switch)
        self.writer = RelaySwitchWriter(self.switch)

        return self.reader, self.writer

    def stop(self, timeout: float = 5.0):
        """Stop the host process."""
        if self.host:
            self.host.stop(timeout)


class RelaySwitchReader:
    """Reader that wraps RelaySwitch.read_from_masters()."""

    def __init__(self, switch: RelaySwitch):
        self.switch = switch

    def read(self):
        """Read next frame from switch (handles peer routing internally)."""
        return self.switch.read_from_masters()


class RelaySwitchWriter:
    """Writer that wraps RelaySwitch.send_to_master()."""

    def __init__(self, switch: RelaySwitch):
        self.switch = switch

    def write(self, frame):
        """Send frame through switch."""
        return self.switch.send_to_master(frame)
