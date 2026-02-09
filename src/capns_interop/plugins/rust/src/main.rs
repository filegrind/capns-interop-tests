use capns::{
    ArgSource, Cap, CapArg, CapArgumentValue, CapManifest, CapOutput, CapUrnBuilder,
    PeerInvoker, PluginRuntime, RuntimeError, StreamEmitter,
};
use capns::plugin_runtime::StreamChunk;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::sync::mpsc::Receiver;
use std::thread;
use std::time::Duration;

// Request types
#[derive(Deserialize)]
struct ValueRequest {
    value: serde_json::Value,
}

// Helper: Collect all stream chunks into a single byte vector
fn collect_payload(stream_chunks: Receiver<StreamChunk>) -> Vec<u8> {
    let mut accumulated = Vec::new();
    for chunk in stream_chunks {
        accumulated.extend_from_slice(&chunk.data);
    }
    accumulated
}

fn build_manifest() -> CapManifest {
    let caps = vec![
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "echo")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Echo".to_string(),
            "echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "double")
                .in_spec("media:number;form=scalar")
                .out_spec("media:number;form=scalar")
                .build()
                .unwrap(),
            "Double".to_string(),
            "double".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "stream_chunks")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;streamable")
                .build()
                .unwrap(),
            "Stream Chunks".to_string(),
            "stream_chunks".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "binary_echo")
                .in_spec("media:bytes")
                .out_spec("media:bytes")
                .build()
                .unwrap(),
            "Binary Echo".to_string(),
            "binary_echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "slow_response")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Slow Response".to_string(),
            "slow_response".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "generate_large")
                .in_spec("media:number;form=scalar")
                .out_spec("media:bytes")
                .build()
                .unwrap(),
            "Generate Large".to_string(),
            "generate_large".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "with_status")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "With Status".to_string(),
            "with_status".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "throw_error")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:void")
                .build()
                .unwrap(),
            "Throw Error".to_string(),
            "throw_error".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "peer_echo")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Peer Echo".to_string(),
            "peer_echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "nested_call")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Nested Call".to_string(),
            "nested_call".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "heartbeat_stress")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Heartbeat Stress".to_string(),
            "heartbeat_stress".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "concurrent_stress")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Concurrent Stress".to_string(),
            "concurrent_stress".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "get_manifest")
                .in_spec("media:void")
                .out_spec("media:json")
                .build()
                .unwrap(),
            "Get Manifest".to_string(),
            "get_manifest".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "process_large")
                .in_spec("media:bytes")
                .out_spec("media:json")
                .build()
                .unwrap(),
            "Process Large".to_string(),
            "process_large".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "hash_incoming")
                .in_spec("media:bytes")
                .out_spec("media:string;textable;form=scalar")
                .build()
                .unwrap(),
            "Hash Incoming".to_string(),
            "hash_incoming".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "verify_binary")
                .in_spec("media:bytes")
                .out_spec("media:boolean")
                .build()
                .unwrap(),
            "Verify Binary".to_string(),
            "verify_binary".to_string(),
        ),
        {
            let mut cap = Cap::new(
                CapUrnBuilder::new()
                    .tag("op", "read_file_info")
                    .in_spec("media:file-path;textable;form=scalar")
                    .out_spec("media:json")
                    .build()
                    .unwrap(),
                "Read File Info".to_string(),
                "read_file_info".to_string(),
            );
            cap.args = vec![CapArg {
                media_urn: "media:file-path;textable;form=scalar".to_string(),
                required: true,
                sources: vec![ArgSource::Stdin {
                    stdin: "media:bytes".to_string(),
                }],
                arg_description: Some("Path to file".to_string()),
                default_value: None,
                metadata: None,
            }];
            cap.output = Some(CapOutput {
                media_urn: "media:json".to_string(),
                output_description: "File size and SHA256 checksum".to_string(),
                metadata: None,
            });
            cap
        },
    ];

    CapManifest::new(
        "InteropTestPlugin".to_string(),
        "1.0.0".to_string(),
        "Interoperability testing plugin (Rust)".to_string(),
        caps,
    )
}

