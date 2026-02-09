"""File-path conversion interoperability tests.

Tests the automatic file-path → bytes conversion feature across plugin runtimes.

CLI Mode Invocation Pattern:
    ./plugin read_file_info /path/to/file.txt

The runtime automatically:
1. Reads the file at the given path
2. Converts it to bytes
3. Passes bytes to the handler
4. Handler returns JSON with size + checksum
"""

import pytest
import subprocess
import hashlib
import json
import os
import tempfile
from pathlib import Path


@pytest.fixture
def test_files(tmp_path):
    """Create temporary test files."""
    files = {}

    # Small text file
    small = tmp_path / "small.txt"
    small.write_text("Hello, world!")
    files["small"] = small

    # Empty file
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    files["empty"] = empty

    # Binary file with all byte values
    binary = tmp_path / "binary.dat"
    binary.write_bytes(bytes(range(256)))
    files["binary"] = binary

    # Large file (100KB)
    large = tmp_path / "large.dat"
    large.write_bytes(b"X" * (100 * 1024))
    files["large"] = large

    # Multiple files for glob testing
    for i in range(3):
        f = tmp_path / f"test{i}.txt"
        f.write_text(f"File {i}")
        files[f"test{i}"] = f

    return files


def invoke_plugin_cli(plugin_path: Path, command: str, *args) -> dict:
    """Invoke plugin in CLI mode and parse JSON response.

    Args:
        plugin_path: Path to plugin binary
        command: Command/capability name
        *args: Positional arguments

    Returns:
        Parsed JSON response
    """
    # For Python plugins, use current Python interpreter explicitly
    if plugin_path.name == "plugin.py":
        import sys
        cmd = [sys.executable, str(plugin_path), command] + list(args)

        # Add capns-py and tagged-urn-py to PYTHONPATH
        env = os.environ.copy()
        project_root = plugin_path.parent.parent.parent.parent
        capns_py = project_root / "capns-py" / "src"
        tagged_urn_py = project_root / "tagged-urn-py" / "src"

        python_paths = [str(capns_py), str(tagged_urn_py)]
        if "PYTHONPATH" in env:
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = ":".join(python_paths)
    else:
        # For compiled plugins (Rust, Go, Swift), run directly
        cmd = [str(plugin_path), command] + list(args)
        env = os.environ.copy()

    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=30,
        check=True,
        env=env
    )

    # Parse JSON output
    return json.loads(result.stdout.decode('utf-8'))


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of file."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "go", "swift"])
async def test_single_file_read(plugin_binaries, test_files, plugin_name):
    """Test plugin reads single file and returns correct size + checksum."""
    plugin_path = plugin_binaries[plugin_name]
    file_path = test_files["small"]
    expected_size = file_path.stat().st_size
    expected_checksum = calculate_checksum(file_path)

    # Invoke plugin in CLI mode
    result = invoke_plugin_cli(plugin_path, "read_file_info", str(file_path))

    assert result["size"] == expected_size, \
        f"[{plugin_name}] Expected size {expected_size}, got {result['size']}"
    assert result["checksum"] == expected_checksum, \
        f"[{plugin_name}] Checksum mismatch"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "go", "swift"])
async def test_empty_file_handling(plugin_binaries, test_files, plugin_name):
    """Test plugin handles empty files correctly."""
    plugin_path = plugin_binaries[plugin_name]
    file_path = test_files["empty"]
    expected_checksum = hashlib.sha256(b"").hexdigest()

    result = invoke_plugin_cli(plugin_path, "read_file_info", str(file_path))

    assert result["size"] == 0, \
        f"[{plugin_name}] Empty file should have size 0, got {result['size']}"
    assert result["checksum"] == expected_checksum, \
        f"[{plugin_name}] Empty file checksum mismatch"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "go", "swift"])
async def test_binary_file_preservation(plugin_binaries, test_files, plugin_name):
    """Test binary data is preserved correctly (all 256 byte values)."""
    plugin_path = plugin_binaries[plugin_name]
    file_path = test_files["binary"]
    expected_size = 256
    expected_checksum = calculate_checksum(file_path)

    result = invoke_plugin_cli(plugin_path, "read_file_info", str(file_path))

    assert result["size"] == expected_size, \
        f"[{plugin_name}] Binary file size mismatch"
    assert result["checksum"] == expected_checksum, \
        f"[{plugin_name}] Binary file checksum mismatch (data not preserved)"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "go", "swift"])
async def test_large_file_handling(plugin_binaries, test_files, plugin_name):
    """Test plugin handles large files (100KB) correctly."""
    plugin_path = plugin_binaries[plugin_name]
    file_path = test_files["large"]
    expected_size = 100 * 1024
    expected_checksum = calculate_checksum(file_path)

    result = invoke_plugin_cli(plugin_path, "read_file_info", str(file_path))

    assert result["size"] == expected_size, \
        f"[{plugin_name}] Large file size mismatch"
    assert result["checksum"] == expected_checksum, \
        f"[{plugin_name}] Large file checksum mismatch"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "go", "swift"])
async def test_missing_file_error(plugin_binaries, tmp_path, plugin_name):
    """Test plugin fails gracefully on missing file."""
    plugin_path = plugin_binaries[plugin_name]
    missing_file = tmp_path / "nonexistent.txt"

    # Should fail with non-zero exit code
    result = subprocess.run(
        [str(plugin_path), "read_file_info", str(missing_file)],
        capture_output=True,
        timeout=30
    )

    assert result.returncode != 0, \
        f"[{plugin_name}] Should fail on missing file"
    # stderr should contain error message
    assert len(result.stderr) > 0, \
        f"[{plugin_name}] Should output error message to stderr"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_cross_language_consistency(plugin_binaries, test_files):
    """Test all languages produce identical results for the same file."""
    file_path = test_files["binary"]
    results = {}

    for plugin_name in ["rust", "python", "go", "swift"]:
        plugin_path = plugin_binaries[plugin_name]
        result = invoke_plugin_cli(plugin_path, "read_file_info", str(file_path))
        results[plugin_name] = result

    # All implementations should produce identical output
    if len(results) < 2:
        pytest.skip("Need at least 2 plugins built for consistency test")

    reference_result = list(results.values())[0]
    for plugin_name, result in results.items():
        assert result == reference_result, \
            f"{plugin_name} result differs from reference: {result} vs {reference_result}"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_utf8_text_file(plugin_binaries, tmp_path):
    """Test plugin handles UTF-8 text files correctly."""
    # Create UTF-8 file with various characters
    utf8_file = tmp_path / "utf8.txt"
    utf8_content = "Hello 世界 🌍 Здравствуй"
    utf8_file.write_text(utf8_content, encoding='utf-8')

    expected_size = len(utf8_content.encode('utf-8'))
    expected_checksum = hashlib.sha256(utf8_content.encode('utf-8')).hexdigest()

    for plugin_name in ["rust", "python", "go", "swift"]:
        plugin_path = plugin_binaries[plugin_name]
        result = invoke_plugin_cli(plugin_path, "read_file_info", str(utf8_file))

        assert result["size"] == expected_size, \
            f"[{plugin_name}] UTF-8 file size mismatch (got {result['size']}, expected {expected_size})"
        assert result["checksum"] == expected_checksum, \
            f"[{plugin_name}] UTF-8 file checksum mismatch"
