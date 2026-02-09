/// Swift test host binary for cross-language matrix tests.
///
/// Reads JSON-line commands from stdin, manages a plugin subprocess
/// via CborPluginHost with a TestRouter, and writes JSON-line responses to stdout.

import Foundation
import CapNs
import CapNsCbor
@preconcurrency import SwiftCBOR

// MARK: - TestRouter (CborCapRouter implementation)

/// A test router that dispatches peer invoke requests to built-in echo/double handlers.
final class TestRouter: CborCapRouter, @unchecked Sendable {
    func beginRequest(capUrn: String, reqId: Data) throws -> CborPeerRequestHandle {
        guard let op = extractOp(from: capUrn) else {
            throw CborPluginHostError.peerInvokeNotSupported(capUrn)
        }

        let handler: (Data) -> Data
        switch op {
        case "echo":
            handler = { payload in payload }
        case "double":
            handler = { payload in
                if let json = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
                   let value = json["value"] as? NSNumber {
                    let doubled = value.intValue * 2
                    // NSJSONSerialization rejects bare scalars — encode directly as JSON number bytes
                    return Data("\(doubled)".utf8)
                }
                return Data()
            }
        default:
            throw CborPluginHostError.peerInvokeNotSupported(capUrn)
        }

        return TestRequestHandle(handler: handler)
    }

    private func extractOp(from capUrn: String) -> String? {
        // Try proper parsing first
        if let parsed = try? CSCapUrn.fromString(capUrn) {
            return parsed.getTag("op")
        }
        // Simple extraction for wildcard URNs
        for part in capUrn.split(separator: ";") {
            let trimmed = part.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("op=") {
                return String(trimmed.dropFirst(3))
            }
        }
        return nil
    }
}

// MARK: - TestRequestHandle (CborPeerRequestHandle implementation)

/// Accumulates streamed arguments, dispatches handler, sends response via AsyncStream.
final class TestRequestHandle: CborPeerRequestHandle, @unchecked Sendable {
    private let handler: (Data) -> Data
    private var streams: [(String, Data)] = [] // (stream_id, accumulated_data)
    private let lock = NSLock()
    private var continuation: AsyncStream<Result<CborResponseChunk, CborPluginHostError>>.Continuation?
    private let _responseStream: AsyncStream<Result<CborResponseChunk, CborPluginHostError>>

    init(handler: @escaping (Data) -> Data) {
        self.handler = handler
        var cont: AsyncStream<Result<CborResponseChunk, CborPluginHostError>>.Continuation!
        self._responseStream = AsyncStream { c in cont = c }
        self.continuation = cont
    }

    func forwardFrame(_ frame: CborFrame) {
        switch frame.frameType {
        case .streamStart:
            let streamId = frame.streamId ?? ""
            lock.lock()
            streams.append((streamId, Data()))
            lock.unlock()

        case .chunk:
            let streamId = frame.streamId ?? ""
            let payload = frame.payload ?? Data()
            lock.lock()
            if let index = streams.firstIndex(where: { $0.0 == streamId }) {
                streams[index].1.append(payload)
            }
            lock.unlock()

        case .streamEnd:
            // No-op — stream tracking only
            break

        case .end:
            // Concatenate all stream data
            lock.lock()
            var payload = Data()
            for (_, data) in streams {
                payload.append(data)
            }
            lock.unlock()

            // Execute handler
            let result = handler(payload)

            // Send single response chunk
            continuation?.yield(.success(CborResponseChunk(
                payload: result,
                seq: 0,
                offset: nil,
                len: nil,
                isEof: true
            )))
            continuation?.finish()

        default:
            break
        }
    }

    func responseStream() -> AsyncStream<Result<CborResponseChunk, CborPluginHostError>> {
        return _responseStream
    }
}

// MARK: - SwiftTestHost

struct SwiftTestHost {
    var pluginHost: CborPluginHost?
    var pluginProcess: Process?

