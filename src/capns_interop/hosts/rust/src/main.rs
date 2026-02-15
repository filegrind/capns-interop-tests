//! Rust test host binary for cross-language matrix tests.
//!
//! Reads JSON-line commands from stdin, manages a plugin subprocess
//! via PluginHostRuntime with a TestRouter, and writes JSON-line responses to stdout.

use base64::Engine;
use capns::bifaci::host_runtime::{AsyncHostError, PluginHostRuntime, PluginResponse, ResponseChunk};
use capns::CapArgumentValue;
use capns::bifaci::router::{ArcCapRouter, CapRouter, PeerRequestHandle};
use capns::bifaci::frame::{Frame, FrameType};
use crossbeam_channel::{bounded, Receiver, Sender};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::io::{self, BufRead, Write};
use std::sync::Arc;
use tokio::process::Command;

type HandlerFn = Arc<dyn Fn(Vec<u8>) -> Vec<u8> + Send + Sync>;

/// A simple test router that dispatches peer invoke requests to registered handlers.
struct TestRouter {
    handlers: HashMap<String, HandlerFn>,
}

impl TestRouter {
    fn new() -> Self {
        let mut handlers: HashMap<String, HandlerFn> = HashMap::new();

        // Echo handler — returns input as-is
        handlers.insert("echo".to_string(), Arc::new(|payload| payload));

        // Double handler — doubles a JSON number
        handlers.insert(
            "double".to_string(),
            Arc::new(|payload| {
                let data: serde_json::Value = serde_json::from_slice(&payload).unwrap();
                let value = data["value"].as_f64().unwrap();
                let result = (value as i64) * 2;
                serde_json::to_vec(&result).unwrap()
            }),
        );

        TestRouter { handlers }
    }

    fn extract_op(cap_urn: &str) -> Option<String> {
        // Try proper parsing first
        if let Ok(parsed) = capns::CapUrn::from_string(cap_urn) {
            return parsed.get_tag("op").map(|s| s.to_string());
        }
        // Simple extraction for URNs like "cap:in=media:;out=media:"
        for part in cap_urn.split(';') {
            let part = part.trim();
            if let Some(rest) = part.strip_prefix("op=") {
                return Some(rest.to_string());
            }
        }
        None
    }
}

impl CapRouter for TestRouter {
    fn begin_request(
        &self,
        cap_urn: &str,
        _req_id: &[u8; 16],
    ) -> Result<Box<dyn PeerRequestHandle>, AsyncHostError> {
        let op = Self::extract_op(cap_urn)
            .ok_or_else(|| AsyncHostError::NoHandler(cap_urn.to_string()))?;

        let handler = self
            .handlers
            .get(&op)
            .ok_or_else(|| AsyncHostError::NoHandler(cap_urn.to_string()))?;

        Ok(Box::new(TestRequestHandle::new(
            cap_urn.to_string(),
            Arc::clone(handler),
        )))
    }
}

/// Handle for a single peer request — accumulates frames, dispatches handler, sends response.
struct TestRequestHandle {
    _cap_urn: String,
    handler: HandlerFn,
    streams: Vec<(String, Vec<u8>)>, // (stream_id, accumulated_data)
    response_sender: Sender<Result<ResponseChunk, AsyncHostError>>,
    response_receiver: Receiver<Result<ResponseChunk, AsyncHostError>>,
}

impl TestRequestHandle {
    fn new(cap_urn: String, handler: HandlerFn) -> Self {
        let (tx, rx) = bounded(64);
        TestRequestHandle {
            _cap_urn: cap_urn,
            handler,
            streams: Vec::new(),
            response_sender: tx,
            response_receiver: rx,
        }
    }
}

impl PeerRequestHandle for TestRequestHandle {
    fn forward_frame(&mut self, frame: Frame) {
        match frame.frame_type {
            FrameType::StreamStart => {
                let stream_id = frame.stream_id.unwrap_or_default();
                self.streams.push((stream_id, Vec::new()));
            }
            FrameType::Chunk => {
                let stream_id = frame.stream_id.unwrap_or_default();
                if let Some(entry) = self.streams.iter_mut().find(|(id, _)| *id == stream_id) {
                    if let Some(payload) = frame.payload {
                        entry.1.extend_from_slice(&payload);
                    }
                }
            }
            FrameType::StreamEnd => {
                // No-op — stream tracking only
            }
            FrameType::End => {
                // Concatenate all stream data
                let mut payload = Vec::new();
                for (_, data) in &self.streams {
                    payload.extend_from_slice(data);
                }

                // Execute handler
                let result = (self.handler)(payload);

                // Send response chunk
                let tx = self.response_sender.clone();
                let _ = tx.send(Ok(ResponseChunk {
                    payload: result,
                    seq: 0,
                    offset: None,
                    len: None,
                    is_eof: true,
                }));
            }
            _ => {}
        }
    }

