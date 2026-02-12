"""Performance benchmark tests.

Measures latency, throughput, and large payload transfer speed across
host x plugin combinations using raw CBOR frames.
"""

import json
import time
import statistics
import pytest

from capns.cbor_frame import FrameType
from capns_interop import TEST_CAPS
from capns_interop.framework.frame_test_helper import (
    HostProcess,
    make_req_id,
    send_request,
    read_response,
    decode_cbor_response,
)

SUPPORTED_HOST_LANGS = ["python", "go", "rust", "swift"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_latency_benchmark(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Benchmark request/response latency: 100 echo iterations, report p50/p95/p99."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        iterations = 100
        latencies = []

        for _ in range(iterations):
            test_input = b"benchmark"
            req_id = make_req_id()

            start = time.perf_counter()
            send_request(writer, req_id, TEST_CAPS["echo"], test_input)
            output, frames = read_response(reader)
            duration = (time.perf_counter() - start) * 1000

            assert output == test_input
            latencies.append(duration)

        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]
        p99 = statistics.quantiles(latencies, n=100)[98]
        avg = statistics.mean(latencies)

        print(
            f"\n  [{host_lang}/{plugin_lang}] Latency: "
            f"p50={p50:.2f}ms, p95={p95:.2f}ms, p99={p99:.2f}ms, avg={avg:.2f}ms"
        )

        # Language-appropriate latency thresholds
        # Python (host or plugin) is slower due to GIL and interpreter overhead
        # Margins account for measurement variance
        if host_lang == "python" and plugin_lang == "python":
            threshold = 1600  # Both Python: double GIL overhead, highest latency (~1000-1500ms p99)
        elif host_lang == "python" or plugin_lang == "python":
            threshold = 1100  # One Python: higher latency expected (~50-400ms avg, ~850-1000ms p99)
        else:
            threshold = 200   # All compiled: lower latency

        assert p99 < threshold, (
            f"[{host_lang}/{plugin_lang}] p99 latency too high: {p99:.2f}ms (threshold: {threshold}ms)"
        )
    finally:
        host.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_throughput_benchmark(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Benchmark throughput: echo requests/second over 2 seconds."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        duration_seconds = 2
        test_input = b"throughput"
        count = 0

        start = time.perf_counter()
        while (time.perf_counter() - start) < duration_seconds:
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["echo"], test_input)
            output, frames = read_response(reader)
            assert output == test_input
            count += 1

        elapsed = time.perf_counter() - start
        rps = count / elapsed

        print(
            f"\n  [{host_lang}/{plugin_lang}] Throughput: "
            f"{rps:.2f} req/s ({count} requests in {elapsed:.2f}s)"
        )

        # Language-appropriate throughput thresholds
        # Python (host or plugin) is slower due to GIL and interpreter overhead
        # Margins account for measurement variance
        if host_lang == "python" or plugin_lang == "python":
            threshold = 8    # Python involved: ~10-18 req/s is normal
        else:
            threshold = 250  # All compiled: ~300+ req/s typical

        assert rps > threshold, (
            f"[{host_lang}/{plugin_lang}] throughput too low: {rps:.2f} req/s (threshold: {threshold})"
        )
    finally:
        host.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_large_payload_throughput(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Benchmark large payload transfer: 10MB generated data, report MB/s."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        payload_size = 10 * 1024 * 1024  # 10 MB
        input_json = json.dumps({"value": payload_size}).encode()

        req_id = make_req_id()
        start = time.perf_counter()
        send_request(writer, req_id, TEST_CAPS["generate_large"], input_json, media_urn="media:report-size;json;textable;form=map")

        # Collect all chunk data
        # Each CHUNK payload MUST be a complete, independently decodable CBOR value
        import cbor2
        all_data = bytearray()
        for _ in range(50000):
            frame = reader.read()
            if frame is None:
                break
            if frame.frame_type == FrameType.CHUNK and frame.payload:
                # Decode each chunk independently - FAIL HARD if not valid CBOR
                decoded = cbor2.loads(frame.payload)  # No try/except
                if isinstance(decoded, bytes):
                    all_data.extend(decoded)
                elif isinstance(decoded, str):
                    all_data.extend(decoded.encode('utf-8'))
                else:
                    raise ValueError(f"Unexpected CBOR type in chunk: {type(decoded)}")
            if frame.frame_type in (FrameType.END, FrameType.ERR):
                break

        elapsed = time.perf_counter() - start
        assert len(all_data) == payload_size, (
            f"[{host_lang}/{plugin_lang}] expected {payload_size} bytes, got {len(all_data)}"
        )

        mb_per_sec = (payload_size / (1024 * 1024)) / elapsed
        print(
            f"\n  [{host_lang}/{plugin_lang}] Large payload: "
            f"{mb_per_sec:.2f} MB/s ({payload_size / (1024 * 1024):.0f} MB in {elapsed:.2f}s)"
        )

        # Verify reasonable throughput (at least 1 MB/s)
        assert mb_per_sec > 1, (
            f"[{host_lang}/{plugin_lang}] throughput too low: {mb_per_sec:.2f} MB/s"
        )
    finally:
        host.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_concurrent_stress(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test concurrent workload simulation: plugin processes 100 work units."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        work_units = 100
        input_json = json.dumps({"value": work_units}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["concurrent_stress"], input_json, media_urn="media:order-batch-size;json;textable;form=map")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        assert output_str.startswith("computed-"), (
            f"[{host_lang}/{plugin_lang}] unexpected output: {output_str!r}"
        )
    finally:
        host.stop()


def test_throughput_matrix(relay_host_binaries, plugin_binaries):
    """Run throughput benchmark for all host×plugin combinations and display as matrix.

    This test provides a comprehensive view of performance across all language combinations.
    """
    print("\n" + "=" * 80)
    print("THROUGHPUT PERFORMANCE MATRIX (requests/second)")
    print("=" * 80)

    results = {}
    for host_lang in SUPPORTED_HOST_LANGS:
        results[host_lang] = {}
        for plugin_lang in SUPPORTED_PLUGIN_LANGS:
            host = HostProcess(
                str(relay_host_binaries[host_lang]),
                [str(plugin_binaries[plugin_lang])],
            )
            reader, writer = host.start()

            try:
                duration_seconds = 2
                test_input = b"throughput"
                count = 0

                start = time.perf_counter()
                while (time.perf_counter() - start) < duration_seconds:
                    req_id = make_req_id()
                    send_request(writer, req_id, TEST_CAPS["echo"], test_input)
                    output, frames = read_response(reader)
                    assert output == test_input
                    count += 1

                elapsed = time.perf_counter() - start
                rps = count / elapsed
                results[host_lang][plugin_lang] = rps
            finally:
                host.stop()

    # Print matrix header
    header_label = "Host \\ Plugin"
    print(f"\n{header_label:<15}", end="")
    for plugin_lang in SUPPORTED_PLUGIN_LANGS:
        print(f"{plugin_lang:>12}", end="")
    print()
    print("-" * (15 + 12 * len(SUPPORTED_PLUGIN_LANGS)))

    # Print matrix rows
    for host_lang in SUPPORTED_HOST_LANGS:
        print(f"{host_lang:<15}", end="")
        for plugin_lang in SUPPORTED_PLUGIN_LANGS:
            rps = results[host_lang][plugin_lang]
            print(f"{rps:>12.1f}", end="")
        print()

    print()

    # Calculate and print statistics
    all_values = [rps for host_results in results.values() for rps in host_results.values()]
    print(f"Overall Statistics:")
    print(f"  Min:    {min(all_values):.1f} req/s")
    print(f"  Max:    {max(all_values):.1f} req/s")
    print(f"  Mean:   {statistics.mean(all_values):.1f} req/s")
    print(f"  Median: {statistics.median(all_values):.1f} req/s")
    print("=" * 80 + "\n")

    # Assert all combinations meet language-appropriate minimum thresholds
    # Python host is slower due to GIL and interpreter overhead
    thresholds = {
        "python": 10,   # Python host: ~12-18 req/s is normal
        "go": 300,      # Compiled languages: much faster
        "rust": 300,
        "swift": 300,
    }

    for host_lang in SUPPORTED_HOST_LANGS:
        threshold = thresholds.get(host_lang, 50)
        for plugin_lang in SUPPORTED_PLUGIN_LANGS:
            rps = results[host_lang][plugin_lang]
            assert rps > threshold, (
                f"[{host_lang}/{plugin_lang}] throughput too low: {rps:.2f} req/s (threshold: {threshold})"
            )
