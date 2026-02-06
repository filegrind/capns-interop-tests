import Foundation
import CapNsCbor

// MARK: - Manifest Building

func buildManifest() -> [String: Any] {
    // URNs must match exactly what TEST_CAPS uses
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:string;textable;form=scalar\";op=echo;out=\"media:string;textable;form=scalar\"",
            "title": "Echo",
            "command": "echo"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=double;out=\"media:number;form=scalar\"",
            "title": "Double",
            "command": "double"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=stream_chunks;out=\"media:string;textable;streamable\"",
            "title": "Stream Chunks",
            "command": "stream_chunks"
        ],
        [
            "urn": "cap:in=\"media:bytes\";op=binary_echo;out=\"media:bytes\"",
            "title": "Binary Echo",
            "command": "binary_echo"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=slow_response;out=\"media:string;textable;form=scalar\"",
            "title": "Slow Response",
            "command": "slow_response"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=generate_large;out=\"media:bytes\"",
            "title": "Generate Large",
            "command": "generate_large"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=with_status;out=\"media:string;textable;form=scalar\"",
            "title": "With Status",
            "command": "with_status"
        ],
        [
            "urn": "cap:in=\"media:string;textable;form=scalar\";op=throw_error;out=\"media:void\"",
            "title": "Throw Error",
            "command": "throw_error"
        ],
        [
            "urn": "cap:in=\"media:string;textable;form=scalar\";op=peer_echo;out=\"media:string;textable;form=scalar\"",
            "title": "Peer Echo",
            "command": "peer_echo"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=nested_call;out=\"media:string;textable;form=scalar\"",
            "title": "Nested Call",
            "command": "nested_call"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=heartbeat_stress;out=\"media:string;textable;form=scalar\"",
            "title": "Heartbeat Stress",
            "command": "heartbeat_stress"
        ],
        [
            "urn": "cap:in=\"media:number;form=scalar\";op=concurrent_stress;out=\"media:string;textable;form=scalar\"",
            "title": "Concurrent Stress",
            "command": "concurrent_stress"
        ],
        [
            "urn": "cap:in=\"media:void\";op=get_manifest;out=\"media:json\"",
            "title": "Get Manifest",
            "command": "get_manifest"
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

// MARK: - Handlers

func handleEcho(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    return payload
}

func handleDouble(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let value = json["value"] as! Int
    let result = value * 2
    return try JSONSerialization.data(withJSONObject: result)
}

func handleStreamChunks(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let count = json["value"] as! Int

    for i in 0..<count {
        let chunk = "chunk-\(i)".data(using: .utf8)!
        emitter.emit(chunk: chunk)
    }

    return "done".data(using: .utf8)!
}

func handleBinaryEcho(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    return payload
}

func handleSlowResponse(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let sleepMs = json["value"] as! Int

    Thread.sleep(forTimeInterval: Double(sleepMs) / 1000.0)

    let response = "slept-\(sleepMs)ms"
    return response.data(using: .utf8)!
}

func handleGenerateLarge(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let size = json["value"] as! Int

    let pattern: [UInt8] = [65, 66, 67, 68, 69, 70, 71, 72] // "ABCDEFGH"
    var result = Data(capacity: size)
    for i in 0..<size {
        result.append(pattern[i % pattern.count])
    }

    return result
}

func handleWithStatus(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let steps = json["value"] as! Int

    for i in 0..<steps {
        let status = "step \(i)"
        emitter.emitStatus(operation: "processing", details: status)
        Thread.sleep(forTimeInterval: 0.01)
    }

    return "completed".data(using: .utf8)!
}

func handleThrowError(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let message = json["value"] as! String
    throw NSError(domain: "InteropTestError", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
}

func handlePeerEcho(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    // Call host's echo capability
    let arg = CborCapArgumentValue(mediaUrn: "media:bytes", value: payload)
    let chunks = try peer.invoke(capUrn: "cap:in=*;op=echo;out=*", arguments: [arg])

    var result = Data()
    for chunkResult in chunks {
        let chunk = try chunkResult.get()
        result.append(chunk)
    }

    return result
}

func handleNestedCall(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let value = json["value"] as! Int

    // Call host's double capability
    let inputData = try JSONSerialization.data(withJSONObject: ["value": value])
    let arg = CborCapArgumentValue(mediaUrn: "media:json", value: inputData)
    let chunks = try peer.invoke(capUrn: "cap:in=*;op=double;out=*", arguments: [arg])

    var resultBytes = Data()
    for chunkResult in chunks {
        let chunk = try chunkResult.get()
        resultBytes.append(chunk)
    }

    let hostResult = try JSONSerialization.jsonObject(with: resultBytes, options: .allowFragments) as! Int

    // Double again locally
    let finalResult = hostResult * 2

    return try JSONSerialization.data(withJSONObject: finalResult, options: .fragmentsAllowed)
}

func handleHeartbeatStress(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let durationMs = json["value"] as! Int

    // Sleep in small chunks to allow heartbeat processing
    let chunks = durationMs / 100
    for _ in 0..<chunks {
        Thread.sleep(forTimeInterval: 0.1)
    }
    Thread.sleep(forTimeInterval: Double(durationMs % 100) / 1000.0)

    let response = "stressed-\(durationMs)ms"
    return response.data(using: .utf8)!
}

func handleConcurrentStress(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let workUnits = json["value"] as! Int

    // Simulate work
    var sum: UInt64 = 0
    for i in 0..<(workUnits * 1000) {
        sum = sum &+ UInt64(i)
    }

    let response = "computed-\(sum)"
    return response.data(using: .utf8)!
}

func handleGetManifest(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let manifest = buildManifest()
    return try JSONSerialization.data(withJSONObject: manifest)
}

// MARK: - Main

let manifestJSON = buildManifestJSON()
let runtime = try! CborPluginRuntime(manifestJSON: manifestJSON)

// Register all handlers with exact URNs
runtime.register(capUrn: "cap:in=\"media:string;textable;form=scalar\";op=echo;out=\"media:string;textable;form=scalar\"", handler: handleEcho)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=double;out=\"media:number;form=scalar\"", handler: handleDouble)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=stream_chunks;out=\"media:string;textable;streamable\"", handler: handleStreamChunks)
runtime.register(capUrn: "cap:in=\"media:bytes\";op=binary_echo;out=\"media:bytes\"", handler: handleBinaryEcho)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=slow_response;out=\"media:string;textable;form=scalar\"", handler: handleSlowResponse)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=generate_large;out=\"media:bytes\"", handler: handleGenerateLarge)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=with_status;out=\"media:string;textable;form=scalar\"", handler: handleWithStatus)
runtime.register(capUrn: "cap:in=\"media:string;textable;form=scalar\";op=throw_error;out=\"media:void\"", handler: handleThrowError)
runtime.register(capUrn: "cap:in=\"media:string;textable;form=scalar\";op=peer_echo;out=\"media:string;textable;form=scalar\"", handler: handlePeerEcho)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=nested_call;out=\"media:string;textable;form=scalar\"", handler: handleNestedCall)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=heartbeat_stress;out=\"media:string;textable;form=scalar\"", handler: handleHeartbeatStress)
runtime.register(capUrn: "cap:in=\"media:number;form=scalar\";op=concurrent_stress;out=\"media:string;textable;form=scalar\"", handler: handleConcurrentStress)
runtime.register(capUrn: "cap:in=\"media:void\";op=get_manifest;out=\"media:json\"", handler: handleGetManifest)

try! runtime.run()
