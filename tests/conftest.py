"""Pytest fixtures for interoperability tests."""

from __future__ import annotations

import json
import subprocess
import pytest
import shutil
from pathlib import Path


def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--clear",
        action="store_true",
        default=False,
        help="Remove all cached binaries and force rebuild all artifacts"
    )


def pytest_configure(config):
    """Configure pytest based on command-line options."""
    if config.getoption("--clear"):
        # When --clear is set, increase timeout to allow for cargo builds
        # Default test timeout is 30s, but cargo builds can take 2-3 minutes
        # Override the timeout setting to 10 minutes (600 seconds)
        config.option.timeout = 600


def pytest_collection_modifyitems(config, items):
    """Modify test items based on command-line options."""
    if config.getoption("--clear"):
        # Override timeout markers when --clear is set to allow builds
        # The @pytest.mark.timeout decorator overrides global config,
        # so we need to remove it and add our own with longer timeout
        for item in items:
            # Remove existing timeout markers
            item.own_markers = [m for m in item.own_markers if m.name != "timeout"]
            # Add new timeout marker with 600s (10 minutes)
            item.add_marker(pytest.mark.timeout(600))


def _clear_binary(binary: Path):
    """Remove a binary file if it exists."""
    if binary.exists():
        print(f"  Removing cached binary: {binary}")
        binary.unlink()


def _needs_build(binary: Path, source_dir: Path, extra_deps: list[Path] | None = None, force: bool = False) -> bool:
    """Check if a binary needs (re)building based on source modification times.

    Args:
        binary: Path to the binary to check
        source_dir: Primary source directory
        extra_deps: Optional list of additional directories to check (e.g., library dependencies)
        force: If True, always return True (force rebuild)
    """
    if force:
        return True

    if not binary.exists():
        return True
    bin_mtime = binary.stat().st_mtime

    # HARD CHECK: source_dir must exist
    if not source_dir.exists():
        raise RuntimeError(
            f"Source directory does not exist: {source_dir}\n"
            f"Cannot check if binary {binary} needs rebuilding"
        )

    # Check primary source directory
    for src in source_dir.rglob("*"):
        if src.is_file() and src.stat().st_mtime > bin_mtime:
            return True

    # Check extra dependencies (e.g., capns library for Rust targets)
    if extra_deps:
        for dep_dir in extra_deps:
            # HARD CHECK: extra dep directories must exist
            if not dep_dir.exists():
                raise RuntimeError(
                    f"Extra dependency directory does not exist: {dep_dir}\n"
                    f"Cannot check if binary {binary} needs rebuilding"
                )
            for src in dep_dir.rglob("*"):
                if src.is_file() and src.stat().st_mtime > bin_mtime:
                    return True

    return False


