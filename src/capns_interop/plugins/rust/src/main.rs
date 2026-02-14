use capns::{
    ArgSource, Cap, CapArg, CapManifest, CapOutput, CapUrnBuilder,
    InputPackage, OutputStream, PeerInvoker, PluginRuntime, RuntimeError, CapUrn,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::thread;
use std::time::Duration;

// Request types
#[derive(Deserialize)]
struct ValueRequest {
    value: serde_json::Value,
}

// Helper: Collect all input as bytes, then parse as JSON.
// InputPackage.collect_all_bytes() already CBOR-decodes each CHUNK —
// the returned bytes are raw data (not CBOR-wrapped). Parse JSON directly.
fn collect_json_request(input: InputPackage) -> Result<ValueRequest, RuntimeError> {
    let bytes = input.collect_all_bytes()
        .map_err(|e| RuntimeError::Handler(format!("Stream error: {}", e)))?;
    serde_json::from_slice(&bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))
}

// Helper: Collect all input as raw bytes.
// InputPackage.collect_all_bytes() already CBOR-decodes each CHUNK —
// the returned bytes are raw data. No further decoding needed.
fn collect_binary(input: InputPackage) -> Result<Vec<u8>, RuntimeError> {
    input.collect_all_bytes()
        .map_err(|e| RuntimeError::Handler(format!("Stream error: {}", e)))
}

