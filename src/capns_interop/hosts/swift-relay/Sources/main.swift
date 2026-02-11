/// Multi-plugin relay host test binary for cross-language interop tests.
///
/// Creates a CborPluginHost managing N plugin subprocesses, with optional CborRelaySlave layer.
/// Communicates via raw CBOR frames on stdin/stdout.
///
/// Without --relay:
///     stdin/stdout carry raw CBOR frames (CborPluginHost relay interface).
///
/// With --relay:
///     stdin/stdout carry CBOR frames including relay-specific types.
///     CborRelaySlave sits between stdin/stdout and CborPluginHost.
///     Initial RelayNotify sent on startup.

import Foundation
import CapNsCbor

// MARK: - Argument Parsing

struct Args {
    var plugins: [String] = []
    var relay: Bool = false

    static func parse() -> Args {
        var args = Args()
        var argv = CommandLine.arguments.dropFirst()
        while let arg = argv.popFirst() {
            switch arg {
            case "--spawn":
                guard let path = argv.popFirst() else {
                    fputs("ERROR: --spawn requires a path argument\n", stderr)
                    exit(1)
                }
                args.plugins.append(path)
            case "--relay":
                args.relay = true
            default:
                fputs("ERROR: unknown argument: \(arg)\n", stderr)
                exit(1)
            }
        }
        return args
    }
}

// MARK: - Plugin Spawning

func spawnPlugin(_ pluginPath: String) -> (stdout: FileHandle, stdin: FileHandle, process: Process) {
    let process = Process()

    if pluginPath.hasSuffix(".py") {
        let pythonExe = ProcessInfo.processInfo.environment["PYTHON_EXECUTABLE"] ?? "python3"
        process.executableURL = URL(fileURLWithPath: pythonExe)
        process.arguments = [pluginPath]
    } else {
        process.executableURL = URL(fileURLWithPath: pluginPath)
        process.arguments = []
    }

    let stdinPipe = Pipe()
    let stdoutPipe = Pipe()
    let stderrPipe = Pipe()

    process.standardInput = stdinPipe
    process.standardOutput = stdoutPipe
    process.standardError = stderrPipe

    // Drain stderr in background
    DispatchQueue.global(qos: .background).async {
        let data = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        if !data.isEmpty {
            FileHandle.standardError.write(data)
        }
    }

    do {
        try process.run()
    } catch {
        fputs("Failed to spawn \(pluginPath): \(error)\n", stderr)
        exit(1)
    }

    return (
        stdout: stdoutPipe.fileHandleForReading,
        stdin: stdinPipe.fileHandleForWriting,
        process: process
    )
}

// MARK: - Run Modes

func runDirect(host: CborPluginHost) {
    do {
        try host.run(
            relayRead: FileHandle.standardInput,
            relayWrite: FileHandle.standardOutput,
            resourceFn: { Data() }
        )
    } catch {
        fputs("CborPluginHost.run error: \(error)\n", stderr)
        exit(1)
    }
}

func runWithRelay(host: CborPluginHost) {
    // Create two pipe pairs for bidirectional communication between slave and host.
    // Pipe A: slave writes → host reads
    let pipeA = Pipe()  // slave local_writer → host relay_read
    // Pipe B: host writes → slave reads
    let pipeB = Pipe()  // host relay_write → slave local_reader

    let hostRelayRead = pipeA.fileHandleForReading
    let slaveToHostWrite = pipeA.fileHandleForWriting
    let hostToSlaveRead = pipeB.fileHandleForReading
    let hostRelayWrite = pipeB.fileHandleForWriting

    let caps = host.capabilities
    let limits = CborLimits()

    var hostError: Error?
    let hostThread = Thread {
        do {
            try host.run(
                relayRead: hostRelayRead,
                relayWrite: hostRelayWrite,
                resourceFn: { Data() }
            )
        } catch {
            hostError = error
        }
        // Close host's pipe ends
        hostRelayRead.closeFile()
        hostRelayWrite.closeFile()
    }
    hostThread.start()

    // Run RelaySlave in main thread
    let slave = CborRelaySlave(localRead: hostToSlaveRead, localWrite: slaveToHostWrite)
    do {
        try slave.run(
            socketRead: FileHandle.standardInput,
            socketWrite: FileHandle.standardOutput,
            initialNotify: (manifest: caps.isEmpty ? Data("[]".utf8) : caps, limits: limits)
        )
    } catch {
        fputs("CborRelaySlave.run error: \(error)\n", stderr)
    }

    // Close slave's pipe ends to unblock host
    slaveToHostWrite.closeFile()
    hostToSlaveRead.closeFile()

    // Wait for host thread to finish
    Thread.sleep(forTimeInterval: 2.0)

    if let err = hostError {
        fputs("CborPluginHost.run error: \(err)\n", stderr)
    }
}

// MARK: - Main

let args = Args.parse()

if args.plugins.isEmpty {
    fputs("ERROR: at least one --spawn required\n", stderr)
    exit(1)
}

let host = CborPluginHost()
var processes: [Process] = []

for pluginPath in args.plugins {
    let (stdout, stdin, process) = spawnPlugin(pluginPath)
    processes.append(process)

    do {
        try host.attachPlugin(stdinHandle: stdin, stdoutHandle: stdout)
    } catch {
        fputs("Failed to attach \(pluginPath): \(error)\n", stderr)
        exit(1)
    }
}

// Register cleanup
atexit {
    for process in processes {
        if process.isRunning {
            process.terminate()
        }
    }
}

if args.relay {
    runWithRelay(host: host)
} else {
    runDirect(host: host)
}