    fn response_receiver(&self) -> Receiver<Result<ResponseChunk, AsyncHostError>> {
        self.response_receiver.clone()
    }
}

struct RustTestHost {
    host: Option<PluginHostRuntime>,
    child: Option<tokio::process::Child>,
}

impl RustTestHost {
    fn new() -> Self {
        RustTestHost {
            host: None,
            child: None,
        }
    }

    async fn handle_spawn(&mut self, cmd: &Value) -> Value {
        let plugin_path = cmd["plugin_path"].as_str().unwrap_or("");

        let mut command = if plugin_path.ends_with(".py") {
            // Use PYTHON_EXECUTABLE env var for correct Python interpreter
            let python = env::var("PYTHON_EXECUTABLE").unwrap_or_else(|_| "python3".to_string());
            let mut c = Command::new(&python);
            c.arg(plugin_path);
            c
        } else {
            Command::new(plugin_path)
        };

        command
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        let mut child = match command.spawn() {
            Ok(c) => c,
            Err(e) => return json!({"ok": false, "error": format!("Failed to spawn: {e}")}),
        };

        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();

        // Drain stderr in background
        if let Some(stderr) = child.stderr.take() {
            tokio::spawn(async move {
                use tokio::io::AsyncReadExt;
                let mut stderr = stderr;
                let mut buf = vec![0u8; 8192];
                loop {
                    match stderr.read(&mut buf).await {
                        Ok(0) => break,
                        Ok(n) => {
                            let _ = io::stderr().write_all(&buf[..n]);
                        }
                        Err(_) => break,
                    }
                }
            });
        }

        // Create router with echo and double handlers
        let router: ArcCapRouter = Arc::new(TestRouter::new());

        // Create PluginHostRuntime with router
        let host = match PluginHostRuntime::new_with_router(stdin, stdout, router).await {
            Ok(h) => h,
            Err(e) => {
                let _ = child.kill().await;
                return json!({"ok": false, "error": format!("Handshake failed: {e}")});
            }
        };

        let manifest = host.plugin_manifest();
        let manifest_b64 = base64::engine::general_purpose::STANDARD.encode(manifest);

        self.host = Some(host);
        self.child = Some(child);

        json!({"ok": true, "manifest_b64": manifest_b64})
    }