fn build_manifest() -> CapManifest {
    let caps = vec![
        Cap::new(
            CapUrn::from_string(capns::CAP_IDENTITY).unwrap(),
            "Echo".to_string(),
            "echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "double")
                .in_spec("media:order-value;json;textable;form=map")
                .out_spec("media:loyalty-points;integer;textable;numeric;form=scalar")
                .build()
                .unwrap(),
            "Double".to_string(),
            "double".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "stream_chunks")
                .in_spec("media:update-count;json;textable;form=map")
                .out_spec("media:order-updates;textable")
                .build()
                .unwrap(),
            "Stream Chunks".to_string(),
            "stream_chunks".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "binary_echo")
                .in_spec("media:product-image;bytes")
                .out_spec("media:product-image;bytes")
                .build()
                .unwrap(),
            "Binary Echo".to_string(),
            "binary_echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "slow_response")
                .in_spec("media:payment-delay-ms;json;textable;form=map")
                .out_spec("media:payment-result;textable;form=scalar")
                .build()
                .unwrap(),
            "Slow Response".to_string(),
            "slow_response".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "generate_large")
                .in_spec("media:report-size;json;textable;form=map")
                .out_spec("media:sales-report;bytes")
                .build()
                .unwrap(),
            "Generate Large".to_string(),
            "generate_large".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "with_status")
                .in_spec("media:fulfillment-steps;json;textable;form=map")
                .out_spec("media:fulfillment-status;textable;form=scalar")
                .build()
                .unwrap(),
            "With Status".to_string(),
            "with_status".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "throw_error")
                .in_spec("media:payment-error;json;textable;form=map")
                .out_spec("media:void")
                .build()
                .unwrap(),
            "Throw Error".to_string(),
            "throw_error".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "peer_echo")
                .in_spec("media:customer-message;textable;form=scalar")
                .out_spec("media:customer-message;textable;form=scalar")
                .build()
                .unwrap(),
            "Peer Echo".to_string(),
            "peer_echo".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "nested_call")
                .in_spec("media:order-value;json;textable;form=map")
                .out_spec("media:final-price;integer;textable;numeric;form=scalar")
                .build()
                .unwrap(),
            "Nested Call".to_string(),
            "nested_call".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "heartbeat_stress")
                .in_spec("media:monitoring-duration-ms;json;textable;form=map")
                .out_spec("media:health-status;textable;form=scalar")
                .build()
                .unwrap(),
            "Heartbeat Stress".to_string(),
            "heartbeat_stress".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "concurrent_stress")
                .in_spec("media:order-batch-size;json;textable;form=map")
                .out_spec("media:batch-result;textable;form=scalar")
                .build()
                .unwrap(),
            "Concurrent Stress".to_string(),
            "concurrent_stress".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "get_manifest")
                .in_spec("media:void")
                .out_spec("media:service-capabilities;json;textable;form=map")
                .build()
                .unwrap(),
            "Get Manifest".to_string(),
            "get_manifest".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "process_large")
                .in_spec("media:uploaded-document;bytes")
                .out_spec("media:document-info;json;textable;form=map")
                .build()
                .unwrap(),
            "Process Large".to_string(),
            "process_large".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "hash_incoming")
                .in_spec("media:uploaded-document;bytes")
                .out_spec("media:document-hash;textable;form=scalar")
                .build()
                .unwrap(),
            "Hash Incoming".to_string(),
            "hash_incoming".to_string(),
        ),
        Cap::new(
            CapUrnBuilder::new()
                .tag("op", "verify_binary")
                .in_spec("media:package-data;bytes")
                .out_spec("media:verification-status;textable;form=scalar")
                .build()
                .unwrap(),
            "Verify Binary".to_string(),
            "verify_binary".to_string(),
        ),
        {
            let mut cap = Cap::new(
                CapUrnBuilder::new()
                    .tag("op", "read_file_info")
                    .in_spec("media:invoice;file-path;textable;form=scalar")
                    .out_spec("media:invoice-metadata;json;textable;form=map")
                    .build()
                    .unwrap(),
                "Read File Info".to_string(),
                "read_file_info".to_string(),
            );
            cap.args = vec![CapArg {
                media_urn: "media:invoice;file-path;textable;form=scalar".to_string(),
                required: true,
                sources: vec![
                    ArgSource::Stdin {
                        stdin: "media:bytes".to_string(),
                    },
                    ArgSource::Position { position: 0 },
                ],
                arg_description: Some("Path to invoice file".to_string()),
                default_value: None,
                metadata: None,
            }];
            cap.output = Some(CapOutput {
                media_urn: "media:invoice-metadata;json;textable;form=map".to_string(),
                output_description: "Invoice file size and SHA256 checksum".to_string(),
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
    eprintln!("[PLUGIN MAIN] Starting");
    let manifest = build_manifest();
    eprintln!("[PLUGIN MAIN] Built manifest");
    let mut runtime = PluginRuntime::with_manifest(manifest);
    eprintln!("[PLUGIN MAIN] Created runtime");

    // Register handlers for all test capabilities
    runtime.register_raw("cap:in=media:;out=media:", handle_echo);
    runtime.register_raw(r#"cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar""#, handle_double);
    runtime.register_raw(r#"cap:in="media:update-count;json;textable;form=map";op=stream_chunks;out="media:order-updates;textable""#, handle_stream_chunks);
    runtime.register_raw(r#"cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes""#, handle_binary_echo);
    runtime.register_raw(r#"cap:in="media:payment-delay-ms;json;textable;form=map";op=slow_response;out="media:payment-result;textable;form=scalar""#, handle_slow_response);
    runtime.register_raw(r#"cap:in="media:report-size;json;textable;form=map";op=generate_large;out="media:sales-report;bytes""#, handle_generate_large);
    runtime.register_raw(r#"cap:in="media:fulfillment-steps;json;textable;form=map";op=with_status;out="media:fulfillment-status;textable;form=scalar""#, handle_with_status);
    runtime.register_raw(r#"cap:in="media:payment-error;json;textable;form=map";op=throw_error;out=media:void"#, handle_throw_error);
    runtime.register_raw(r#"cap:in="media:customer-message;textable;form=scalar";op=peer_echo;out="media:customer-message;textable;form=scalar""#, handle_peer_echo);
    runtime.register_raw(r#"cap:in="media:order-value;json;textable;form=map";op=nested_call;out="media:final-price;integer;textable;numeric;form=scalar""#, handle_nested_call);
    runtime.register_raw(
        r#"cap:in="media:monitoring-duration-ms;json;textable;form=map";op=heartbeat_stress;out="media:health-status;textable;form=scalar""#,
        handle_heartbeat_stress,
    );
    runtime.register_raw(
        r#"cap:in="media:order-batch-size;json;textable;form=map";op=concurrent_stress;out="media:batch-result;textable;form=scalar""#,
        handle_concurrent_stress,
    );
    runtime.register_raw(r#"cap:in=media:void;op=get_manifest;out="media:service-capabilities;json;textable;form=map""#, handle_get_manifest);
    runtime.register_raw(r#"cap:in="media:uploaded-document;bytes";op=process_large;out="media:document-info;json;textable;form=map""#, handle_process_large);
    runtime.register_raw(r#"cap:in="media:uploaded-document;bytes";op=hash_incoming;out="media:document-hash;textable;form=scalar""#, handle_hash_incoming);
    runtime.register_raw(r#"cap:in="media:package-data;bytes";op=verify_binary;out="media:verification-status;textable;form=scalar""#, handle_verify_binary);
    runtime.register_raw(r#"cap:in="media:invoice;file-path;textable;form=scalar";op=read_file_info;out="media:invoice-metadata;json;textable;form=map""#, handle_read_file_info);

    eprintln!("[PLUGIN MAIN] Calling runtime.run()");
    let result = runtime.run();
    eprintln!("[PLUGIN MAIN] runtime.run() returned: {:?}", result);
    result
}

// === STREAMING HANDLERS (no accumulation — handle infinite streams) ===

// Handler: echo — identity cap, pure passthrough
fn handle_echo(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    for stream in input {
        for chunk in stream? {
            output.emit_cbor(&chunk?)?;
        }
    }
    Ok(())
}

// Handler: binary_echo — same pattern (binary passthrough)
fn handle_binary_echo(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    for stream in input {
        for chunk in stream? {
            output.emit_cbor(&chunk?)?;
        }
    }
    Ok(())
}

// Handler: peer_echo — forward input to peer, stream response back
fn handle_peer_echo(
    input: InputPackage,
    output: &OutputStream,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[peer_echo] Handler started");
    let payload = collect_binary(input)?;
    eprintln!("[peer_echo] Collected {} bytes, calling peer", payload.len());

    let response = peer.call_with_bytes(
        "cap:in=media:;out=media:",
        &[("media:customer-message;textable;form=scalar", &payload)],
    ).map_err(|e| {
        eprintln!("[peer_echo] Peer call failed: {}", e);
        e
    })?;

    eprintln!("[peer_echo] Got peer response stream");
    let value = response.collect_value()
        .map_err(|e| RuntimeError::Handler(format!("Peer response error: {}", e)))?;
    eprintln!("[peer_echo] Got peer response value: {:?}", value);

    output.emit_cbor(&value)?;
    Ok(())
}

// === ACCUMULATING HANDLERS (need complete data for business logic) ===

// Handler: double — must parse JSON to extract number
fn handle_double(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[double] Handler starting");
    let req = collect_json_request(input)?;
    let value = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    eprintln!("[double] Parsed value: {}, doubling to: {}", value, value * 2);
    let result = value * 2;

    output.emit_cbor(&ciborium::Value::Integer(result.into()))?;
    eprintln!("[double] Handler complete");
    Ok(())
}

// Handler: stream_chunks — must parse JSON to get count, then streams output
fn handle_stream_chunks(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let count = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    for i in 0..count {
        let chunk = format!("chunk-{}", i);
        output.write(chunk.as_bytes())?;
    }
    output.write(b"done")?;
    Ok(())
}

// Handler: slow_response — sleeps before responding
fn handle_slow_response(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let sleep_ms = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    thread::sleep(Duration::from_millis(sleep_ms));

    let response = format!("slept-{}ms", sleep_ms);
    output.write(response.as_bytes())?;
    Ok(())
}

// Handler: generate_large — generates large payload
fn handle_generate_large(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let size = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))? as usize;

    let pattern = b"ABCDEFGH";
    let mut result = Vec::with_capacity(size);
    for i in 0..size {
        result.push(pattern[i % pattern.len()]);
    }

    output.emit_cbor(&ciborium::Value::Bytes(result))?;
    Ok(())
}

// Handler: with_status — emits status messages during processing
fn handle_with_status(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let steps = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    for i in 0..steps {
        let status = format!("step {}", i);
        output.log("processing", &status);
        thread::sleep(Duration::from_millis(10));
    }

    output.write(b"completed")?;
    Ok(())
}

// Handler: throw_error — returns an error
fn handle_throw_error(
    input: InputPackage,
    _output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let message = req.value.as_str()
        .ok_or_else(|| RuntimeError::Handler("Expected string".to_string()))?;
    Err(RuntimeError::Handler(message.to_string()))
}

// Handler: nested_call — makes a peer call to double, then doubles again
fn handle_nested_call(
    input: InputPackage,
    output: &OutputStream,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[nested_call] Starting handler");
    let req = collect_json_request(input)?;
    let value = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    eprintln!("[nested_call] Parsed value: {}", value);

    // Call host's double capability
    let double_arg = serde_json::to_vec(&serde_json::json!({"value": value}))
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;

    eprintln!("[nested_call] Calling peer double");
    let response = peer.call_with_bytes(
        r#"cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar""#,
        &[("media:order-value;json;textable;form=map", &double_arg)],
    )?;

    let cbor_value = response.collect_value()
        .map_err(|e| RuntimeError::Handler(format!("Peer response error: {}", e)))?;
    eprintln!("[nested_call] Peer response: {:?}", cbor_value);

    let host_result = match cbor_value {
        ciborium::Value::Integer(n) => {
            let val: i128 = n.into();
            val as u64
        }
        _ => return Err(RuntimeError::Deserialize(format!(
            "Expected integer from double, got: {:?}", cbor_value
        ))),
    };

    let final_result = host_result * 2;
    eprintln!("[nested_call] Final result: {}", final_result);

    output.emit_cbor(&ciborium::Value::Integer(final_result.into()))?;
    Ok(())
}

// Handler: heartbeat_stress — simulates heavy processing
fn handle_heartbeat_stress(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let duration_ms = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    let chunks = duration_ms / 100;
    let remainder = duration_ms % 100;
    for _ in 0..chunks {
        thread::sleep(Duration::from_millis(100));
    }
    if remainder > 0 {
        thread::sleep(Duration::from_millis(remainder));
    }

    let response = format!("stressed-{}ms", duration_ms);
    output.write(response.as_bytes())?;
    Ok(())
}

// Handler: concurrent_stress — spawns multiple threads
fn handle_concurrent_stress(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let req = collect_json_request(input)?;
    let thread_count = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))? as usize;

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
    output.write(response.as_bytes())?;
    Ok(())
}

// Handler: get_manifest — returns plugin manifest
fn handle_get_manifest(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    // Consume input (even if void)
    let _ = input.collect_all_bytes();

    let manifest = build_manifest();
    let manifest_json = serde_json::to_vec(&manifest)
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;
    output.emit_cbor(&ciborium::Value::Bytes(manifest_json))?;
    Ok(())
}

// Handler: process_large — processes large binary data
fn handle_process_large(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_binary(input)?;

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    let result = serde_json::to_vec(&serde_json::json!({
        "size": payload.len(),
        "checksum": hash_hex
    }))
    .map_err(|e| RuntimeError::Serialize(e.to_string()))?;

    output.emit_cbor(&ciborium::Value::Bytes(result))?;
    Ok(())
}

// Handler: hash_incoming — computes SHA256 hash
fn handle_hash_incoming(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_binary(input)?;

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    output.write(hash_hex.as_bytes())?;
    Ok(())
}

// Handler: verify_binary — checks if all 256 byte values are present
fn handle_verify_binary(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let payload = collect_binary(input)?;

    let mut seen = HashSet::new();
    for &byte in &payload {
        seen.insert(byte);
    }

    if seen.len() == 256 {
        output.write(b"ok")?;
    } else {
        let mut missing: Vec<u8> = (0..=255u8).filter(|b| !seen.contains(b)).collect();
        missing.sort();
        let msg = format!("missing byte values: {:?}", missing);
        output.write(msg.as_bytes())?;
    }
    Ok(())
}

// Handler: read_file_info — reads file and returns metadata
fn handle_read_file_info(
    input: InputPackage,
    output: &OutputStream,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let file_content = collect_binary(input)?;

    let mut hasher = Sha256::new();
    hasher.update(&file_content);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    let result = serde_json::to_vec(&serde_json::json!({
        "size": file_content.len(),
        "checksum": hash_hex
    }))
    .map_err(|e| RuntimeError::Serialize(e.to_string()))?;

    output.emit_cbor(&ciborium::Value::Bytes(result))?;
    Ok(())
}
