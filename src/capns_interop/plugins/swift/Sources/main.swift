import Foundation
import SwiftCBOR
import CapNsCbor
import CryptoKit

// MARK: - Manifest Building

func buildManifest() -> [String: Any] {
    // E-commerce semantic media URNs - must match across all plugin languages
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:customer-message;textable;form=scalar\";op=echo;out=\"media:customer-message;textable;form=scalar\"",
            "title": "Echo",
            "command": "echo"
        ],
        [
            "urn": "cap:in=\"media:order-value;json;textable;form=map\";op=double;out=\"media:loyalty-points;integer;textable;numeric;form=scalar\"",
            "title": "Double",
            "command": "double"
        ],
        [
            "urn": "cap:in=\"media:update-count;json;textable;form=map\";op=stream_chunks;out=\"media:order-updates;textable\"",
            "title": "Stream Chunks",
            "command": "stream_chunks"
        ],
        [
            "urn": "cap:in=\"media:product-image;bytes\";op=binary_echo;out=\"media:product-image;bytes\"",
            "title": "Binary Echo",
            "command": "binary_echo"
        ],
        [
            "urn": "cap:in=\"media:payment-delay-ms;json;textable;form=map\";op=slow_response;out=\"media:payment-result;textable;form=scalar\"",
            "title": "Slow Response",
            "command": "slow_response"
        ],
        [
            "urn": "cap:in=\"media:report-size;json;textable;form=map\";op=generate_large;out=\"media:sales-report;bytes\"",
            "title": "Generate Large",
            "command": "generate_large"
        ],
        [
            "urn": "cap:in=\"media:fulfillment-steps;json;textable;form=map\";op=with_status;out=\"media:fulfillment-status;textable;form=scalar\"",
            "title": "With Status",
            "command": "with_status"
        ],
        [
            "urn": "cap:in=\"media:payment-error;json;textable;form=map\";op=throw_error;out=\"media:void\"",
            "title": "Throw Error",
            "command": "throw_error"
        ],
        [
            "urn": "cap:in=\"media:customer-message;textable;form=scalar\";op=peer_echo;out=\"media:customer-message;textable;form=scalar\"",
            "title": "Peer Echo",
            "command": "peer_echo"
        ],
        [
            "urn": "cap:in=\"media:order-value;json;textable;form=map\";op=nested_call;out=\"media:final-price;integer;textable;numeric;form=scalar\"",
            "title": "Nested Call",
            "command": "nested_call"
        ],
        [
            "urn": "cap:in=\"media:monitoring-duration-ms;json;textable;form=map\";op=heartbeat_stress;out=\"media:health-status;textable;form=scalar\"",
            "title": "Heartbeat Stress",
            "command": "heartbeat_stress"
        ],
        [
            "urn": "cap:in=\"media:order-batch-size;json;textable;form=map\";op=concurrent_stress;out=\"media:batch-result;textable;form=scalar\"",
            "title": "Concurrent Stress",
            "command": "concurrent_stress"
        ],
        [
            "urn": "cap:in=\"media:void\";op=get_manifest;out=\"media:service-capabilities;json;textable;form=map\"",
            "title": "Get Manifest",
            "command": "get_manifest"
        ],
        [
            "urn": "cap:in=\"media:uploaded-document;bytes\";op=process_large;out=\"media:document-info;json;textable;form=map\"",
            "title": "Process Large",
            "command": "process_large"
        ],
        [
            "urn": "cap:in=\"media:uploaded-document;bytes\";op=hash_incoming;out=\"media:document-hash;textable;form=scalar\"",
            "title": "Hash Incoming",
            "command": "hash_incoming"
        ],
        [
            "urn": "cap:in=\"media:package-data;bytes\";op=verify_binary;out=\"media:verification-status;textable;form=scalar\"",
            "title": "Verify Binary",
            "command": "verify_binary"
        ],
        [
            "urn": "cap:in=\"media:invoice-path;textable;form=scalar\";op=read_file_info;out=\"media:invoice-metadata;json;textable;form=map\"",
            "title": "Read File Info",
            "command": "read_file_info",
            "args": [
                [
                    "media_urn": "media:invoice-path;textable;form=scalar",
                    "required": true,
                    "sources": [
                        ["stdin": "media:bytes"],
                        ["position": 0]
                    ],
                    "arg_description": "Path to invoice file to read"
                ] as [String: Any]
            ],
            "output": [
                "media_urn": "media:invoice-metadata;json;textable;form=map",
                "output_description": "Invoice file size and SHA256 checksum"
            ] as [String: Any]
        ]
    ]

    return [
        "name": "InteropTestPlugin",
        "version": "1.0.0",
        "description": "Interoperability testing plugin (Swift)",
        "caps": caps
    ]
}