    async fn handle_call(&self, cmd: &Value) -> Value {
        let host = match &self.host {
            Some(h) => h,
            None => return json!({"ok": false, "error": "No host"}),
        };

        let cap_urn = cmd["cap_urn"].as_str().unwrap_or("");

        let args_json = match cmd["arguments"].as_array() {
            Some(arr) => arr,
            None => return json!({"ok": false, "error": "Missing 'arguments' array"}),
        };

        let mut args = Vec::new();
        for arg_json in args_json {
            let media_urn = match arg_json["media_urn"].as_str() {
                Some(s) => s,
                None => return json!({"ok": false, "error": "Argument missing 'media_urn'"}),
            };
            let value_b64 = match arg_json["value_b64"].as_str() {
                Some(s) => s,
                None => return json!({"ok": false, "error": "Argument missing 'value_b64'"}),
            };
            let value = match base64::engine::general_purpose::STANDARD.decode(value_b64) {
                Ok(v) => v,
                Err(e) => return json!({"ok": false, "error": format!("Invalid base64 in argument: {e}")}),
            };
            args.push(CapArgumentValue::new(media_urn.to_string(), value));
        }

        let start = std::time::Instant::now();
        let response = match host.call_with_arguments(cap_urn, &args).await {
            Ok(r) => r,
            Err(e) => return json!({"ok": false, "error": format!("{e}")}),
        };
        let duration_ns = start.elapsed().as_nanos() as u64;

        // Decode CBOR values from response and return as base64
        match response {
            PluginResponse::Streaming(chunks) => {
                // Concatenate all chunk payloads
                let mut all_data = Vec::new();
                for chunk in &chunks {
                    all_data.extend_from_slice(&chunk.payload);
                }

                // Try CBOR decode
                match decode_cbor_values(&all_data) {
                    Ok(decoded) if decoded.len() == 1 => {
                        json!({
                            "ok": true,
                            "payload_b64": base64::engine::general_purpose::STANDARD.encode(&decoded[0]),
                            "is_streaming": false,
                            "duration_ns": duration_ns,
                        })
                    }
                    Ok(decoded) if decoded.len() > 1 => {
                        let chunks_b64: Vec<String> = decoded
                            .iter()
                            .map(|d| base64::engine::general_purpose::STANDARD.encode(d))
                            .collect();
                        json!({
                            "ok": true,
                            "is_streaming": true,
                            "chunks_b64": chunks_b64,
                            "duration_ns": duration_ns,
                        })
                    }
                    _ => {
                        // Raw chunks
                        let chunks_b64: Vec<String> = chunks
                            .iter()
                            .map(|c| base64::engine::general_purpose::STANDARD.encode(&c.payload))
                            .collect();
                        json!({
                            "ok": true,
                            "is_streaming": true,
                            "chunks_b64": chunks_b64,
                            "duration_ns": duration_ns,
                        })
                    }
                }
            }
            PluginResponse::Single(data) => {
                // Try CBOR decode
                match decode_cbor_values(&data) {
                    Ok(decoded) if decoded.len() == 1 => {
                        json!({
                            "ok": true,
                            "payload_b64": base64::engine::general_purpose::STANDARD.encode(&decoded[0]),
                            "is_streaming": false,
                            "duration_ns": duration_ns,
                        })
                    }
                    Ok(decoded) if decoded.len() > 1 => {
                        let chunks_b64: Vec<String> = decoded
                            .iter()
                            .map(|d| base64::engine::general_purpose::STANDARD.encode(d))
                            .collect();
                        json!({
                            "ok": true,
                            "is_streaming": true,
                            "chunks_b64": chunks_b64,
                            "duration_ns": duration_ns,
                        })
                    }
                    _ => {
                        json!({
                            "ok": true,
                            "payload_b64": base64::engine::general_purpose::STANDARD.encode(&data),
                            "is_streaming": false,
                            "duration_ns": duration_ns,
                        })
                    }
                }
            }
        }
    }

    async fn handle_throughput(&self, cmd: &Value) -> Value {
        let host = match &self.host {
            Some(h) => h,
            None => return json!({"ok": false, "error": "No host"}),
        };

        let payload_mb = cmd["payload_mb"].as_u64().unwrap_or(5) as usize;
        let payload_size = payload_mb * 1024 * 1024;
        let cap_urn = r#"cap:in="media:number;form=scalar";op=generate_large;out="media:bytes""#;

        let input_json = serde_json::to_vec(&json!({"value": payload_size})).unwrap();
        let args = vec![CapArgumentValue::new("media:json".to_string(), input_json)];

        let start = std::time::Instant::now();
        let response = match host.call_with_arguments(cap_urn, &args).await {
            Ok(r) => r,
            Err(e) => return json!({"ok": false, "error": format!("{e}")}),
        };
        let elapsed = start.elapsed().as_secs_f64();

        // CBOR-decode to get exact payload bytes
        let raw = match &response {
            PluginResponse::Streaming(chunks) => {
                let mut all = Vec::new();
                for c in chunks { all.extend_from_slice(&c.payload); }
                all
            }
            PluginResponse::Single(data) => data.clone(),
        };
        let decoded = match decode_cbor_values(&raw) {
            Ok(d) => d,
            Err(e) => return json!({"ok": false, "error": format!("CBOR decode: {e}")}),
        };
        let total_bytes: usize = decoded.iter().map(|v| v.len()).sum();

        if total_bytes != payload_size {
            return json!({
                "ok": false,
                "error": format!("Expected {} bytes, got {}", payload_size, total_bytes),
            });
        }

        let mb_per_sec = payload_mb as f64 / elapsed;

        json!({
            "ok": true,
            "payload_mb": payload_mb,
            "duration_s": (elapsed * 10000.0).round() / 10000.0,
            "mb_per_sec": (mb_per_sec * 100.0).round() / 100.0,
        })
    }

