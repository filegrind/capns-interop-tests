"""Pytest fixtures for interoperability tests."""

import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def plugin_binaries(project_root):
    """Return paths to built plugin binaries."""
    artifacts = project_root / "artifacts" / "build"

    binaries = {
        "rust": artifacts / "rust" / "capns-interop-plugin-rust",
        "python": artifacts / "python" / "plugin.py",
        "swift": artifacts / "swift" / "capns-interop-plugin-swift",
        "go": artifacts / "go" / "capns-interop-plugin-go",
    }

    # Verify at least rust exists for basic tests
    if not binaries["rust"].exists():
        pytest.skip("Rust plugin not built. Run 'make build-rust' first.")

    return binaries


@pytest.fixture(scope="session")
def host_binaries(project_root):
    """Return paths to built test host binaries."""
    artifacts = project_root / "artifacts" / "build"
    hosts_src = project_root / "src" / "capns_interop" / "hosts"

    return {
        "rust": artifacts / "rust-host" / "capns-interop-host-rust",
        "python": hosts_src / "python" / "host.py",
        "swift": artifacts / "swift-host" / "capns-interop-host-swift",
        "go": artifacts / "go-host" / "capns-interop-host-go",
    }


@pytest.fixture
def rust_plugin(plugin_binaries):
    """Return path to Rust plugin."""
    return plugin_binaries["rust"]


@pytest.fixture
def python_plugin(plugin_binaries):
    """Return path to Python plugin."""
    if not plugin_binaries["python"].exists():
        pytest.skip("Python plugin not built. Run 'make build-python' first.")
    return plugin_binaries["python"]


@pytest.fixture
def swift_plugin(plugin_binaries):
    """Return path to Swift plugin."""
    if not plugin_binaries["swift"].exists():
        pytest.skip("Swift plugin not built. Run 'make build-swift' first.")
    return plugin_binaries["swift"]


@pytest.fixture
def go_plugin(plugin_binaries):
    """Return path to Go plugin."""
    if not plugin_binaries["go"].exists():
        pytest.skip("Go plugin not built. Run 'make build-go' first.")
    return plugin_binaries["go"]
