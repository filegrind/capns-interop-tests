use capns::{
    ArgSource, Cap, CapArg, CapArgumentValue, CapManifest, CapOutput, CapUrnBuilder,
    FrameSender, PeerInvoker, PluginRuntime, RuntimeError, StreamEmitter, CapUrn,
};
use capns::cbor_frame::{Frame, FrameType, MessageId};
use crossbeam_channel::Receiver;
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

// Helper: Collect all frames, decode each CHUNK payload as CBOR, extract bytes
// PROTOCOL: Each CHUNK payload is a complete, independently decodable CBOR value
// For Value::Bytes, extract and concatenate the bytes
// For Value::Text, extract and concatenate as UTF-8 bytes
fn collect_payload(frames: Receiver<Frame>) -> ciborium::Value {
    let mut chunks = Vec::new();
    for frame in frames {
        match frame.frame_type {
            FrameType::Chunk => {
                if let Some(payload) = frame.payload {
                    // Each CHUNK payload MUST be valid CBOR - decode it
                    let value: ciborium::Value = ciborium::from_reader(&payload[..])
                        .expect("CHUNK payload must be valid CBOR");
                    chunks.push(value);
                }
            }
            FrameType::End => {
                break;
            }
            _ => {} // Ignore other frame types
        }
    }

    // Reconstruct value from chunks
    if chunks.is_empty() {
        ciborium::Value::Null
    } else if chunks.len() == 1 {
        chunks.into_iter().next().unwrap()
    } else {
        // Multiple chunks - concatenate bytes/text or collect as array
        match &chunks[0] {
            ciborium::Value::Bytes(_) => {
                let mut accumulated = Vec::new();
                for chunk in chunks {
                    if let ciborium::Value::Bytes(bytes) = chunk {
                        accumulated.extend_from_slice(&bytes);
                    }
                }
                ciborium::Value::Bytes(accumulated)
            }
            ciborium::Value::Text(_) => {
                let mut accumulated = String::new();
                for chunk in chunks {
                    if let ciborium::Value::Text(text) = chunk {
                        accumulated.push_str(&text);
                    }
                }
                ciborium::Value::Text(accumulated)
            }
            _ => {
                // For other types (Map, Array, Integer, etc.), collect as array
                ciborium::Value::Array(chunks)
            }
        }
    }
}

// Helper: Collect peer response as CBOR value
// Decodes each CHUNK individually, reconstructs the complete value
// For simple values (Bytes/Text/Integer), there's typically one chunk
// For arrays/maps, multiple chunks are combined
fn collect_peer_response(peer_frames: Receiver<Frame>) -> Result<ciborium::Value, RuntimeError> {
    let mut chunks = Vec::new();
    eprintln!("[collect_peer_response] Starting to collect frames");
    for frame in peer_frames {
        eprintln!("[collect_peer_response] Received frame: {:?}", frame.frame_type);
        match frame.frame_type {
            FrameType::Chunk => {
                if let Some(payload) = frame.payload {
                    eprintln!("[collect_peer_response] CHUNK payload length: {}", payload.len());
                    // Each CHUNK payload MUST be valid CBOR - decode it
                    let value: ciborium::Value = ciborium::from_reader(&payload[..])
                        .map_err(|e| RuntimeError::Deserialize(format!("Invalid CBOR in CHUNK: {}", e)))?;
                    eprintln!("[collect_peer_response] Decoded value: {:?}", value);
                    chunks.push(value);
                } else {
                    eprintln!("[collect_peer_response] CHUNK has no payload");
                }
            }
            FrameType::End => {
                eprintln!("[collect_peer_response] Received END, breaking");
                break;
            }
            FrameType::Err => {
                let code = frame.error_code().unwrap_or("UNKNOWN");
                let message = frame.error_message().unwrap_or("Unknown error");
                eprintln!("[collect_peer_response] Received ERR: [{}] {}", code, message);
                return Err(RuntimeError::PeerRequest(format!("[{}] {}", code, message)));
            }
            _ => {
                eprintln!("[collect_peer_response] Ignoring frame type: {:?}", frame.frame_type);
            }
        }
    }

    eprintln!("[collect_peer_response] Collected {} chunks", chunks.len());
    // Reconstruct value from chunks
    if chunks.is_empty() {
        eprintln!("[collect_peer_response] ERROR: No chunks received");
        return Err(RuntimeError::Deserialize("No chunks received".to_string()));
    } else if chunks.len() == 1 {
        // Single chunk - return as-is
        Ok(chunks.into_iter().next().unwrap())
    } else {
        // Multiple chunks - concatenate Bytes/Text, or collect Array elements
        let first = &chunks[0];
        match first {
            ciborium::Value::Bytes(_) => {
                // Concatenate all byte chunks
                let mut result = Vec::new();
                for chunk in chunks {
                    match chunk {
                        ciborium::Value::Bytes(bytes) => result.extend_from_slice(&bytes),
                        _ => return Err(RuntimeError::Deserialize("Mixed chunk types".to_string())),
                    }
                }
                Ok(ciborium::Value::Bytes(result))
            }
            ciborium::Value::Text(_) => {
                // Concatenate all text chunks
                let mut result = String::new();
                for chunk in chunks {
                    match chunk {
                        ciborium::Value::Text(text) => result.push_str(&text),
                        _ => return Err(RuntimeError::Deserialize("Mixed chunk types".to_string())),
                    }
                }
                Ok(ciborium::Value::Text(result))
            }
            _ => {
                // For other types (Integer, Array elements), collect as array
                Ok(ciborium::Value::Array(chunks))
            }
        }
    }
}