fn main() -> Result<(), RuntimeError> {
    let manifest = build_manifest();
    let mut runtime = PluginRuntime::with_manifest(manifest);

    // Register handlers for all test capabilities
    runtime.register_raw(r#"cap:in=*;op=echo;out=*"#, handle_echo);
    runtime.register_raw(r#"cap:in=*;op=double;out=*"#, handle_double);
    runtime.register_raw(r#"cap:in=*;op=stream_chunks;out=*"#, handle_stream_chunks);
    runtime.register_raw(r#"cap:in=*;op=binary_echo;out=*"#, handle_binary_echo);
    runtime.register_raw(r#"cap:in=*;op=slow_response;out=*"#, handle_slow_response);
    runtime.register_raw(r#"cap:in=*;op=generate_large;out=*"#, handle_generate_large);
    runtime.register_raw(r#"cap:in=*;op=with_status;out=*"#, handle_with_status);
    runtime.register_raw(r#"cap:in=*;op=throw_error;out=*"#, handle_throw_error);
    runtime.register_raw(r#"cap:in=*;op=peer_echo;out=*"#, handle_peer_echo);
    runtime.register_raw(r#"cap:in=*;op=nested_call;out=*"#, handle_nested_call);
    runtime.register_raw(
        r#"cap:in=*;op=heartbeat_stress;out=*"#,
        handle_heartbeat_stress,
    );
    runtime.register_raw(
        r#"cap:in=*;op=concurrent_stress;out=*"#,
        handle_concurrent_stress,
    );
    runtime.register_raw(r#"cap:in=*;op=get_manifest;out=*"#, handle_get_manifest);
    runtime.register_raw(r#"cap:in=*;op=process_large;out=*"#, handle_process_large);
    runtime.register_raw(r#"cap:in=*;op=hash_incoming;out=*"#, handle_hash_incoming);
    runtime.register_raw(r#"cap:in=*;op=verify_binary;out=*"#, handle_verify_binary);
    runtime.register_raw(r#"cap:in=*;op=read_file_info;out=*"#, handle_read_file_info);

    runtime.run()
}

// Handler: echo - returns input as-is
fn handle_echo(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    emitter.emit_cbor(&ciborium::Value::Bytes(payload))?;
    Ok(())
}

// Handler: double - doubles a number
fn handle_double(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let value = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    let result = value * 2;
    emitter.emit(serde_json::json!(result))?;
    Ok(())
}

// Handler: stream_chunks - emits N chunks
fn handle_stream_chunks(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let count = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    for i in 0..count {
        let chunk = format!("chunk-{}", i);
        emitter.emit(serde_json::json!(chunk))?;
    }

    emitter.emit(serde_json::json!("done"))?;
    Ok(())
}

// Handler: binary_echo - echoes binary data
fn handle_binary_echo(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    emitter.emit_cbor(&ciborium::Value::Bytes(payload))?;
    Ok(())
}

// Handler: slow_response - sleeps before responding
fn handle_slow_response(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let sleep_ms = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    thread::sleep(Duration::from_millis(sleep_ms));

    let response = format!("slept-{}ms", sleep_ms);
    emitter.emit(serde_json::json!(response))?;
    Ok(())
}

// Handler: generate_large - generates large payload
fn handle_generate_large(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let size = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?
        as usize;

    // Generate repeating pattern
    let pattern = b"ABCDEFGH";
    let mut result = Vec::with_capacity(size);
    for i in 0..size {
        result.push(pattern[i % pattern.len()]);
    }

    emitter.emit_cbor(&ciborium::Value::Bytes(result))?;
    Ok(())
}

// Handler: with_status - emits status messages during processing
fn handle_with_status(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let steps = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    for i in 0..steps {
        let status = format!("step {}", i);
        emitter.emit_status("processing", &status);
        thread::sleep(Duration::from_millis(10));
    }

    emitter.emit_cbor(&ciborium::Value::Bytes(b"completed".to_vec()))?;
    Ok(())
}

// Handler: throw_error - returns an error
fn handle_throw_error(
    stream_chunks: Receiver<StreamChunk>,
    _emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let message = req
        .value
        .as_str()
        .ok_or_else(|| RuntimeError::Handler("Expected string".to_string()))?;

    Err(RuntimeError::Handler(message.to_string()))
}

// Handler: peer_echo - calls host's echo via PeerInvoker
fn handle_peer_echo(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);

    // Call host's echo capability
    let args = vec![CapArgumentValue::new("media:bytes", payload)];
    let rx = peer.invoke(r#"cap:in=*;op=echo;out=*"#, &args)?;

    // Collect response
    let mut result = Vec::new();
    for chunk_result in rx {
        let chunk = chunk_result?;
        result.extend(chunk);
    }

    emitter.emit_cbor(&ciborium::Value::Bytes(result))?;
    Ok(())
}

// Handler: nested_call - makes a peer call to double, then doubles again
fn handle_nested_call(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let value = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    // Call host's double capability
    let input = serde_json::to_vec(&serde_json::json!({"value": value}))
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;
    let args = vec![CapArgumentValue::new("media:json", input)];

    let rx = peer.invoke(r#"cap:in=*;op=double;out=*"#, &args)?;

    // Collect response
    let mut result_bytes = Vec::new();
    for chunk_result in rx {
        let chunk = chunk_result?;
        result_bytes.extend(chunk);
    }

    let host_result: u64 = serde_json::from_slice(&result_bytes)
        .map_err(|e| RuntimeError::Deserialize(e.to_string()))?;

    // Double again locally
    let final_result = host_result * 2;

    emitter.emit(serde_json::json!(final_result))?;
    Ok(())
}

// Handler: heartbeat_stress - simulates heavy processing
fn handle_heartbeat_stress(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let duration_ms = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    // Sleep in small chunks to allow heartbeat processing
    let chunks = duration_ms / 100;
    let remainder = duration_ms % 100;
    for _ in 0..chunks {
        thread::sleep(Duration::from_millis(100));
    }
    if remainder > 0 {
        thread::sleep(Duration::from_millis(remainder));
    }

    let response = format!("stressed-{}ms", duration_ms);
    emitter.emit_cbor(&ciborium::Value::Bytes(response.into_bytes()))?;
    Ok(())
}

// Handler: concurrent_stress - spawns multiple threads
fn handle_concurrent_stress(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);
    let req: ValueRequest = serde_json::from_slice(&payload)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let thread_count = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?
        as usize;

    let handles: Vec<_> = (0..thread_count)
        .map(|i| {
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(10));
                i
            })
        })
        .collect();

    let mut results = Vec::new();
    for handle in handles {
        results.push(handle.join().unwrap());
    }

    let sum: usize = results.iter().sum();
    let response = format!("computed-{}", sum);
    emitter.emit_cbor(&ciborium::Value::Bytes(response.into_bytes()))?;
    Ok(())
}

// Handler: get_manifest - returns plugin manifest
fn handle_get_manifest(
    _stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let manifest = build_manifest();
    let manifest_json = serde_json::to_value(&manifest)
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;
    emitter.emit(manifest_json)?;
    Ok(())
}

// Handler: process_large - processes large binary data
fn handle_process_large(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    emitter.emit(serde_json::json!({
        "size": payload.len(),
        "checksum": hash_hex
    }))?;
    Ok(())
}

// Handler: hash_incoming - computes SHA256 hash
fn handle_hash_incoming(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    emitter.emit_cbor(&ciborium::Value::Bytes(hash_hex.into_bytes()))?;
    Ok(())
}

// Handler: verify_binary - checks if all 256 byte values are present
fn handle_verify_binary(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_payload(stream_chunks);

    let mut seen = HashSet::new();
    for &byte in &payload {
        seen.insert(byte);
    }

    if seen.len() == 256 {
        emitter.emit_cbor(&ciborium::Value::Bytes(b"ok".to_vec()))?;
    } else {
        let mut missing: Vec<u8> = (0..=255u8).filter(|b| !seen.contains(b)).collect();
        missing.sort();
        let msg = format!("missing byte values: {:?}", missing);
        emitter.emit_cbor(&ciborium::Value::Bytes(msg.into_bytes()))?;
    }
    Ok(())
}

// Handler: read_file_info - reads file and returns metadata
fn handle_read_file_info(
    stream_chunks: Receiver<StreamChunk>,
    emitter: &dyn StreamEmitter,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    // File content is provided via stdin source auto-conversion
    let file_content = collect_payload(stream_chunks);

    let mut hasher = Sha256::new();
    hasher.update(&file_content);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    emitter.emit(serde_json::json!({
        "size": file_content.len(),
        "sha256": hash_hex
    }))?;
    Ok(())
}