    mutating func handleSpawn(_ cmd: [String: Any]) -> [String: Any] {
        guard let pluginPath = cmd["plugin_path"] as? String else {
            return ["ok": false, "error": "Missing plugin_path"]
        }

        let process = Process()

        if pluginPath.hasSuffix(".py") {
            let pythonExe = ProcessInfo.processInfo.environment["PYTHON_EXECUTABLE"] ?? "python3"
            process.executableURL = URL(fileURLWithPath: pythonExe)
            process.arguments = [pluginPath]
        } else {
            process.executableURL = URL(fileURLWithPath: pluginPath)
        }

        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()

        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        // Drain stderr in background
        DispatchQueue.global().async {
            let data = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            if !data.isEmpty {
                FileHandle.standardError.write(data)
            }
        }

        do {
            try process.run()
        } catch {
            return ["ok": false, "error": "Failed to spawn: \(error)"]
        }

        let router = TestRouter()

        do {
            let host = try CborPluginHost(
                stdinHandle: stdinPipe.fileHandleForWriting,
                stdoutHandle: stdoutPipe.fileHandleForReading,
                router: router
            )

            let manifest = host.pluginManifest ?? Data()
            let manifestB64 = manifest.base64EncodedString()

            self.pluginHost = host
            self.pluginProcess = process

            return ["ok": true, "manifest_b64": manifestB64]
        } catch {
            process.terminate()
            return ["ok": false, "error": "Handshake failed: \(error)"]
        }
    }

    func handleCall(_ cmd: [String: Any]) async -> [String: Any] {
        guard let host = pluginHost else {
            return ["ok": false, "error": "No host"]
        }

        let capUrn = cmd["cap_urn"] as? String ?? ""

        guard let argsRaw = cmd["arguments"] as? [[String: Any]] else {
            return ["ok": false, "error": "Missing 'arguments' array"]
        }

        var arguments: [(mediaUrn: String, value: Data)] = []
        for argMap in argsRaw {
            guard let mediaUrn = argMap["media_urn"] as? String else {
                return ["ok": false, "error": "Argument missing 'media_urn'"]
            }
            let valueB64 = argMap["value_b64"] as? String ?? ""
            guard let value = Data(base64Encoded: valueB64) else {
                return ["ok": false, "error": "Invalid base64 in argument"]
            }
            arguments.append((mediaUrn: mediaUrn, value: value))
        }

        let start = DispatchTime.now()

        do {
            let response = try await host.callWithArguments(capUrn: capUrn, arguments: arguments)
            let durationNs = DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds

            // Collect raw data from response
            let rawData: Data
            switch response {
            case .single(let data):
                rawData = data
            case .streaming(let chunks):
                var allData = Data()
                for chunk in chunks {
                    allData.append(chunk.payload)
                }
                rawData = allData
            }

            // Decode CBOR values — matches Rust host's decode_cbor_values() exactly
            if let decoded = decodeCborValues(rawData) {
                if decoded.count == 1 {
                    return [
                        "ok": true,
                        "payload_b64": decoded[0].base64EncodedString(),
                        "is_streaming": false,
                        "duration_ns": durationNs,
                    ]
                } else if decoded.count > 1 {
                    let chunksB64 = decoded.map { $0.base64EncodedString() }
                    return [
                        "ok": true,
                        "is_streaming": true,
                        "chunks_b64": chunksB64,
                        "duration_ns": durationNs,
                    ]
                }
            }

            // Raw (non-CBOR) data
            return [
                "ok": true,
                "payload_b64": rawData.base64EncodedString(),
                "is_streaming": false,
                "duration_ns": durationNs,
            ]
        } catch {
            return ["ok": false, "error": "\(error)"]
        }
    }

    func handleSendHeartbeat() async -> [String: Any] {
        guard let host = pluginHost else {
            return ["ok": false, "error": "No host"]
        }
        do {
            try await host.sendHeartbeat()
            return ["ok": true]
        } catch {
            return ["ok": false, "error": "\(error)"]
        }
    }

    func handleGetManifest() -> [String: Any] {
        guard let host = pluginHost else {
            return ["ok": false, "error": "No host"]
        }
        let manifest = host.pluginManifest ?? Data()
        return ["ok": true, "manifest_b64": manifest.base64EncodedString()]
    }

