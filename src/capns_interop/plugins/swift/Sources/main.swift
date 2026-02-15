import Foundation
import SwiftCBOR
import Bifaci
import CryptoKit

// Type aliases to avoid ambiguity with Foundation.OutputStream
typealias BifaciOutputStream = Bifaci.OutputStream
typealias BifaciInputStream = Bifaci.InputStream

// MARK: - Manifest Building

func buildManifest() -> [String: Any] {
    // E-commerce semantic media URNs - must match across all plugin languages
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:bytes\";op=echo;out=\"media:bytes\"",
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
            "urn": "cap:in=\"media:invoice;file-path;textable;form=scalar\";op=read_file_info;out=\"media:invoice-metadata;json;textable;form=map\"",
            "title": "Read File Info",
            "command": "read_file_info",
            "args": [
                [
                    "media_urn": "media:invoice;file-path;textable;form=scalar",
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

// MARK: - Helper Functions

/// Extract first CBOR value from input stream (for single-arg handlers)
func firstValue(from input: InputPackage) throws -> CBOR {
    guard let streamResult = input.nextStream() else {
        throw PluginRuntimeError.handlerError("No input stream")
    }
    let stream = try streamResult.get()
    return try stream.collectValue()
}

/// Convert CBOR value to Data
func cborToData(_ value: CBOR) throws -> Data {
    switch value {
    case .byteString(let bytes):
        return Data(bytes)
    case .utf8String(let text):
        return text.data(using: .utf8)!
    default:
        throw PluginRuntimeError.handlerError("Expected byteString or utf8String, got \(value)")
    }
}

/// Convert CBOR map to JSON Data
func cborMapToJSON(_ value: CBOR) throws -> Data {
    guard case .map(let dict) = value else {
        throw PluginRuntimeError.handlerError("Expected CBOR map")
    }

    var swiftDict: [String: Any] = [:]
    for (key, val) in dict {
        guard case .utf8String(let keyStr) = key else {
            throw PluginRuntimeError.handlerError("Map key must be string")
        }
        swiftDict[keyStr] = cborToAny(val)
    }
    return try JSONSerialization.data(withJSONObject: swiftDict)
}

/// Convert CBOR to Any for JSON serialization
func cborToAny(_ value: CBOR) -> Any {
    switch value {
    case .unsignedInt(let n):
        return Int(n)
    case .negativeInt(let n):
        return -Int(n) - 1
    case .utf8String(let s):
        return s
    case .byteString(let b):
        return Data(b)
    case .array(let arr):
        return arr.map { cborToAny($0) }
    case .map(let m):
        var dict: [String: Any] = [:]
        for (k, v) in m {
            if case .utf8String(let key) = k {
                dict[key] = cborToAny(v)
            }
        }
        return dict
    case .boolean(let b):
        return b
    case .null:
        return NSNull()
    case .float(let f):
        return f
    case .double(let d):
        return d
    default:
        return NSNull()
    }
}

/// Parse JSON input from CBOR value (handles both map and byteString)
func parseJSONInput(_ value: CBOR) throws -> [String: Any] {
    let jsonData: Data
    if case .map = value {
        jsonData = try cborMapToJSON(value)
    } else {
        jsonData = try cborToData(value)
    }
    return try JSONSerialization.jsonObject(with: jsonData) as! [String: Any]
}

// MARK: - Handlers

func handleEcho(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()
    try output.write(payload)
    try output.close()
}

func handleDouble(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let inputValue = json["value"] as! Int
    let result = inputValue * 2
    try output.emitCbor(CBOR.unsignedInt(UInt64(result)))
    try output.close()
}

func handleStreamChunks(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let count = json["value"] as! Int

    for i in 0..<count {
        let chunk = "chunk-\(i)".data(using: .utf8)!
        try output.emitCbor(CBOR.byteString([UInt8](chunk)))
    }

    try output.emitCbor(CBOR.byteString([UInt8]("done".data(using: .utf8)!)))
    try output.close()
}

func handleBinaryEcho(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()
    try output.write(payload)
    try output.close()
}

func handleSlowResponse(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let sleepMs = json["value"] as! Int

    Thread.sleep(forTimeInterval: Double(sleepMs) / 1000.0)

    let response = "slept-\(sleepMs)ms"
    try output.emitCbor(CBOR.byteString([UInt8](response.data(using: .utf8)!)))
    try output.close()
}

func handleGenerateLarge(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let size = json["value"] as! Int

    let pattern: [UInt8] = [65, 66, 67, 68, 69, 70, 71, 72] // "ABCDEFGH"
    var result = Data(capacity: size)
    for i in 0..<size {
        result.append(pattern[i % pattern.count])
    }

    try output.write(result)
    try output.close()
}

func handleWithStatus(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let steps = json["value"] as! Int

    for i in 0..<steps {
        let status = "step \(i)"
        output.log(level: "info", message: "processing: \(status)")
        Thread.sleep(forTimeInterval: 0.01) // 10ms
    }

    try output.emitCbor(CBOR.byteString([UInt8]("completed".data(using: .utf8)!)))
    try output.close()
}

func handleThrowError(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let message = json["value"] as! String
    throw NSError(domain: "InteropTestError", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
}

func handlePeerEcho(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()

    // Call host's echo capability
    let call = try peer.call(capUrn: "cap:in=media:;out=media:")
    let arg = call.arg(mediaUrn: "media:customer-message;textable;form=scalar")
    try arg.write(payload)
    try arg.close()

    let response = try call.finish()
    let responseBytes = try response.collectBytes()

    try output.write(responseBytes)
    try output.close()
}

func handleNestedCall(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let inputValue = json["value"] as! Int

    // Call host's double capability
    let inputData = try JSONSerialization.data(withJSONObject: ["value": inputValue])
    let call = try peer.call(capUrn: "cap:in=*;op=double;out=*")
    let arg = call.arg(mediaUrn: "media:order-value;json;textable;form=map")
    try arg.write(inputData)
    try arg.close()

    let response = try call.finish()
    let responseCbor = try response.collectValue()

    // Extract integer from response
    let hostResult: Int
    switch responseCbor {
    case .unsignedInt(let val):
        hostResult = Int(val)
    case .negativeInt(let val):
        hostResult = -Int(val) - 1
    default:
        throw PluginRuntimeError.handlerError("Expected integer from double")
    }

    // Double again locally
    let finalResult = hostResult * 2

    let finalData = try JSONSerialization.data(withJSONObject: finalResult, options: .fragmentsAllowed)
    try output.write(finalData)
    try output.close()
}

func handleHeartbeatStress(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let durationMs = json["value"] as! Int

    Thread.sleep(forTimeInterval: Double(durationMs) / 1000.0)

    let response = "stressed-\(durationMs)ms"
    try output.emitCbor(CBOR.byteString([UInt8](response.data(using: .utf8)!)))
    try output.close()
}

func handleConcurrentStress(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let value = try firstValue(from: input)
    let json = try parseJSONInput(value)
    let workUnits = json["value"] as! Int

    // Simulate work
    var sum: UInt64 = 0
    for i in 0..<(workUnits * 1000) {
        sum = sum &+ UInt64(i)
    }

    let response = "computed-\(sum)"
    try output.emitCbor(CBOR.byteString([UInt8](response.data(using: .utf8)!)))
    try output.close()
}

func handleGetManifest(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    _ = try input.collectAllBytes() // Consume input
    let manifest = buildManifest()
    let resultData = try JSONSerialization.data(withJSONObject: manifest)
    try output.write(resultData)
    try output.close()
}

func handleProcessLarge(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()
    let size = payload.count
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()

    let result: [String: Any] = [
        "size": size,
        "checksum": checksum
    ]

    let resultData = try JSONSerialization.data(withJSONObject: result)
    try output.write(resultData)
    try output.close()
}

func handleHashIncoming(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()
    try output.emitCbor(CBOR.byteString([UInt8](checksum.data(using: .utf8)!)))
    try output.close()
}

func handleVerifyBinary(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    let payload = try input.collectAllBytes()
    var present = Set<UInt8>()

    for byte in payload {
        present.insert(byte)
    }

    if present.count == 256 {
        try output.emitCbor(CBOR.byteString([UInt8]("ok".data(using: .utf8)!)))
    } else {
        let missing = (0...255).filter { !present.contains(UInt8($0)) }
        let message = "missing \(missing.count) values"
        try output.emitCbor(CBOR.byteString([UInt8](message.data(using: .utf8)!)))
    }
    try output.close()
}

func handleReadFileInfo(input: InputPackage, output: BifaciOutputStream, peer: PeerInvoker) throws {
    // Payload is already file bytes (auto-converted by runtime from file-path)
    let payload = try input.collectAllBytes()
    let size = payload.count
    let hash = SHA256.hash(data: payload)
    let checksum = hash.compactMap { String(format: "%02x", $0) }.joined()

    let result: [String: Any] = [
        "size": size,
        "checksum": checksum
    ]

    let resultData = try JSONSerialization.data(withJSONObject: result)
    try output.write(resultData)
    try output.close()
}

// MARK: - Main

let manifestJSON = buildManifestJSON()
let runtime = PluginRuntime(manifestJSON: manifestJSON)

// Register all handlers with exact e-commerce semantic URNs
runtime.register(capUrn: "cap:in=\"media:bytes\";op=echo;out=\"media:bytes\"", handler: handleEcho)
runtime.register(capUrn: "cap:in=\"media:order-value;json;textable;form=map\";op=double;out=\"media:loyalty-points;integer;textable;numeric;form=scalar\"", handler: handleDouble)
runtime.register(capUrn: "cap:in=\"media:update-count;json;textable;form=map\";op=stream_chunks;out=\"media:order-updates;textable\"", handler: handleStreamChunks)
runtime.register(capUrn: "cap:in=\"media:product-image;bytes\";op=binary_echo;out=\"media:product-image;bytes\"", handler: handleBinaryEcho)
runtime.register(capUrn: "cap:in=\"media:payment-delay-ms;json;textable;form=map\";op=slow_response;out=\"media:payment-result;textable;form=scalar\"", handler: handleSlowResponse)
runtime.register(capUrn: "cap:in=\"media:report-size;json;textable;form=map\";op=generate_large;out=\"media:sales-report;bytes\"", handler: handleGenerateLarge)
runtime.register(capUrn: "cap:in=\"media:fulfillment-steps;json;textable;form=map\";op=with_status;out=\"media:fulfillment-status;textable;form=scalar\"", handler: handleWithStatus)
runtime.register(capUrn: "cap:in=\"media:payment-error;json;textable;form=map\";op=throw_error;out=\"media:void\"", handler: handleThrowError)
runtime.register(capUrn: "cap:in=\"media:customer-message;textable;form=scalar\";op=peer_echo;out=\"media:customer-message;textable;form=scalar\"", handler: handlePeerEcho)
runtime.register(capUrn: "cap:in=\"media:order-value;json;textable;form=map\";op=nested_call;out=\"media:final-price;integer;textable;numeric;form=scalar\"", handler: handleNestedCall)
runtime.register(capUrn: "cap:in=\"media:monitoring-duration-ms;json;textable;form=map\";op=heartbeat_stress;out=\"media:health-status;textable;form=scalar\"", handler: handleHeartbeatStress)
runtime.register(capUrn: "cap:in=\"media:order-batch-size;json;textable;form=map\";op=concurrent_stress;out=\"media:batch-result;textable;form=scalar\"", handler: handleConcurrentStress)
runtime.register(capUrn: "cap:in=\"media:void\";op=get_manifest;out=\"media:service-capabilities;json;textable;form=map\"", handler: handleGetManifest)
runtime.register(capUrn: "cap:in=\"media:uploaded-document;bytes\";op=process_large;out=\"media:document-info;json;textable;form=map\"", handler: handleProcessLarge)
runtime.register(capUrn: "cap:in=\"media:uploaded-document;bytes\";op=hash_incoming;out=\"media:document-hash;textable;form=scalar\"", handler: handleHashIncoming)
runtime.register(capUrn: "cap:in=\"media:package-data;bytes\";op=verify_binary;out=\"media:verification-status;textable;form=scalar\"", handler: handleVerifyBinary)
runtime.register(capUrn: "cap:in=\"media:invoice;file-path;textable;form=scalar\";op=read_file_info;out=\"media:invoice-metadata;json;textable;form=map\"", handler: handleReadFileInfo)

try! runtime.run()