    async fn handle_send_heartbeat(&self) -> Value {
        if let Some(host) = &self.host {
            match host.send_heartbeat().await {
                Ok(()) => json!({"ok": true}),
                Err(e) => json!({"ok": false, "error": format!("{e}")}),
            }
        } else {
            json!({"ok": false, "error": "No host"})
        }
    }

    fn handle_get_manifest(&self) -> Value {
        if let Some(host) = &self.host {
            let manifest = host.plugin_manifest();
            let manifest_b64 = base64::engine::general_purpose::STANDARD.encode(manifest);
            json!({"ok": true, "manifest_b64": manifest_b64})
        } else {
            json!({"ok": false, "error": "No host"})
        }
    }

    async fn handle_shutdown(&mut self) -> Value {
        if let Some(host) = self.host.take() {
            let _ = host.shutdown().await;
        }
        if let Some(mut child) = self.child.take() {
            let _ = child.kill().await;
        }
        json!({"ok": true})
    }
}

/// Decode concatenated CBOR values from raw bytes.
fn decode_cbor_values(raw: &[u8]) -> Result<Vec<Vec<u8>>, String> {
    if raw.is_empty() {
        return Ok(vec![]);
    }

    let mut results = Vec::new();
    let mut cursor = std::io::Cursor::new(raw);

    loop {
        let pos_before = cursor.position() as usize;
        if pos_before >= raw.len() {
            break;
        }

        let value: ciborium::Value = match ciborium::from_reader(&mut cursor) {
            Ok(v) => v,
            Err(_) => {
                if results.is_empty() {
                    return Err("Not CBOR".to_string());
                }
                break;
            }
        };

        let bytes = match value {
            ciborium::Value::Bytes(b) => b,
            ciborium::Value::Text(s) => s.into_bytes(),
            other => {
                // Try JSON encoding for numbers, arrays, etc.
                let json_val = cbor_to_json(&other);
                serde_json::to_vec(&json_val).map_err(|e| e.to_string())?
            }
        };

        results.push(bytes);
    }

    Ok(results)
}

fn cbor_to_json(value: &ciborium::Value) -> serde_json::Value {
    match value {
        ciborium::Value::Integer(i) => {
            let n: i128 = (*i).into();
            json!(n as i64)
        }
        ciborium::Value::Float(f) => json!(f),
        ciborium::Value::Text(s) => json!(s),
        ciborium::Value::Bool(b) => json!(b),
        ciborium::Value::Null => serde_json::Value::Null,
        ciborium::Value::Bytes(b) => {
            json!(base64::engine::general_purpose::STANDARD.encode(b))
        }
        ciborium::Value::Array(arr) => {
            let items: Vec<serde_json::Value> = arr.iter().map(cbor_to_json).collect();
            json!(items)
        }
        ciborium::Value::Map(map) => {
            let mut obj = serde_json::Map::new();
            for (k, v) in map {
                if let ciborium::Value::Text(key) = k {
                    obj.insert(key.clone(), cbor_to_json(v));
                }
            }
            serde_json::Value::Object(obj)
        }
        _ => serde_json::Value::Null,
    }
}

#[tokio::main]
async fn main() {
    let mut host = RustTestHost::new();

    let stdin = io::stdin();
    let stdout = io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };

        if line.is_empty() {
            continue;
        }

        let cmd: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let resp = json!({"ok": false, "error": format!("Invalid JSON: {e}")});
                let mut out = stdout.lock();
                let _ = writeln!(out, "{}", resp);
                let _ = out.flush();
                continue;
            }
        };

        let cmd_type = cmd["cmd"].as_str().unwrap_or("");
        let response = match cmd_type {
            "spawn" => host.handle_spawn(&cmd).await,
            "call" => host.handle_call(&cmd).await,
            "throughput" => host.handle_throughput(&cmd).await,
            "send_heartbeat" => host.handle_send_heartbeat().await,
            "get_manifest" => host.handle_get_manifest(),
            "shutdown" => {
                let resp = host.handle_shutdown().await;
                let mut out = stdout.lock();
                let _ = writeln!(out, "{}", resp);
                let _ = out.flush();
                break;
            }
            _ => json!({"ok": false, "error": format!("Unknown command: {cmd_type}")}),
        };

        let mut out = stdout.lock();
        let _ = writeln!(out, "{}", response);
        let _ = out.flush();
    }
}
