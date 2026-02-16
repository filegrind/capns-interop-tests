/// Multi-plugin relay host test binary for cross-language interop tests.
///
/// Creates a PluginHost managing N plugin subprocesses, with optional RelaySlave layer.
/// Communicates via raw CBOR frames on stdin/stdout OR Unix socket.
///
/// Without --relay:
///     stdin/stdout carry raw CBOR frames (PluginHost relay interface).
///
/// With --relay:
///     stdin/stdout OR socket carry CBOR frames including relay-specific types.
///     RelaySlave sits between stdin/stdout (or socket) and PluginHost.
///     Initial RelayNotify sent on startup.
///
/// With --listen <socket-path>:
///     Creates a Unix socket listener and accepts ONE connection from router.
///     Router and host are independent processes (not parent-child).

import Foundation
import Bifaci
import CapNs

// MARK: - Argument Parsing

struct Args {
    var plugins: [String] = []
    var relay: Bool = false
    var listenSocket: String? = nil

    static func parse() -> Args {
        var args = Args()
        var argv = Array(CommandLine.arguments.dropFirst())
        var i = 0
        while i < argv.count {
            switch argv[i] {
            case "--spawn":
                i += 1
                guard i < argv.count else {
                    fputs("ERROR: --spawn requires a path argument\n", stderr)
                    exit(1)
                }
                args.plugins.append(argv[i])
            case "--relay":
                args.relay = true
            case "--listen":
                i += 1
                guard i < argv.count else {
                    fputs("ERROR: --listen requires a socket path argument\n", stderr)
                    exit(1)
                }
                args.listenSocket = argv[i]
            default:
                fputs("ERROR: unknown argument: \(argv[i])\n", stderr)
                exit(1)
            }
            i += 1
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

    // Forward stderr continuously in background (not readDataToEndOfFile which blocks until EOF)
    let stderrReader = stderrPipe.fileHandleForReading
    DispatchQueue.global(qos: .background).async {
        while true {
            let chunk = stderrReader.availableData
            if chunk.isEmpty {
                break // EOF
            }
            FileHandle.standardError.write(chunk)
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

func runDirect(host: PluginHost) {
    do {
        try host.run(
            relayRead: FileHandle.standardInput,
            relayWrite: FileHandle.standardOutput,
            resourceFn: { Data() }
        )
    } catch {
        fputs("PluginHost.run error: \(error)\n", stderr)
        exit(1)
    }
}

func runWithRelay(host: PluginHost) {
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
    let limits = Limits()

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
    let slave = RelaySlave(localRead: hostToSlaveRead, localWrite: slaveToHostWrite)
    do {
        try slave.run(
            socketRead: FileHandle.standardInput,
            socketWrite: FileHandle.standardOutput,
            initialNotify: (manifest: caps.isEmpty ? Data("[]".utf8) : caps, limits: limits)
        )
    } catch {
        fputs("RelaySlave.run error: \(error)\n", stderr)
    }

    // Close slave's pipe ends to unblock host
    slaveToHostWrite.closeFile()
    hostToSlaveRead.closeFile()

    // Wait for host thread to finish
    Thread.sleep(forTimeInterval: 2.0)

    if let err = hostError {
        fputs("PluginHost.run error: \(err)\n", stderr)
    }
}

func runWithRelaySocket(host: PluginHost, socketPath: String) {
    // Remove existing socket if it exists
    try? FileManager.default.removeItem(atPath: socketPath)

    // Create Unix socket listener
    let sock = socket(AF_UNIX, SOCK_STREAM, 0)
    guard sock >= 0 else {
        fputs("Failed to create socket: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)

    let pathSize = MemoryLayout.size(ofValue: addr.sun_path)
    guard socketPath.count < pathSize else {
        fputs("Socket path too long: \(socketPath)\n", stderr)
        exit(1)
    }

    socketPath.withCString { cstr in
        withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
            strncpy(ptr, cstr, pathSize - 1)
        }
    }

    let bindResult = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(sock, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }

    guard bindResult == 0 else {
        fputs("Failed to bind socket \(socketPath): \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    guard listen(sock, 1) == 0 else {
        fputs("Failed to listen on socket: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    fputs("[RelayHost] Listening on socket: \(socketPath)\n", stderr)

    // Accept ONE connection from router
    var clientAddr = sockaddr_un()
    var clientLen = socklen_t(MemoryLayout<sockaddr_un>.size)
    let clientSock = withUnsafeMutablePointer(to: &clientAddr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            accept(sock, $0, &clientLen)
        }
    }

    guard clientSock >= 0 else {
        fputs("Failed to accept connection: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    fputs("[RelayHost] Router connected\n", stderr)

    // Close listener socket (only need one connection)
    close(sock)

    // Duplicate client socket for bidirectional communication
    let clientSockDup = dup(clientSock)
    guard clientSockDup >= 0 else {
        fputs("Failed to duplicate client socket: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    let socketRead = FileHandle(fileDescriptor: clientSock, closeOnDealloc: true)
    let socketWrite = FileHandle(fileDescriptor: clientSockDup, closeOnDealloc: true)

    // Create two pipe pairs for bidirectional communication between slave and host.
    // Pipe A: slave writes → host reads
    let pipeA = Pipe()
    // Pipe B: host writes → slave reads
    let pipeB = Pipe()

    let hostRelayRead = pipeA.fileHandleForReading
    let slaveToHostWrite = pipeA.fileHandleForWriting
    let hostToSlaveRead = pipeB.fileHandleForReading
    let hostRelayWrite = pipeB.fileHandleForWriting

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

    // Run RelaySlave in main thread with socket
    let slave = RelaySlave(localRead: hostToSlaveRead, localWrite: slaveToHostWrite)

    // Send initial RelayNotify with CAP_IDENTITY (always available).
    // PluginHost will send updated RelayNotify after plugins connect.
    let initialCaps = [CSCapIdentity]
    let initialCapsJson: Data
    do {
        initialCapsJson = try JSONSerialization.data(withJSONObject: initialCaps)
    } catch {
        fputs("Failed to serialize initial caps: \(error)\n", stderr)
        exit(1)
    }

    let capsStr = String(data: initialCapsJson, encoding: .utf8) ?? "<invalid UTF-8>"
    fputs("[RelayHost] Initial RelayNotify payload: \(initialCapsJson.count) bytes: \(capsStr)\n", stderr)
    let limits = Limits()

    do {
        try slave.run(
            socketRead: socketRead,
            socketWrite: socketWrite,
            initialNotify: (manifest: initialCapsJson, limits: limits)
        )
    } catch {
        fputs("RelaySlave.run error: \(error)\n", stderr)
    }

    // Close slave's pipe ends to unblock host
    slaveToHostWrite.closeFile()
    hostToSlaveRead.closeFile()

    // Close socket handles
    socketRead.closeFile()
    socketWrite.closeFile()

    // Wait for host thread to finish
    Thread.sleep(forTimeInterval: 2.0)

    if let err = hostError {
        fputs("PluginHost.run error: \(err)\n", stderr)
    }
}

// MARK: - Main

let args = Args.parse()

guard !args.plugins.isEmpty else {
    fputs("ERROR: at least one --spawn required\n", stderr)
    exit(1)
}

let host = PluginHost()
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
    if let socketPath = args.listenSocket {
        runWithRelaySocket(host: host, socketPath: socketPath)
    } else {
        runWithRelay(host: host)
    }
} else {
    runDirect(host: host)
}
