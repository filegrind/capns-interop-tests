/// Swift test host binary for cross-language matrix tests.
///
/// Reads JSON-line commands from stdin, manages a plugin subprocess
/// via direct CBOR frame communication, and writes JSON-line responses to stdout.

import Foundation
import CapNs
import Bifaci
@preconcurrency import SwiftCBOR

// MARK: - Single Plugin Wrapper

/// Wraps a single plugin subprocess with CBOR frame communication.
final class PluginWrapper {
    private let process: Process
    private let reader: FrameReader
    private let writer: FrameWriter
    private let stdinPipe: Pipe
    private let stdoutPipe: Pipe

    init(pluginPath: String) throws {
        let process = Process()
        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()

        if pluginPath.hasSuffix(".py") {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["python3", pluginPath]
        } else if pluginPath.contains("/") {
            process.executableURL = URL(fileURLWithPath: pluginPath)
        } else {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = [pluginPath]
        }

        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = FileHandle.standardError

        let writer = FrameWriter(handle: stdinPipe.fileHandleForWriting)
        let reader = FrameReader(handle: stdoutPipe.fileHandleForReading)

        self.process = process
        self.stdinPipe = stdinPipe
        self.stdoutPipe = stdoutPipe
        self.writer = writer
        self.reader = reader

        try process.run()

        // Perform handshake
        let ourLimits = Limits()
        let helloFrame = Frame.hello(limits: ourLimits)
        try writer.write(helloFrame)

        guard let theirHello = try reader.read() else {
            throw PluginHostError.handshakeFailed("Plugin closed before HELLO")
        }
        guard theirHello.frameType == .hello else {
            throw PluginHostError.handshakeFailed("Expected HELLO, got \(theirHello.frameType)")
        }

        // Negotiate limits
        let theirMaxFrame = theirHello.helloMaxFrame ?? DEFAULT_MAX_FRAME
        let theirMaxChunk = theirHello.helloMaxChunk ?? DEFAULT_MAX_CHUNK
        let theirMaxReorder = theirHello.helloMaxReorderBuffer ?? DEFAULT_MAX_REORDER_BUFFER

        let negotiated = Limits(
            maxFrame: min(ourLimits.maxFrame, theirMaxFrame),
            maxChunk: min(ourLimits.maxChunk, theirMaxChunk),
            maxReorderBuffer: min(ourLimits.maxReorderBuffer, theirMaxReorder)
        )

        writer.setLimits(negotiated)
        reader.setLimits(negotiated)
    }

    func executeCap(capUrn: String, payload: Data, contentType: String = "application/json") throws -> Data {
        // Generate MessageId from UUID
        let reqId = MessageId.newUUID()

        // Send REQ frame
        let reqFrame = Frame.req(
            id: reqId,
            capUrn: capUrn,
            payload: payload,
            contentType: contentType
        )
        try writer.write(reqFrame)

        // Send END frame
        let endFrame = Frame.end(id: reqId, finalPayload: nil)
        try writer.write(endFrame)

        // Read response frames until END or ERR
        var result = Data()

        while true {
            guard let frame = try reader.read() else {
                throw PluginHostError.processExited
            }

            // Only process frames for our request ID
            guard frame.id == reqId else {
                continue
            }

            switch frame.frameType {
            case .chunk:
                if let chunkPayload = frame.payload {
                    result.append(chunkPayload)
                }

            case .end:
                if let finalPayload = frame.payload {
                    result.append(finalPayload)
                }
                return result

            case .err:
                let code = frame.errorCode ?? "UNKNOWN"
                let msg = frame.errorMessage ?? "Unknown error"
                throw PluginHostError.pluginError(code: code, message: msg)

            case .streamStart, .streamEnd:
                // Skip stream markers
                continue

            case .log:
                // Skip log frames
                continue

            default:
                throw PluginHostError.unexpectedFrameType(frame.frameType)
            }
        }
    }

    func shutdown() {
        try? stdinPipe.fileHandleForWriting.close()
        process.terminate()
        process.waitUntilExit()
    }
}

// MARK: - JSON Protocol

struct Command: Codable {
    let action: String
    let plugin: String?
    let cap_urn: String?
    let payload: String? // base64-encoded
}

struct Response: Codable {
    let ok: Bool
    let result: String? // base64-encoded
    let error: String?
}

// MARK: - Main Loop

var pluginWrapper: PluginWrapper?

let encoder = JSONEncoder()
let decoder = JSONDecoder()

while let line = readLine() {
    if line.isEmpty { continue }

    guard let cmd = try? decoder.decode(Command.self, from: Data(line.utf8)) else {
        let resp = Response(ok: false, result: nil, error: "Invalid JSON")
        if let json = try? encoder.encode(resp) {
            FileHandle.standardOutput.write(json)
            FileHandle.standardOutput.write(Data("\n".utf8))
        }
        continue
    }

    do {
        switch cmd.action {
        case "spawn":
            guard let pluginPath = cmd.plugin else {
                throw PluginHostError.protocolError("Missing plugin path")
            }
            pluginWrapper = try PluginWrapper(pluginPath: pluginPath)

            let resp = Response(ok: true, result: nil, error: nil)
            if let json = try? encoder.encode(resp) {
                FileHandle.standardOutput.write(json)
                FileHandle.standardOutput.write(Data("\n".utf8))
            }

        case "execute_cap":
            guard let wrapper = pluginWrapper else {
                throw PluginHostError.protocolError("No plugin spawned")
            }
            guard let capUrn = cmd.cap_urn else {
                throw PluginHostError.protocolError("Missing cap_urn")
            }

            let payload: Data
            if let b64 = cmd.payload, let decoded = Data(base64Encoded: b64) {
                payload = decoded
            } else {
                payload = Data()
            }

            let result = try wrapper.executeCap(capUrn: capUrn, payload: payload)
            let b64Result = result.base64EncodedString()

            let resp = Response(ok: true, result: b64Result, error: nil)
            if let json = try? encoder.encode(resp) {
                FileHandle.standardOutput.write(json)
                FileHandle.standardOutput.write(Data("\n".utf8))
            }

        case "shutdown":
            pluginWrapper?.shutdown()
            pluginWrapper = nil

            let resp = Response(ok: true, result: nil, error: nil)
            if let json = try? encoder.encode(resp) {
                FileHandle.standardOutput.write(json)
                FileHandle.standardOutput.write(Data("\n".utf8))
            }
            exit(0)

        default:
            throw PluginHostError.protocolError("Unknown action: \(cmd.action)")
        }
    } catch {
        let resp = Response(ok: false, result: nil, error: error.localizedDescription)
        if let json = try? encoder.encode(resp) {
            FileHandle.standardOutput.write(json)
            FileHandle.standardOutput.write(Data("\n".utf8))
        }
    }
}