func buildManifestJSON() -> String {
    let manifest = buildManifest()
    let data = try! JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys])
    return String(data: data, encoding: .utf8)!
}

// MARK: - Helper

// collectPayload reads all CHUNK frames, decodes each as CBOR, and accumulates bytes
// PROTOCOL: Each CHUNK payload is a complete, independently decodable CBOR value
// For byteString values, extract and concatenate the bytes
// For utf8String values, extract and concatenate as UTF-8 bytes
func collectPayload(from stream: AsyncStream<CborFrame>) async throws -> Data {
    var accumulated = Data()
    for await frame in stream {
        if case .chunk = frame.frameType, let payload = frame.payload {
            // Each CHUNK payload MUST be valid CBOR - decode it
            guard let value = try? CBOR.decode([UInt8](payload)) else {
                throw CborPluginRuntimeError.handlerError("CHUNK payload must be valid CBOR")
            }

            // Extract bytes from CBOR value
            switch value {
            case .byteString(let bytes):
                accumulated.append(Data(bytes))
            case .utf8String(let text):
                accumulated.append(text.data(using: .utf8)!)
            default:
                throw CborPluginRuntimeError.handlerError("Unexpected CBOR type in CHUNK: expected byteString or utf8String")
            }
        }
    }
    return accumulated
}

// collectPeerResponse reads peer response frames, decodes each CHUNK as CBOR, and reconstructs value
// For simple values (byteString/utf8String/int), there's typically one chunk
// For arrays/maps, multiple chunks are combined
func collectPeerResponse(from stream: AsyncStream<CborFrame>) async throws -> CBOR {
    var chunks: [CBOR] = []
    for await frame in stream {
        switch frame.frameType {
        case .chunk:
            if let payload = frame.payload {
                // Each CHUNK payload MUST be valid CBOR - decode it
                guard let value = try? CBOR.decode([UInt8](payload)) else {
                    throw CborPluginRuntimeError.handlerError("Invalid CBOR in CHUNK")
                }
                chunks.append(value)
            }
        case .end:
            break
        case .err:
            let code = frame.errorCode ?? "UNKNOWN"
            let message = frame.errorMessage ?? "Unknown error"
            throw CborPluginRuntimeError.peerRequestError("[\(code)] \(message)")
        default:
            continue
        }
    }

    // Reconstruct value from chunks
    if chunks.isEmpty {
        throw CborPluginRuntimeError.handlerError("No chunks received")
    } else if chunks.count == 1 {
        // Single chunk - return value as-is
        return chunks[0]
    } else {
        // Multiple chunks - concatenate bytes/strings, or collect array elements
        switch chunks[0] {
        case .byteString:
            // Concatenate all byte chunks
            var result = Data()
            for chunk in chunks {
                if case .byteString(let bytes) = chunk {
                    result.append(Data(bytes))
                } else {
                    throw CborPluginRuntimeError.handlerError("Mixed chunk types")
                }
            }
            return .byteString([UInt8](result))
        case .utf8String:
            // Concatenate all string chunks
            var result = ""
            for chunk in chunks {
                if case .utf8String(let text) = chunk {
                    result += text
                } else {
                    throw CborPluginRuntimeError.handlerError("Mixed chunk types")
                }
            }
            return .utf8String(result)
        default:
            // For other types (Integer, Array elements), collect as array
            return .array(chunks)
        }
    }
}

// MARK: - Handlers

func handleEcho(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    try emitter.emitCbor(.byteString([UInt8](payload)))
}

func handleDouble(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let value = json["value"] as! Int
    let result = value * 2
    // Return as CBOR integer (per protocol: int sent as single chunk)
    try emitter.emitCbor(.unsignedInt(UInt64(result)))
}

func handleStreamChunks(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let count = json["value"] as! Int

    for i in 0..<count {
        let chunk = "chunk-\(i)".data(using: .utf8)!
        try emitter.emitCbor(.byteString([UInt8](chunk)))
    }

    try emitter.emitCbor(.byteString([UInt8]("done".data(using: .utf8)!)))
}

func handleBinaryEcho(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    try emitter.emitCbor(.byteString([UInt8](payload)))
}