def _run_make(project_root: Path, target: str):
    """Run a Makefile target, fail hard on error."""
    result = subprocess.run(
        ["make", target],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=300,  # 5 minute timeout - fail hard if cargo is stuck
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"make {target} failed (exit {result.returncode}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def plugin_binaries(project_root, request):
    """Return paths to built plugin binaries, auto-building if needed."""
    clear_cache = request.config.getoption("--clear")
    artifacts = project_root / "artifacts" / "build"
    src = project_root / "src" / "capns_interop" / "plugins"
    capns_src = project_root.parent / "capns" / "src"  # capns library dependency

    # HARD CHECK: capns library dependency path must exist for Rust builds
    if not capns_src.exists():
        raise RuntimeError(
            f"capns library dependency not found at: {capns_src}\n"
            f"Expected structure: filegrind/capns/src and filegrind/capns-interop-tests/"
        )

    binaries = {
        "rust": artifacts / "rust" / "capns-interop-plugin-rust",
        "python": artifacts / "python" / "plugin.py",
        "swift": artifacts / "swift" / "capns-interop-plugin-swift",
        "go": artifacts / "go" / "capns-interop-plugin-go",
    }

    targets = {
        "rust": ("build-rust", src / "rust", [capns_src]),
        "python": ("build-python", src / "python", None),
        "swift": ("build-swift", src / "swift", None),
        "go": ("build-go", src / "go", None),
    }

    # Clear cached binaries if --clear option is set
    if clear_cache:
        print("\n--clear: Removing cached plugin binaries...")
        for lang, binary_path in binaries.items():
            _clear_binary(binary_path)

    for lang, (target, source_dir, extra_deps) in targets.items():
        binary_path = binaries[lang]
        old_mtime = binary_path.stat().st_mtime if binary_path.exists() else 0

        if _needs_build(binary_path, source_dir, extra_deps, force=clear_cache):
            print(f"\nAuto-building {lang} plugin...")
            _run_make(project_root, target)

            # HARD CHECK: Binary must exist after build
            if not binary_path.exists():
                raise RuntimeError(
                    f"Build succeeded but binary not found at: {binary_path}\n"
                    f"make {target} completed but failed to create/copy the binary"
                )

            # HARD CHECK: Binary timestamp must have been updated
            new_mtime = binary_path.stat().st_mtime
            if new_mtime <= old_mtime:
                raise RuntimeError(
                    f"Build succeeded but binary was not updated: {binary_path}\n"
                    f"Old mtime: {old_mtime}, New mtime: {new_mtime}\n"
                    f"This suggests the build didn't actually recompile or the copy failed"
                )

    return binaries


@pytest.fixture(scope="session")
def host_binaries(project_root, request):
    """Return paths to built test host binaries, auto-building if needed."""
    clear_cache = request.config.getoption("--clear")
    artifacts = project_root / "artifacts" / "build"
    hosts_src = project_root / "src" / "capns_interop" / "hosts"
    capns_src = project_root.parent / "capns" / "src"  # capns library dependency

    # HARD CHECK: capns library dependency path must exist for Rust builds
    if not capns_src.exists():
        raise RuntimeError(
            f"capns library dependency not found at: {capns_src}\n"
            f"Expected structure: filegrind/capns/src and filegrind/capns-interop-tests/"
        )

    binaries = {
        "rust": artifacts / "rust-host" / "capns-interop-host-rust",
        "python": hosts_src / "python" / "host.py",
        "swift": artifacts / "swift-host" / "capns-interop-host-swift",
        "go": artifacts / "go-host" / "capns-interop-host-go",
    }

    targets = {
        "rust": ("build-rust-host", hosts_src / "rust", [capns_src]),
        "swift": ("build-swift-host", hosts_src / "swift", None),
        "go": ("build-go-host", hosts_src / "go", None),
    }

    # Clear cached binaries if --clear option is set
    if clear_cache:
        print("\n--clear: Removing cached host binaries...")
        for lang, binary_path in binaries.items():
            if lang in targets:  # Only clear binaries that have build targets
                _clear_binary(binary_path)

    for lang, (target, source_dir, extra_deps) in targets.items():
        binary_path = binaries[lang]
        old_mtime = binary_path.stat().st_mtime if binary_path.exists() else 0

        if _needs_build(binary_path, source_dir, extra_deps, force=clear_cache):
            print(f"\nAuto-building {lang} host...")
            _run_make(project_root, target)

            # HARD CHECK: Binary must exist after build
            if not binary_path.exists():
                raise RuntimeError(
                    f"Build succeeded but binary not found at: {binary_path}\n"
                    f"make {target} completed but failed to create/copy the binary"
                )

            # HARD CHECK: Binary timestamp must have been updated
            new_mtime = binary_path.stat().st_mtime
            if new_mtime <= old_mtime:
                raise RuntimeError(
                    f"Build succeeded but binary was not updated: {binary_path}\n"
                    f"Old mtime: {old_mtime}, New mtime: {new_mtime}\n"
                    f"This suggests the build didn't actually recompile or the copy failed"
                )

    return binaries


def _print_throughput_matrix(results: dict):
    """Print throughput matrix table to stdout."""
    langs = ["rust", "go", "python", "swift"]
    print()
    print("━━━ THROUGHPUT MATRIX (MB/s)")
    print()
    header = "host ↓ \\ plugin →"
    print(f"  {header:>20}", end="")
    for p in langs:
        print(f"  {p:>8}", end="")
    print()
    print(f"  {'─' * 20}", end="")
    for _ in langs:
        print(f"  {'─' * 8}", end="")
    print()
    rows = []
    for h in langs:
        print(f"  {h:>20}", end="")
        for p in langs:
            cell = results.get(h, {}).get(p)
            if cell is None:
                print(f"  {'--':>8}", end="")
            elif cell.get("status") == "pass" and cell.get("mb_per_sec") is not None:
                print(f"  {cell['mb_per_sec']:>8.2f}", end="")
                rows.append((f"{h}-{p}", cell["mb_per_sec"]))
            else:
                print(f"  {'X':>8}", end="")
                rows.append((f"{h}-{p}", None))
        print()
    print()
    # Sorted ranking: passing combos descending by throughput, then failures
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    for label, val in rows:
        if val is not None:
            print(f"  {label:<20} {val:>8.2f} MB/s")
        else:
            print(f"  {label:<20} {'X':>8}")
    print()


@pytest.fixture(scope="session")
def throughput_collector(project_root):
    """Collect throughput matrix results, write JSON, and print table at session end."""
    results = {}
    yield results
    if not results:
        return
    output_path = project_root / "artifacts" / "throughput_matrix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    _print_throughput_matrix(results)


@pytest.fixture(scope="session")
def relay_host_binaries(project_root, request):
    """Return paths to built relay host binaries, auto-building if needed."""
    clear_cache = request.config.getoption("--clear")
    artifacts = project_root / "artifacts" / "build"
    hosts_src = project_root / "src" / "capns_interop" / "hosts"
    capns_src = project_root.parent / "capns" / "src"  # capns library dependency

    # HARD CHECK: capns library dependency path must exist for Rust builds
    if not capns_src.exists():
        raise RuntimeError(
            f"capns library dependency not found at: {capns_src}\n"
            f"Expected structure: filegrind/capns/src and filegrind/capns-interop-tests/"
        )

    binaries = {
        "rust": artifacts / "rust-relay" / "capns-interop-relay-host-rust",
        "python": hosts_src / "python" / "relay_host.py",
        "swift": artifacts / "swift-relay" / "capns-interop-relay-host-swift",
        "go": artifacts / "go-relay" / "capns-interop-relay-host-go",
    }

    targets = {
        "rust": ("build-rust-relay-host", hosts_src / "rust-relay", [capns_src]),
        "swift": ("build-swift-relay-host", hosts_src / "swift-relay", None),
        "go": ("build-go-relay-host", hosts_src / "go-relay", None),
    }

    # Clear cached binaries if --clear option is set
    if clear_cache:
        print("\n--clear: Removing cached relay host binaries...")
        for lang, binary_path in binaries.items():
            if lang in targets:  # Only clear binaries that have build targets
                _clear_binary(binary_path)

    for lang, (target, source_dir, extra_deps) in targets.items():
        binary_path = binaries[lang]
        old_mtime = binary_path.stat().st_mtime if binary_path.exists() else 0

        if _needs_build(binary_path, source_dir, extra_deps, force=clear_cache):
            print(f"\nAuto-building {lang} relay host...")
            _run_make(project_root, target)

            # HARD CHECK: Binary must exist after build
            if not binary_path.exists():
                raise RuntimeError(
                    f"Build succeeded but binary not found at: {binary_path}\n"
                    f"make {target} completed but failed to create/copy the binary"
                )

            # HARD CHECK: Binary timestamp must have been updated
            new_mtime = binary_path.stat().st_mtime
            if new_mtime <= old_mtime:
                raise RuntimeError(
                    f"Build succeeded but binary was not updated: {binary_path}\n"
                    f"Old mtime: {old_mtime}, New mtime: {new_mtime}\n"
                    f"This suggests the build didn't actually recompile or the copy failed"
                )

    return binaries


@pytest.fixture(scope="session")
def router_binaries(project_root, request):
    """Return paths to built router binaries, auto-building if needed."""
    clear_cache = request.config.getoption("--clear")
    artifacts = project_root / "artifacts" / "build"
    routers_src = project_root / "src" / "capns_interop" / "routers"
    capns_src = project_root.parent / "capns" / "src"  # capns library dependency

    # HARD CHECK: capns library dependency path must exist for Rust builds
    if not capns_src.exists():
        raise RuntimeError(
            f"capns library dependency not found at: {capns_src}\n"
            f"Expected structure: filegrind/capns/src and filegrind/capns-interop-tests/"
        )

    binaries = {
        "rust": artifacts / "rust-router" / "capns-interop-router-rust",
        # TODO: Add other languages when implemented
        # "python": routers_src / "python" / "router.py",
        # "swift": artifacts / "swift-router" / "capns-interop-router-swift",
        # "go": artifacts / "go-router" / "capns-interop-router-go",
    }

    targets = {
        "rust": ("build-rust-router", routers_src / "rust", [capns_src]),
    }

    # Clear cached binaries if --clear option is set
    if clear_cache:
        print("\n--clear: Removing cached router binaries...")
        for lang, binary_path in binaries.items():
            if lang in targets:  # Only clear binaries that have build targets
                _clear_binary(binary_path)

    for lang, (target, source_dir, extra_deps) in targets.items():
        binary_path = binaries[lang]
        old_mtime = binary_path.stat().st_mtime if binary_path.exists() else 0

        if _needs_build(binary_path, source_dir, extra_deps, force=clear_cache):
            print(f"\nAuto-building {lang} router...")
            _run_make(project_root, target)

            # HARD CHECK: Binary must exist after build
            if not binary_path.exists():
                raise RuntimeError(
                    f"Build succeeded but binary not found at: {binary_path}\n"
                    f"make {target} completed but failed to create/copy the binary"
                )

            # HARD CHECK: Binary timestamp must have been updated
            new_mtime = binary_path.stat().st_mtime
            if new_mtime <= old_mtime:
                raise RuntimeError(
                    f"Build succeeded but binary was not updated: {binary_path}\n"
                    f"Old mtime: {old_mtime}, New mtime: {new_mtime}\n"
                    f"This suggests the build didn't actually recompile or the copy failed"
                )

    return binaries


@pytest.fixture
def rust_plugin(plugin_binaries):
    """Return path to Rust plugin."""
    return plugin_binaries["rust"]


@pytest.fixture
def python_plugin(plugin_binaries):
    """Return path to Python plugin."""
    return plugin_binaries["python"]


@pytest.fixture
def swift_plugin(plugin_binaries):
    """Return path to Swift plugin."""
    return plugin_binaries["swift"]


@pytest.fixture
def go_plugin(plugin_binaries):
    """Return path to Go plugin."""
    return plugin_binaries["go"]
