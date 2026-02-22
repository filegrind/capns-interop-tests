/// Swift Router Binary for Interop Tests
///
/// Position: Router (RelaySwitch + RelayMaster)
/// Communicates with test orchestration via stdin/stdout (CBOR frames)
/// Connects to independent relay host processes via Unix sockets
///
/// Usage:
///   capns-interop-router-swift --connect <socket-path> [--connect <another-socket>]

import Foundation
import Bifaci

struct Args {
    var socketPaths: [String] = []
}

func parseArgs() -> Args {
    var args = Args()
    let argv = Array(CommandLine.arguments.dropFirst())
    var i = 0
    while i < argv.count {
        switch argv[i] {
        case "--connect":
            i += 1
            guard i < argv.count else {
                fputs("ERROR: --connect requires a socket path argument\n", stderr)
                exit(1)
            }
            args.socketPaths.append(argv[i])
        default:
            fputs("ERROR: unknown argument: \(argv[i])\n", stderr)
            exit(1)
        }
        i += 1
    }
    return args
}

func connectToHost(socketPath: String) -> SocketPair {
    fputs("[Router] Connecting to relay host at: \(socketPath)\n", stderr)

    // Connect to the relay host's listening socket
    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)

    let pathSize = MemoryLayout.size(ofValue: addr.sun_path)
    guard socketPath.count < pathSize else {
        fputs("ERROR: Socket path too long: \(socketPath)\n", stderr)
        exit(1)
    }

    socketPath.withCString { cstr in
        withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
            strncpy(ptr, cstr, pathSize - 1)
        }
    }

    let sock = socket(AF_UNIX, SOCK_STREAM, 0)
    guard sock >= 0 else {
        fputs("ERROR: Failed to create socket: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    let connectResult = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.connect(sock, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }

    guard connectResult == 0 else {
        fputs("ERROR: Failed to connect to \(socketPath): \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    fputs("[Router] Connected to relay host at \(socketPath)\n", stderr)

    // Duplicate the file descriptor for separate read/write handles
    let dupSock = dup(sock)
    guard dupSock >= 0 else {
        fputs("ERROR: Failed to duplicate socket: \(String(cString: strerror(errno)))\n", stderr)
        exit(1)
    }

    let readHandle = FileHandle(fileDescriptor: sock, closeOnDealloc: true)
    let writeHandle = FileHandle(fileDescriptor: dupSock, closeOnDealloc: true)

    return SocketPair(read: readHandle, write: writeHandle)
}

// Main entry point
let args = parseArgs()

guard !args.socketPaths.isEmpty else {
    fputs("ERROR: at least one --connect <socket-path> required\n", stderr)
    exit(1)
}

// Connect to all relay host sockets
var socketPairs: [SocketPair] = []

for socketPath in args.socketPaths {
    let socketPair = connectToHost(socketPath: socketPath)
    socketPairs.append(socketPair)
}

// Create RelaySwitch with all host connections
fputs("[Router] Creating RelaySwitch with \(socketPairs.count) host(s)\n", stderr)

let relaySwitch: RelaySwitch
do {
    relaySwitch = try RelaySwitch(sockets: socketPairs)
} catch {
    fputs("Failed to create RelaySwitch: \(error)\n", stderr)
    exit(1)
}

fputs("[Router] RelaySwitch initialized, connected to \(args.socketPaths.count) relay host(s)\n", stderr)

// Send initial RelayNotify to engine with aggregate capabilities.
// The full capabilities from hosts were consumed during identity verification
// in RelaySwitch.init(), so the engine hasn't seen them yet.
do {
    let stdout = FileHandle.standardOutput
    let writer = FrameWriter(handle: stdout)
    let manifest = relaySwitch.capabilities()
    let limits = relaySwitch.limits()
    let notify = Frame.relayNotify(manifest: manifest, limits: limits)
    try writer.write(notify)
    fputs("[Router] Sent initial RelayNotify to engine (\(manifest.count) bytes)\n", stderr)
} catch {
    fputs("Failed to write initial RelayNotify to engine: \(error)\n", stderr)
    exit(1)
}

// Router is a pure multiplexer - two independent loops:
//   - Thread 1: stdin → queue (continuously read stdin, send frames to queue)
//   - Thread 2 (main): queue + RelaySwitch → stdout (multiplex stdin frames and master frames)
//
// No coupling between them! Frames flow independently in both directions.

let stdinQueue = BlockingQueue<Frame>()
let stdinEOF = NSCondition()
var stdinClosed = false

// Thread 1: stdin → queue
Thread.detachNewThread {
    let stdin = FileHandle.standardInput
    let reader = FrameReader(handle: stdin)

    fputs("[Router/stdin] Starting stdin reader loop\n", stderr)
    while true {
        do {
            guard let frame = try reader.read() else {
                fputs("[Router/stdin] EOF on stdin, exiting\n", stderr)
                stdinEOF.lock()
                stdinClosed = true
                stdinEOF.signal()
                stdinEOF.unlock()
                break
            }
            fputs("[Router/stdin] Read frame: \(frame.frameType) (id=\(frame.id))\n", stderr)
            stdinQueue.push(frame)
        } catch {
            fputs("[Router/stdin] Error reading: \(error)\n", stderr)
            stdinEOF.lock()
            stdinClosed = true
            stdinEOF.signal()
            stdinEOF.unlock()
            break
        }
    }
}

// Main thread: multiplex stdinQueue and RelaySwitch
let stdout = FileHandle.standardOutput
let writer = FrameWriter(handle: stdout)
var seqAssigner = SeqAssigner()

// Track pending requests: requests sent to masters that haven't received END/ERR yet
var pendingRequests = Set<MessageId>()

fputs("[Router/main] Starting main multiplexer loop\n", stderr)

// Main loop: balanced interleaving of stdin and master frames
// Process one stdin frame, then one master frame (with timeout), repeat
while true {
    // Try to read ONE stdin frame (non-blocking with minimal timeout)
    if let frame = stdinQueue.tryPop(timeout: 0.0001) {
        fputs("[Router/main] Sending stdin frame to master: \(frame.frameType) (id=\(frame.id))\n", stderr)
        let frameId = frame.id
        let isReq = frame.frameType == FrameType.req
        do {
            try relaySwitch.sendToMaster(frame, preferredCap: nil)
            // Track REQ frames - they need END/ERR before we can shut down
            if isReq {
                pendingRequests.insert(frameId)
            }
        } catch {
            fputs("[Router/main] Error sending to master: \(error)\n", stderr)
            // On REQ failure, send ERR back to engine so it doesn't hang
            if isReq {
                let errFrame = Frame.err(id: frameId, code: "NO_HANDLER", message: "\(error)")
                try? writer.write(errFrame)
            }
        }
    }

    // Check if stdin is closed
    stdinEOF.lock()
    let isClosed = stdinClosed
    stdinEOF.unlock()

    // Try to read ONE master frame (with minimal timeout for responsiveness)
    do {
        if var frame = try relaySwitch.readFromMasters(timeout: 0.0001) {
            fputs("[Router/main] Received from master: \(frame.frameType) (id=\(frame.id))\n", stderr)
            seqAssigner.assign(&frame)
            try writer.write(frame)
            // Track completion: END or ERR means request is done
            if frame.frameType == FrameType.end || frame.frameType == FrameType.err {
                seqAssigner.remove(FlowKey.fromFrame(frame))
                pendingRequests.remove(frame.id)
            }
        } else if isClosed && stdinQueue.isEmpty() && pendingRequests.isEmpty {
            // Guaranteed shutdown: stdin closed AND no pending stdin frames AND all requests completed
            fputs("[Router/main] stdin closed and all \(pendingRequests.count) pending requests completed, shutting down\n", stderr)
            break
        }
        // nil with stdin still open = timeout, loop back to check stdin
    } catch {
        fputs("[Router/main] ERROR reading from masters: \(error) - Router exiting and closing connections!\n", stderr)
        fputs("[Router/main] THIS IS A BUG - Router should NOT exit while test is running!\n", stderr)
        break
    }
}

// Cleanup
try? writer.flush()  // Flush any buffered frames before shutdown
fputs("[Router] Shutting down - relay hosts will continue running independently\n", stderr)