func handleSlowResponse(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let sleepMs = json["value"] as! Int

    try await Task.sleep(nanoseconds: UInt64(sleepMs) * 1_000_000)

    let response = "slept-\(sleepMs)ms"
    try emitter.emitCbor(.byteString([UInt8](response.data(using: .utf8)!)))
}

func handleGenerateLarge(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let size = json["value"] as! Int

    let pattern: [UInt8] = [65, 66, 67, 68, 69, 70, 71, 72] // "ABCDEFGH"
    var result = Data(capacity: size)
    for i in 0..<size {
        result.append(pattern[i % pattern.count])
    }

    try emitter.emitCbor(.byteString([UInt8](result)))
}

func handleWithStatus(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let steps = json["value"] as! Int

    for i in 0..<steps {
        let status = "step \(i)"
        emitter.emitLog(level: "info", message: "processing: \(status)")
        try await Task.sleep(nanoseconds: 10_000_000) // 10ms
    }

    try emitter.emitCbor(.byteString([UInt8]("completed".data(using: .utf8)!)))
}

func handleThrowError(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let message = json["value"] as! String
    throw NSError(domain: "InteropTestError", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
}

func handlePeerEcho(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    // Call host's echo capability
    let arg = CborCapArgumentValue(mediaUrn: "media:customer-message;textable;form=scalar", value: payload)
    let peerFrames = try peer.invoke(capUrn: "cap:in=*;op=echo;out=*", arguments: [arg])

    // Collect and decode peer response
    let cborValue = try await collectPeerResponse(from: peerFrames)

    // Re-emit (consumption → production)
    try emitter.emitCbor(cborValue)
}

func handleNestedCall(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let value = json["value"] as! Int

    // Call host's double capability
    let inputData = try JSONSerialization.data(withJSONObject: ["value": value])
    let arg = CborCapArgumentValue(mediaUrn: "media:order-value;json;textable;form=map", value: inputData)
    let peerFrames = try peer.invoke(capUrn: "cap:in=*;op=double;out=*", arguments: [arg])

    // Collect and decode peer response
    let cborValue = try await collectPeerResponse(from: peerFrames)

    // Extract integer from response
    let hostResult: Int
    switch cborValue {
    case .unsignedInt(let val):
        hostResult = Int(val)
    case .negativeInt(let val):
        hostResult = -Int(val) - 1
    default:
        throw CborPluginRuntimeError.handlerError("Expected integer from double")
    }

    // Double again locally
    let finalResult = hostResult * 2

    let finalData = try JSONSerialization.data(withJSONObject: finalResult, options: .fragmentsAllowed)
    try emitter.emitCbor(.byteString([UInt8](finalData)))
}

func handleHeartbeatStress(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let durationMs = json["value"] as! Int

    // Sleep in small chunks to allow heartbeat processing
    let chunks = durationMs / 100
    for _ in 0..<chunks {
        try await Task.sleep(nanoseconds: 100_000_000) // 100ms
    }
    try await Task.sleep(nanoseconds: UInt64(durationMs % 100) * 1_000_000)

    let response = "stressed-\(durationMs)ms"
    try emitter.emitCbor(.byteString([UInt8](response.data(using: .utf8)!)))
}

func handleConcurrentStress(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let workUnits = json["value"] as! Int

    // Simulate work
    var sum: UInt64 = 0
    for i in 0..<(workUnits * 1000) {
        sum = sum &+ UInt64(i)
    }

    let response = "computed-\(sum)"
    try emitter.emitCbor(.byteString([UInt8](response.data(using: .utf8)!)))
}

func handleGetManifest(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    _ = try await collectPayload(from: stream)
    let manifest = buildManifest()
    let resultData = try JSONSerialization.data(withJSONObject: manifest)
    try emitter.emitCbor(.byteString([UInt8](resultData)))
}

func handleProcessLarge(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let size = payload.count
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()

    let result: [String: Any] = [
        "size": size,
        "checksum": checksum
    ]

    let resultData = try JSONSerialization.data(withJSONObject: result)
    try emitter.emitCbor(.byteString([UInt8](resultData)))
}

func handleHashIncoming(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()
    try emitter.emitCbor(.byteString([UInt8](checksum.data(using: .utf8)!)))
}

func handleVerifyBinary(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    let payload = try await collectPayload(from: stream)
    var present = Set<UInt8>()

    for byte in payload {
        present.insert(byte)
    }

    if present.count == 256 {
        try emitter.emitCbor(.byteString([UInt8]("ok".data(using: .utf8)!)))
    } else {
        let missing = (0...255).filter { !present.contains(UInt8($0)) }
        let message = "missing \(missing.count) values"
        try emitter.emitCbor(.byteString([UInt8](message.data(using: .utf8)!)))
    }
}

func handleReadFileInfo(stream: AsyncStream<CborFrame>, emitter: CborStreamEmitter, peer: CborPeerInvoker) async throws -> Void {
    // Payload is already file bytes (auto-converted by runtime from file-path)
    let payload = try await collectPayload(from: stream)
    let size = payload.count
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()

    let result: [String: Any] = [
        "size": size,
        "checksum": checksum
    ]

    let resultData = try JSONSerialization.data(withJSONObject: result)
    try emitter.emitCbor(.byteString([UInt8](resultData)))
}

// MARK: - Main

let manifestJSON = buildManifestJSON()
let runtime = try! CborPluginRuntime(manifestJSON: manifestJSON)

// Register all handlers with exact e-commerce semantic URNs using registerRaw
runtime.registerRaw(capUrn: "cap:in=\"media:customer-message;textable;form=scalar\";op=echo;out=\"media:customer-message;textable;form=scalar\"", handler: handleEcho)
runtime.registerRaw(capUrn: "cap:in=\"media:order-value;json;textable;form=map\";op=double;out=\"media:loyalty-points;integer;textable;numeric;form=scalar\"", handler: handleDouble)
runtime.registerRaw(capUrn: "cap:in=\"media:update-count;json;textable;form=map\";op=stream_chunks;out=\"media:order-updates;textable\"", handler: handleStreamChunks)
runtime.registerRaw(capUrn: "cap:in=\"media:product-image;bytes\";op=binary_echo;out=\"media:product-image;bytes\"", handler: handleBinaryEcho)
runtime.registerRaw(capUrn: "cap:in=\"media:payment-delay-ms;json;textable;form=map\";op=slow_response;out=\"media:payment-result;textable;form=scalar\"", handler: handleSlowResponse)
runtime.registerRaw(capUrn: "cap:in=\"media:report-size;json;textable;form=map\";op=generate_large;out=\"media:sales-report;bytes\"", handler: handleGenerateLarge)
runtime.registerRaw(capUrn: "cap:in=\"media:fulfillment-steps;json;textable;form=map\";op=with_status;out=\"media:fulfillment-status;textable;form=scalar\"", handler: handleWithStatus)
runtime.registerRaw(capUrn: "cap:in=\"media:payment-error;json;textable;form=map\";op=throw_error;out=\"media:void\"", handler: handleThrowError)
runtime.registerRaw(capUrn: "cap:in=\"media:customer-message;textable;form=scalar\";op=peer_echo;out=\"media:customer-message;textable;form=scalar\"", handler: handlePeerEcho)
runtime.registerRaw(capUrn: "cap:in=\"media:order-value;json;textable;form=map\";op=nested_call;out=\"media:final-price;integer;textable;numeric;form=scalar\"", handler: handleNestedCall)
runtime.registerRaw(capUrn: "cap:in=\"media:monitoring-duration-ms;json;textable;form=map\";op=heartbeat_stress;out=\"media:health-status;textable;form=scalar\"", handler: handleHeartbeatStress)
runtime.registerRaw(capUrn: "cap:in=\"media:order-batch-size;json;textable;form=map\";op=concurrent_stress;out=\"media:batch-result;textable;form=scalar\"", handler: handleConcurrentStress)
runtime.registerRaw(capUrn: "cap:in=\"media:void\";op=get_manifest;out=\"media:service-capabilities;json;textable;form=map\"", handler: handleGetManifest)
runtime.registerRaw(capUrn: "cap:in=\"media:uploaded-document;bytes\";op=process_large;out=\"media:document-info;json;textable;form=map\"", handler: handleProcessLarge)
runtime.registerRaw(capUrn: "cap:in=\"media:uploaded-document;bytes\";op=hash_incoming;out=\"media:document-hash;textable;form=scalar\"", handler: handleHashIncoming)
runtime.registerRaw(capUrn: "cap:in=\"media:package-data;bytes\";op=verify_binary;out=\"media:verification-status;textable;form=scalar\"", handler: handleVerifyBinary)
runtime.registerRaw(capUrn: "cap:in=\"media:invoice-path;textable;form=scalar\";op=read_file_info;out=\"media:invoice-metadata;json;textable;form=map\"", handler: handleReadFileInfo)

try! runtime.run()