// Helper: Extract REQ frame and prepare for handler
// Returns (request_id, routing_id, payload_receiver)
fn extract_request_info(frames: Receiver<Frame>) -> Result<(MessageId, Option<MessageId>, Receiver<Frame>), RuntimeError> {
    let mut routing_id: Option<MessageId> = None;
    let mut request_id: Option<MessageId> = None;
    let mut payload_frames = Vec::new();

    for frame in frames {
        match frame.frame_type {
            FrameType::Req => {
                routing_id = frame.routing_id.clone();
                request_id = Some(frame.id.clone());
            }
            _ => {
                payload_frames.push(frame);
            }
        }
    }

    let request_id = request_id.ok_or_else(|| RuntimeError::Handler("Missing REQ frame".to_string()))?;

    // Create channel for payload frames
    let (tx, rx) = crossbeam_channel::unbounded();
    for f in payload_frames {
        let _ = tx.send(f);
    }
    drop(tx);

    Ok((request_id, routing_id, rx))
}

fn build_manifest() -> CapManifest {
    let caps = vec![
        Cap::new(
            CapUrn::from_string(capns::CAP_ECHO).unwrap(),
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

// Helper: Extract bytes from CBOR value
fn cbor_to_bytes(value: &ciborium::Value) -> Result<Vec<u8>, RuntimeError> {
    match value {
        ciborium::Value::Bytes(b) => Ok(b.clone()),
        ciborium::Value::Text(s) => Ok(s.as_bytes().to_vec()),
        _ => Err(RuntimeError::Handler(format!("Expected bytes or text, got {:?}", value))),
    }
}

// Helper: Extract JSON bytes from CBOR Map
fn cbor_map_to_json_bytes(value: &ciborium::Value) -> Result<Vec<u8>, RuntimeError> {
    match value {
        ciborium::Value::Bytes(bytes) => {
            // Already JSON bytes - return directly
            Ok(bytes.clone())
        }
        ciborium::Value::Text(text) => {
            // JSON as text - convert to bytes
            Ok(text.as_bytes().to_vec())
        }
        ciborium::Value::Map(_) => {
            // Serialize CBOR map to JSON
            let mut json_bytes = Vec::new();
            ciborium::into_writer(value, &mut json_bytes)
                .map_err(|e| RuntimeError::Serialize(format!("Failed to serialize CBOR: {}", e)))?;
            // Re-read as serde_json::Value, then write as JSON
            let json_val: serde_json::Value = ciborium::from_reader(&json_bytes[..])
                .map_err(|e| RuntimeError::Deserialize(format!("Failed to read CBOR as JSON: {}", e)))?;
            let result = serde_json::to_vec(&json_val)
                .map_err(|e| RuntimeError::Serialize(format!("Failed to serialize JSON: {}", e)))?;
            Ok(result)
        }
        _ => {
            Err(RuntimeError::Handler(format!("Expected CBOR Bytes, Text, or Map, got {:?}", value)))
        }
    }
}

// Handler: echo - returns input as-is
fn handle_echo(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let payload = cbor_to_bytes(&cbor_value)?;

    // Create stream emitter with routing_id
    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(payload))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: double - doubles a number
fn handle_double(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[double] Handler starting");
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    eprintln!("[double] Collected payload: {:?}", cbor_value);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let value = req.value.as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    eprintln!("[double] Parsed value: {}, doubling to: {}", value, value * 2);
    let result = value * 2;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    eprintln!("[double] Emitting result: {}", result);
    emitter.emit_cbor(&ciborium::Value::Integer(result.into()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    eprintln!("[double] Handler complete");
    Ok(())
}

// Handler: stream_chunks - emits N chunks
fn handle_stream_chunks(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let count = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    for i in 0..count {
        let chunk = format!("chunk-{}", i);
        emitter.emit_cbor(&ciborium::Value::Bytes(chunk.into_bytes()))?;
    }

    emitter.emit_cbor(&ciborium::Value::Bytes(b"done".to_vec()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: binary_echo - echoes binary data
fn handle_binary_echo(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let payload = cbor_to_bytes(&cbor_value)?;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(payload))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: slow_response - sleeps before responding
fn handle_slow_response(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let sleep_ms = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    thread::sleep(Duration::from_millis(sleep_ms));

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    let response = format!("slept-{}ms", sleep_ms);
    emitter.emit_cbor(&ciborium::Value::Bytes(response.into_bytes()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: generate_large - generates large payload
fn handle_generate_large(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
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

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(result))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: with_status - emits status messages during processing
fn handle_with_status(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let steps = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    for i in 0..steps {
        let status = format!("step {}", i);
        emitter.emit_log("processing", &status);
        thread::sleep(Duration::from_millis(10));
    }

    emitter.emit_cbor(&ciborium::Value::Bytes(b"completed".to_vec()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: throw_error - returns an error
fn handle_throw_error(
    frames: Receiver<Frame>,
    _sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (_request_id, _routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let message = req
        .value
        .as_str()
        .ok_or_else(|| RuntimeError::Handler("Expected string".to_string()))?;

    Err(RuntimeError::Handler(message.to_string()))
}

// Handler: peer_echo - calls host's echo via PeerInvoker
fn handle_peer_echo(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[peer_echo] Handler started, collecting payload");
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    eprintln!("[peer_echo] Payload collected: {:?}", cbor_value);
    let payload = cbor_to_bytes(&cbor_value)?;

    // Call host's echo capability
    let args = vec![CapArgumentValue::new("media:customer-message;textable;form=scalar", payload)];
    eprintln!("[peer_echo] Calling peer.invoke with cap:in=media:;out=media:");
    let peer_frames = peer.invoke("cap:in=media:;out=media:", &args)?;
    eprintln!("[peer_echo] peer.invoke returned channel, waiting for response");

    // Collect and decode peer response
    let cbor_value = collect_peer_response(peer_frames)?;
    eprintln!("[peer_echo] Got peer response: {:?}", cbor_value);

    // Create stream emitter and re-emit
    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&cbor_value)?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: nested_call - makes a peer call to double, then doubles again
fn handle_nested_call(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    eprintln!("[nested_call] Starting handler");
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    eprintln!("[nested_call] Collected payload: {:?}", cbor_value);

    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
        .map_err(|e| RuntimeError::Handler(format!("Invalid JSON: {}", e)))?;

    let value = req
        .value
        .as_u64()
        .ok_or_else(|| RuntimeError::Handler("Expected number".to_string()))?;

    eprintln!("[nested_call] Parsed value: {}", value);

    // Call host's double capability
    let input = serde_json::to_vec(&serde_json::json!({"value": value}))
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;
    let args = vec![CapArgumentValue::new("media:order-value;json;textable;form=map", input)];

    eprintln!("[nested_call] Calling peer.invoke(double)");
    let peer_frames = peer.invoke(r#"cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar""#, &args)?;

    // Collect and decode peer response
    eprintln!("[nested_call] Collecting peer response");
    let cbor_value = collect_peer_response(peer_frames)?;
    eprintln!("[nested_call] Peer response: {:?}", cbor_value);

    let host_result = match cbor_value {
        ciborium::Value::Integer(n) => {
            let val: i128 = n.into();
            eprintln!("[nested_call] Converted integer: {}", val);
            val as u64
        }
        _ => {
            return Err(RuntimeError::Deserialize(format!("Expected integer from double, got: {:?}", cbor_value)));
        }
    };

    // Double again locally
    let final_result = host_result * 2;
    eprintln!("[nested_call] Final result: {}", final_result);

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    eprintln!("[nested_call] Emitting result");
    emitter.emit_cbor(&ciborium::Value::Integer(final_result.into()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    eprintln!("[nested_call] Handler complete");
    Ok(())
}

// Handler: heartbeat_stress - simulates heavy processing
fn handle_heartbeat_stress(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
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

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    let response = format!("stressed-{}ms", duration_ms);
    emitter.emit_cbor(&ciborium::Value::Bytes(response.into_bytes()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: concurrent_stress - spawns multiple threads
fn handle_concurrent_stress(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let json_bytes = cbor_map_to_json_bytes(&cbor_value)?;
    let req: ValueRequest = serde_json::from_slice(&json_bytes)
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

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    let sum: usize = results.iter().sum();
    let response = format!("computed-{}", sum);
    emitter.emit_cbor(&ciborium::Value::Bytes(response.into_bytes()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: get_manifest - returns plugin manifest
fn handle_get_manifest(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let _payload = collect_payload(payload_rx);

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    let manifest = build_manifest();
    let manifest_json = serde_json::to_vec(&manifest)
        .map_err(|e| RuntimeError::Serialize(e.to_string()))?;
    emitter.emit_cbor(&ciborium::Value::Bytes(manifest_json))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: process_large - processes large binary data
fn handle_process_large(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let payload = cbor_to_bytes(&cbor_value)?;

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    let result = serde_json::to_vec(&serde_json::json!({
        "size": payload.len(),
        "checksum": hash_hex
    }))
    .map_err(|e| RuntimeError::Serialize(e.to_string()))?;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(result))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: hash_incoming - computes SHA256 hash
fn handle_hash_incoming(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let payload = cbor_to_bytes(&cbor_value)?;

    let mut hasher = Sha256::new();
    hasher.update(&payload);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(hash_hex.into_bytes()))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: verify_binary - checks if all 256 byte values are present
fn handle_verify_binary(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let payload = cbor_to_bytes(&cbor_value)?;

    let mut seen = HashSet::new();
    for &byte in &payload {
        seen.insert(byte);
    }

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    if seen.len() == 256 {
        emitter.emit_cbor(&ciborium::Value::Bytes(b"ok".to_vec()))?;
    } else {
        let mut missing: Vec<u8> = (0..=255u8).filter(|b| !seen.contains(b)).collect();
        missing.sort();
        let msg = format!("missing byte values: {:?}", missing);
        emitter.emit_cbor(&ciborium::Value::Bytes(msg.into_bytes()))?;
    }
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}

// Handler: read_file_info - reads file and returns metadata
fn handle_read_file_info(
    frames: Receiver<Frame>,
    sender: &dyn FrameSender,
    _peer: &dyn PeerInvoker,
) -> Result<(), RuntimeError> {
    let (request_id, routing_id, payload_rx) = extract_request_info(frames)?;
    let cbor_value = collect_payload(payload_rx);
    let file_content = cbor_to_bytes(&cbor_value)?;

    let mut hasher = Sha256::new();
    hasher.update(&file_content);
    let hash = hasher.finalize();
    let hash_hex = hex::encode(hash);

    let result = serde_json::to_vec(&serde_json::json!({
        "size": file_content.len(),
        "checksum": hash_hex
    }))
    .map_err(|e| RuntimeError::Serialize(e.to_string()))?;

    let stream_id = MessageId::new_uuid();
    let emitter = StreamEmitter::new(sender, stream_id.to_uuid_string().unwrap(), request_id.clone(), routing_id.clone(), 256 * 1024);

    emitter.emit_cbor(&ciborium::Value::Bytes(result))?;
    emitter.end_stream()?;

    let mut end_frame = Frame::end(request_id, None);
    end_frame.routing_id = routing_id;
    sender.send(&end_frame)?;

    Ok(())
}