    mutating func handleShutdown() -> [String: Any] {
        if let host = pluginHost {
            host.close()
            self.pluginHost = nil
        }
        if let process = pluginProcess {
            process.terminate()
            self.pluginProcess = nil
        }
        return ["ok": true]
    }
}

// MARK: - CBOR Decode Helper

/// Decode ALL CBOR values from concatenated bytes, extracting inner bytes from each.
/// Returns nil if the data is not valid CBOR.
/// Matches the Rust host's decode_cbor_values() behavior exactly.
func decodeCborValues(_ data: Data) -> [Data]? {
    if data.isEmpty { return [] }

    var results: [Data] = []
    var bytes = [UInt8](data)
    var offset = 0

    while offset < bytes.count {
        let remaining = Array(bytes[offset...])
        guard let decoded = try? CBOR.decode(remaining) else {
            if results.isEmpty {
                return nil  // Not CBOR at all
            }
            break  // Trailing non-CBOR data after valid CBOR items
        }

        let value: Data?
        switch decoded {
        case .byteString(let b):
            value = Data(b)
        case .utf8String(let s):
            value = Data(s.utf8)
        default:
            if let jsonValue = cborToJsonValue(decoded),
               let jsonData = try? JSONSerialization.data(withJSONObject: jsonValue) {
                value = jsonData
            } else {
                value = nil
            }
        }

        guard let v = value else { break }
        results.append(v)

        // Advance offset past the decoded CBOR item
        // Re-encode to find the byte length consumed
        let encodedLen = decoded.encode().count
        offset += encodedLen
    }

    return results.isEmpty ? nil : results
}

func cborToJsonValue(_ cbor: CBOR) -> Any? {
    switch cbor {
    case .unsignedInt(let n): return n
    case .negativeInt(let n): return -Int(n) - 1
    case .utf8String(let s): return s
    case .boolean(let b): return b
    case .null: return NSNull()
    case .float(let f): return f
    case .double(let d): return d
    case .byteString(let bytes): return Data(bytes).base64EncodedString()
    case .array(let arr): return arr.compactMap { cborToJsonValue($0) }
    case .map(let pairs):
        var dict: [String: Any] = [:]
        for (k, v) in pairs {
            if case .utf8String(let key) = k, let val = cborToJsonValue(v) {
                dict[key] = val
            }
        }
        return dict
    default:
        return nil
    }
}

// MARK: - Main

var host = SwiftTestHost()

// Read JSON-line commands from stdin
while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }

    guard let cmdData = line.data(using: .utf8),
          let cmd = try? JSONSerialization.jsonObject(with: cmdData) as? [String: Any] else {
        let resp = ["ok": false, "error": "Invalid JSON"] as [String: Any]
        writeResponse(resp)
        continue
    }

    let cmdType = cmd["cmd"] as? String ?? ""

    let response: [String: Any]
    switch cmdType {
    case "spawn":
        response = host.handleSpawn(cmd)
    case "call":
        // Need to run async code synchronously
        let semaphore = DispatchSemaphore(value: 0)
        var asyncResponse: [String: Any] = [:]
        Task {
            asyncResponse = await host.handleCall(cmd)
            semaphore.signal()
        }
        semaphore.wait()
        response = asyncResponse
    case "send_heartbeat":
        let semaphore = DispatchSemaphore(value: 0)
        var asyncResponse: [String: Any] = [:]
        Task {
            asyncResponse = await host.handleSendHeartbeat()
            semaphore.signal()
        }
        semaphore.wait()
        response = asyncResponse
    case "get_manifest":
        response = host.handleGetManifest()
    case "shutdown":
        let resp = host.handleShutdown()
        writeResponse(resp)
        exit(0)
    default:
        response = ["ok": false, "error": "Unknown command: \(cmdType)"]
    }

    writeResponse(response)
}

func writeResponse(_ dict: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: dict),
          let str = String(data: data, encoding: .utf8) else {
        print("{\"ok\":false,\"error\":\"Failed to encode response\"}")
        fflush(stdout)
        return
    }
    print(str)
    fflush(stdout)
}
