"""Throughput matrix: measure MB/s for all host x plugin combinations.

Each host binary runs the benchmark internally — it calls generate_large
on the plugin via CBOR (chunked automatically), measures wall-clock time,
and reports only the metric over JSON-lines.  No payload crosses the
JSON-line boundary.

Configure via env vars:
  THROUGHPUT_MB       payload size in MB (default 5)
  THROUGHPUT_TIMEOUT  per-test timeout in seconds (default: 30 + THROUGHPUT_MB * 2)
"""

import os
import pytest
from capns_interop.framework.host_process import HostProcess
from capns_interop.framework.remote_host import RemoteHost

PAYLOAD_MB = int(os.environ.get("THROUGHPUT_MB", "5"))
TIMEOUT = int(os.environ.get("THROUGHPUT_TIMEOUT", str(30 + PAYLOAD_MB * 2)))

HOSTS = ["rust", "go", "python", "swift"]
PLUGINS = ["rust", "go", "python", "swift"]


@pytest.mark.asyncio
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("host_lang", HOSTS)
@pytest.mark.parametrize("plugin_lang", PLUGINS)
async def test_throughput_matrix(
    host_binaries, plugin_binaries, host_lang, plugin_lang, throughput_collector
):
    """Measure throughput for a specific host x plugin combination."""
    host_path = host_binaries[host_lang]
    plugin_path = plugin_binaries[plugin_lang]

    # Spawn host, have it spawn the plugin, then run throughput internally
    host_proc = HostProcess(host_path)
    try:
        await host_proc.start()
        remote = RemoteHost(host_proc)
        await remote.spawn_plugin(plugin_path)

        result = await remote.run_throughput(payload_mb=PAYLOAD_MB)

        mb_per_sec = result["mb_per_sec"]

        if host_lang not in throughput_collector:
            throughput_collector[host_lang] = {}
        throughput_collector[host_lang][plugin_lang] = {
            "mb_per_sec": mb_per_sec,
            "status": "pass",
        }

        await remote.shutdown()
        await host_proc.stop()

    except Exception as e:
        try:
            await host_proc.kill()
        except Exception:
            pass

        if host_lang not in throughput_collector:
            throughput_collector[host_lang] = {}
        throughput_collector[host_lang][plugin_lang] = {
            "mb_per_sec": None,
            "status": "error",
            "error": str(e),
        }

        print(f"\n  X [{host_lang}-host -> {plugin_lang}-plugin]: {e}")
