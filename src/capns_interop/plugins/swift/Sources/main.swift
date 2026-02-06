import Foundation
import CapNsCbor

// MARK: - Manifest Building

func buildManifest() -> [String: Any] {
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:string;form=scalar;textable\";op=echo;out=\"media:string;form=scalar;textable\"",
            "title": "Echo",
            "command": "echo"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=double;out=\"media:form=scalar;number\"",
            "title": "Double",
            "command": "double"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=stream_chunks;out=\"media:streamable;string;textable\"",
            "title": "Stream Chunks",
            "command": "stream_chunks"
        ],
        [
            "urn": "cap:in=\"media:bytes\";op=binary_echo;out=\"media:bytes\"",
            "title": "Binary Echo",
            "command": "binary_echo"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=slow_response;out=\"media:string;form=scalar;textable\"",
            "title": "Slow Response",
            "command": "slow_response"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=generate_large;out=\"media:bytes\"",
            "title": "Generate Large",
            "command": "generate_large"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=with_status;out=\"media:string;form=scalar;textable\"",
            "title": "With Status",
            "command": "with_status"
        ],
        [
            "urn": "cap:in=\"media:string;form=scalar;textable\";op=throw_error;out=\"media:void\"",
            "title": "Throw Error",
            "command": "throw_error"
        ],
        [
            "urn": "cap:in=\"media:string;form=scalar;textable\";op=peer_echo;out=\"media:string;form=scalar;textable\"",
            "title": "Peer Echo",
            "command": "peer_echo"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=nested_call;out=\"media:string;form=scalar;textable\"",
            "title": "Nested Call",
            "command": "nested_call"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=heartbeat_stress;out=\"media:string;form=scalar;textable\"",
            "title": "Heartbeat Stress",
            "command": "heartbeat_stress"
        ],
        [
            "urn": "cap:in=\"media:form=scalar;number\";op=concurrent_stress;out=\"media:string;form=scalar;textable\"",
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
        emitter.emitBytes(chunk)
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
        emitter.emitStatus("processing", details: status)
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
    let chunks = try peer.invoke(capUrn: "cap:in=*;op=echo;out=*", args: [("media:bytes", payload)])

    var result = Data()
    for chunk in chunks {
        result.append(chunk)
    }

    return result
}

func handleNestedCall(payload: Data, emitter: CborStreamEmitter, peer: CborPeerInvoker) throws -> Data {
    let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
    let value = json["value"] as! Int

    // Call host's double capability
    let inputData = try JSONSerialization.data(withJSONObject: ["value": value])
    let chunks = try peer.invoke(capUrn: "cap:in=*;op=double;out=*", args: [("media:json", inputData)])

    var resultBytes = Data()
    for chunk in chunks {
        resultBytes.append(chunk)
    }

    let hostResult = try JSONSerialization.jsonObject(with: resultBytes) as! Int

    // Double again locally
    let finalResult = hostResult * 2

    return try JSONSerialization.data(withJSONObject: finalResult)
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

let manifest = buildManifest()
let manifestJSON = try! JSONSerialization.data(withJSONObject: manifest)

let runtime = try! CborPluginRuntime(manifestJSON: manifestJSON)

// Register all handlers
runtime.register(capUrn: "cap:in=*;op=echo;out=*", handler: handleEcho)
runtime.register(capUrn: "cap:in=*;op=double;out=*", handler: handleDouble)
runtime.register(capUrn: "cap:in=*;op=stream_chunks;out=*", handler: handleStreamChunks)
runtime.register(capUrn: "cap:in=*;op=binary_echo;out=*", handler: handleBinaryEcho)
runtime.register(capUrn: "cap:in=*;op=slow_response;out=*", handler: handleSlowResponse)
runtime.register(capUrn: "cap:in=*;op=generate_large;out=*", handler: handleGenerateLarge)
runtime.register(capUrn: "cap:in=*;op=with_status;out=*", handler: handleWithStatus)
runtime.register(capUrn: "cap:in=*;op=throw_error;out=*", handler: handleThrowError)
runtime.register(capUrn: "cap:in=*;op=peer_echo;out=*", handler: handlePeerEcho)
runtime.register(capUrn: "cap:in=*;op=nested_call;out=*", handler: handleNestedCall)
runtime.register(capUrn: "cap:in=*;op=heartbeat_stress;out=*", handler: handleHeartbeatStress)
runtime.register(capUrn: "cap:in=*;op=concurrent_stress;out=*", handler: handleConcurrentStress)
runtime.register(capUrn: "cap:in=*;op=get_manifest;out=*", handler: handleGetManifest)

try! runtime.run()
