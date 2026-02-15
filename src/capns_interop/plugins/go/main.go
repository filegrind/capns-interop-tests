package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	cborlib "github.com/fxamacker/cbor/v2"

	capns "github.com/filegrind/capns-go"
	"github.com/filegrind/capns-go/cbor"
)

// collectPayload reads all CHUNK frames, decodes each as CBOR, and returns the reconstructed value
// PROTOCOL: Each CHUNK payload is a complete, independently decodable CBOR value
// Returns the decoded CBOR value ([]byte, string, map[string]interface{}, []interface{}, etc.)
func collectPayload(frames <-chan cbor.Frame) interface{} {
	var chunks []interface{}
	for frame := range frames {
		switch frame.FrameType {
		case cbor.FrameTypeChunk:
			if frame.Payload != nil {
				// Each CHUNK payload MUST be valid CBOR - decode it
				var value interface{}
				if err := cborlib.Unmarshal(frame.Payload, &value); err != nil {
					panic(fmt.Sprintf("CHUNK payload must be valid CBOR: %v", err))
				}
				chunks = append(chunks, value)
			}
		case cbor.FrameTypeEnd:
			goto reconstruct
		}
	}

reconstruct:
	// Reconstruct value from chunks
	if len(chunks) == 0 {
		return nil
	} else if len(chunks) == 1 {
		return chunks[0]
	} else {
		// Multiple chunks - concatenate bytes/strings or collect as array
		switch chunks[0].(type) {
		case []byte:
			var accumulated []byte
			for _, chunk := range chunks {
				if b, ok := chunk.([]byte); ok {
					accumulated = append(accumulated, b...)
				}
			}
			return accumulated
		case string:
			var accumulated string
			for _, chunk := range chunks {
				if s, ok := chunk.(string); ok {
					accumulated += s
				}
			}
			return accumulated
		default:
			// For other types (map, int, etc.), return as array
			return chunks
		}
	}
}

// collectPeerResponse reads peer response frames, decodes each CHUNK as CBOR, and reconstructs value
// For simple values (bytes/string/int), there's typically one chunk
// For arrays/maps, multiple chunks are combined
func collectPeerResponse(peerFrames <-chan cbor.Frame) (interface{}, error) {
	var chunks []interface{}
	for frame := range peerFrames {
		switch frame.FrameType {
		case cbor.FrameTypeChunk:
			if frame.Payload != nil {
				// Each CHUNK payload MUST be valid CBOR - decode it
				var value interface{}
				if err := cborlib.Unmarshal(frame.Payload, &value); err != nil {
					return nil, fmt.Errorf("invalid CBOR in CHUNK: %w", err)
				}
				chunks = append(chunks, value)
			}
		case cbor.FrameTypeEnd:
			goto reconstruct
		case cbor.FrameTypeErr:
			code := frame.ErrorCode()
			message := frame.ErrorMessage()
			if code == "" {
				code = "UNKNOWN"
			}
			if message == "" {
				message = "Unknown error"
			}
			return nil, fmt.Errorf("[%s] %s", code, message)
		}
	}

reconstruct:
	// Reconstruct value from chunks
	if len(chunks) == 0 {
		return nil, fmt.Errorf("no chunks received")
	} else if len(chunks) == 1 {
		// Single chunk - return value as-is
		return chunks[0], nil
	} else {
		// Multiple chunks - concatenate bytes/strings, or collect array elements
		first := chunks[0]
		switch first.(type) {
		case []byte:
			// Concatenate all byte chunks
			var result []byte
			for _, chunk := range chunks {
				if bytes, ok := chunk.([]byte); ok {
					result = append(result, bytes...)
				} else {
					return nil, fmt.Errorf("mixed chunk types")
				}
			}
			return result, nil
		case string:
			// Concatenate all string chunks
			var result string
			for _, chunk := range chunks {
				if str, ok := chunk.(string); ok {
					result += str
				} else {
					return nil, fmt.Errorf("mixed chunk types")
				}
			}
			return result, nil
		default:
			// For other types (Integer, Array elements), collect as array
			return chunks, nil
		}
	}
}

// cborValueToBytes converts a CBOR value to bytes for handlers expecting bytes
func cborValueToBytes(value interface{}) ([]byte, error) {
	switch v := value.(type) {
	case []byte:
		return v, nil
	case string:
		return []byte(v), nil
	default:
		return nil, fmt.Errorf("expected []byte or string, got %T", v)
	}
}

// cborMapToJSON converts a CBOR map to JSON bytes
func cborMapToJSON(value interface{}) ([]byte, error) {
	// The value is already a Go map/interface{} from CBOR decoding
	// Just marshal it as JSON
	return json.Marshal(value)
}

func buildManifest() *capns.CapManifest {
	mustBuild := func(b *capns.CapUrnBuilder) *capns.CapUrn {
		urn, err := b.Build()
		if err != nil {
			panic(fmt.Sprintf("failed to build cap URN: %v", err))
		}
		return urn
	}

	caps := []capns.Cap{
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "echo").
				InSpec("media:bytes").
				OutSpec("media:bytes")),
			"Echo", "echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "double").
				InSpec("media:order-value;json;textable;form=map").
				OutSpec("media:loyalty-points;integer;textable;numeric;form=scalar")),
			"Double", "double",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "stream_chunks").
				InSpec("media:update-count;json;textable;form=map").
				OutSpec("media:order-updates;textable")),
			"Stream Chunks", "stream_chunks",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "binary_echo").
				InSpec("media:product-image;bytes").
				OutSpec("media:product-image;bytes")),
			"Binary Echo", "binary_echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "slow_response").
				InSpec("media:payment-delay-ms;json;textable;form=map").
				OutSpec("media:payment-result;textable;form=scalar")),
			"Slow Response", "slow_response",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "generate_large").
				InSpec("media:report-size;json;textable;form=map").
				OutSpec("media:sales-report;bytes")),
			"Generate Large", "generate_large",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "with_status").
				InSpec("media:fulfillment-steps;json;textable;form=map").
				OutSpec("media:fulfillment-status;textable;form=scalar")),
			"With Status", "with_status",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "throw_error").
				InSpec("media:payment-error;json;textable;form=map").
				OutSpec("media:void")),
			"Throw Error", "throw_error",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "peer_echo").
				InSpec("media:customer-message;textable;form=scalar").
				OutSpec("media:customer-message;textable;form=scalar")),
			"Peer Echo", "peer_echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "nested_call").
				InSpec("media:order-value;json;textable;form=map").
				OutSpec("media:final-price;integer;textable;numeric;form=scalar")),
			"Nested Call", "nested_call",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "heartbeat_stress").
				InSpec("media:monitoring-duration-ms;json;textable;form=map").
				OutSpec("media:health-status;textable;form=scalar")),
			"Heartbeat Stress", "heartbeat_stress",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "concurrent_stress").
				InSpec("media:order-batch-size;json;textable;form=map").
				OutSpec("media:batch-result;textable;form=scalar")),
			"Concurrent Stress", "concurrent_stress",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "get_manifest").
				InSpec("media:void").
				OutSpec("media:service-capabilities;json;textable;form=map")),
			"Get Manifest", "get_manifest",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "process_large").
				InSpec("media:uploaded-document;bytes").
				OutSpec("media:document-info;json;textable;form=map")),
			"Process Large", "process_large",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "hash_incoming").
				InSpec("media:uploaded-document;bytes").
				OutSpec("media:document-hash;textable;form=scalar")),
			"Hash Incoming", "hash_incoming",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "verify_binary").
				InSpec("media:package-data;bytes").
				OutSpec("media:verification-status;textable;form=scalar")),
			"Verify Binary", "verify_binary",
		),
		func() capns.Cap {
			stdin := "media:bytes"
			position := 0
			argDesc := "Path to invoice file to read"

			cap := capns.NewCap(
				mustBuild(capns.NewCapUrnBuilder().
					Tag("op", "read_file_info").
					InSpec("media:invoice;file-path;textable;form=scalar").
					OutSpec("media:invoice-metadata;json;textable;form=map")),
				"Read File Info", "read_file_info",
			)
			cap.Args = []capns.CapArg{
				{
					MediaUrn: "media:invoice;file-path;textable;form=scalar",
					Required: true,
					Sources: []capns.ArgSource{
						{Stdin: &stdin},
						{Position: &position},
					},
					ArgDescription: argDesc,
				},
			}
			cap.Output = &capns.CapOutput{
				MediaUrn:          "media:invoice-metadata;json;textable;form=map",
				OutputDescription: "Invoice file size and SHA256 checksum",
			}
			return *cap
		}(),
	}

	return capns.NewCapManifest(
		"InteropTestPlugin",
		"1.0.0",
		"Interoperability testing plugin (Go)",
		caps,
	)
}

// valueRequest is the JSON structure for number/string payloads
type valueRequest struct {
	Value json.RawMessage `json:"value"`
}

func parseValueRequest(cborValue interface{}) (valueRequest, error) {
	var req valueRequest

	// cborValue might be a map (CBOR Map) or []byte (CBOR Bytes with JSON)
	switch v := cborValue.(type) {
	case map[interface{}]interface{}:
		// CBOR Map - extract "value" field and marshal to JSON
		if val, ok := v["value"]; ok {
			// Marshal the value to JSON bytes
			valueBytes, err := json.Marshal(val)
			if err != nil {
				return req, fmt.Errorf("failed to marshal value: %w", err)
			}
			req.Value = json.RawMessage(valueBytes)
			return req, nil
		}
		return req, fmt.Errorf("missing 'value' field in map")
	case []byte:
		// JSON bytes - unmarshal
		if err := json.Unmarshal(v, &req); err != nil {
			return req, fmt.Errorf("invalid JSON: %w", err)
		}
		return req, nil
	case string:
		// JSON string - unmarshal
		if err := json.Unmarshal([]byte(v), &req); err != nil {
			return req, fmt.Errorf("invalid JSON: %w", err)
		}
		return req, nil
	default:
		return req, fmt.Errorf("expected map or []byte, got %T", cborValue)
	}
}

func handleEcho(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payloadBytes, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	emitter.EmitCbor(payloadBytes)
	return nil
}

func handleDouble(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var value uint64
	if err := json.Unmarshal(req.Value, &value); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	result := value * 2
	resultBytes, err := json.Marshal(result)
	if err != nil {
		return err
	}
	emitter.EmitCbor(resultBytes)
	return nil
}

func handleStreamChunks(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var count uint64
	if err := json.Unmarshal(req.Value, &count); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	for i := uint64(0); i < count; i++ {
		chunk := fmt.Sprintf("chunk-%d", i)
		emitter.EmitCbor([]byte(chunk))
	}

	emitter.EmitCbor([]byte("done"))
	return nil
}

func handleBinaryEcho(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payloadBytes, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	emitter.EmitCbor(payloadBytes)
	return nil
}

func handleSlowResponse(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var sleepMs uint64
	if err := json.Unmarshal(req.Value, &sleepMs); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	time.Sleep(time.Duration(sleepMs) * time.Millisecond)

	response := fmt.Sprintf("slept-%dms", sleepMs)
	emitter.EmitCbor([]byte(response))
	return nil
}

func handleGenerateLarge(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var size uint64
	if err := json.Unmarshal(req.Value, &size); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	pattern := []byte("ABCDEFGH")
	result := make([]byte, size)
	for i := uint64(0); i < size; i++ {
		result[i] = pattern[i%uint64(len(pattern))]
	}

	emitter.EmitCbor(result)
	return nil
}

func handleWithStatus(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var steps uint64
	if err := json.Unmarshal(req.Value, &steps); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	for i := uint64(0); i < steps; i++ {
		status := fmt.Sprintf("step %d", i)
		emitter.EmitLog("processing", status)
		time.Sleep(10 * time.Millisecond)
	}

	emitter.EmitCbor([]byte("completed"))
	return nil
}

func handleThrowError(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var message string
	if err := json.Unmarshal(req.Value, &message); err != nil {
		return fmt.Errorf("expected string: %w", err)
	}

	return fmt.Errorf("%s", message)
}

func handlePeerEcho(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payloadBytes, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	// Call host's echo capability with semantic URN
	args := []capns.CapArgumentValue{
		capns.NewCapArgumentValue("media:customer-message;textable;form=scalar", payloadBytes),
	}

	peerFrames, err := peer.Invoke("cap:in=media:;out=media:", args)
	if err != nil {
		return fmt.Errorf("peer invoke failed: %w", err)
	}

	// Collect and decode peer response
	cborValue, err2 := collectPeerResponse(peerFrames)
	if err2 != nil {
		return err2
	}

	// Re-emit (consumption → production)
	return emitter.EmitCbor(cborValue)
}

func handleNestedCall(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var value uint64
	if err := json.Unmarshal(req.Value, &value); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	// Call host's double capability
	input, err := json.Marshal(map[string]uint64{"value": value})
	if err != nil {
		return err
	}
	args := []capns.CapArgumentValue{
		capns.NewCapArgumentValue("media:order-value;json;textable;form=map", input),
	}

	peerFrames, err := peer.Invoke(`cap:in=*;op=double;out=*`, args)
	if err != nil {
		return fmt.Errorf("peer invoke failed: %w", err)
	}

	// Collect and decode peer response
	cborValue, err := collectPeerResponse(peerFrames)
	if err != nil {
		return err
	}

	// Extract integer from response
	var hostResult uint64
	switch v := cborValue.(type) {
	case uint64:
		hostResult = v
	case int64:
		hostResult = uint64(v)
	case int:
		hostResult = uint64(v)
	default:
		return fmt.Errorf("expected integer from double, got %T", v)
	}

	// Double again locally
	finalResult := hostResult * 2

	finalBytes, err := json.Marshal(finalResult)
	if err != nil {
		return err
	}

	emitter.EmitCbor(finalBytes)
	return nil
}

func handleHeartbeatStress(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var durationMs uint64
	if err := json.Unmarshal(req.Value, &durationMs); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	// Sleep in small chunks to allow heartbeat processing
	chunks := durationMs / 100
	for i := uint64(0); i < chunks; i++ {
		time.Sleep(100 * time.Millisecond)
	}
	time.Sleep(time.Duration(durationMs%100) * time.Millisecond)

	response := fmt.Sprintf("stressed-%dms", durationMs)
	emitter.EmitCbor([]byte(response))
	return nil
}

func handleConcurrentStress(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	payload := collectPayload(frames)
	req, err := parseValueRequest(payload)
	if err != nil {
		return err
	}

	var workUnits uint64
	if err := json.Unmarshal(req.Value, &workUnits); err != nil {
		return fmt.Errorf("expected number: %w", err)
	}

	// Simulate work
	var sum uint64
	for i := uint64(0); i < workUnits*1000; i++ {
		sum += i
	}

	response := fmt.Sprintf("computed-%d", sum)
	emitter.EmitCbor([]byte(response))
	return nil
}

func handleGetManifest(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	_ = collectPayload(frames) // Consume frames even if empty
	manifest := buildManifest()
	manifestBytes, err := json.Marshal(manifest)
	if err != nil {
		return err
	}

	emitter.EmitCbor(manifestBytes)
	return nil
}

func handleProcessLarge(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payload, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	// Calculate size and checksum
	size := len(payload)
	hash := sha256.Sum256(payload)
	checksum := hex.EncodeToString(hash[:])

	result := map[string]interface{}{
		"size":     size,
		"checksum": checksum,
	}

	resultBytes, err := json.Marshal(result)
	if err != nil {
		return err
	}

	emitter.EmitCbor(resultBytes)
	return nil
}

func handleHashIncoming(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payload, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	// Calculate SHA256 hash
	hash := sha256.Sum256(payload)
	hexHash := hex.EncodeToString(hash[:])

	emitter.EmitCbor([]byte(hexHash))
	return nil
}

func handleVerifyBinary(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payload, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	// Check if all 256 byte values (0x00-0xFF) are present
	present := make(map[byte]bool)
	for _, b := range payload {
		present[b] = true
	}

	var message string
	if len(present) != 256 {
		message = fmt.Sprintf("missing %d byte values", 256-len(present))
	} else {
		message = "ok"
	}

	emitter.EmitCbor([]byte(message))
	return nil
}

func handleReadFileInfo(frames <-chan cbor.Frame, emitter capns.StreamEmitter, peer capns.PeerInvoker) error {
	cborValue := collectPayload(frames)
	payload, err := cborValueToBytes(cborValue)
	if err != nil {
		return err
	}
	// Payload is already file bytes (auto-converted by runtime from file-path)
	size := len(payload)
	hash := sha256.Sum256(payload)
	checksum := hex.EncodeToString(hash[:])

	result := map[string]interface{}{
		"size":     size,
		"checksum": checksum,
	}

	resultBytes, err := json.Marshal(result)
	if err != nil {
		return err
	}

	emitter.EmitCbor(resultBytes)
	return nil
}

func main() {
	manifest := buildManifest()
	runtime, err := capns.NewPluginRuntimeWithManifest(manifest)
	if err != nil {
		panic(fmt.Sprintf("failed to create plugin runtime: %v", err))
	}

	// Register handlers with wildcard URNs (matching is done by PluginRuntime.FindHandler)
	runtime.Register(`cap:in="media:bytes";op=echo;out="media:bytes"`, handleEcho)
	runtime.Register(`cap:in=*;op=double;out=*`, handleDouble)
	runtime.Register(`cap:in=*;op=stream_chunks;out=*`, handleStreamChunks)
	runtime.Register(`cap:in=*;op=binary_echo;out=*`, handleBinaryEcho)
	runtime.Register(`cap:in=*;op=slow_response;out=*`, handleSlowResponse)
	runtime.Register(`cap:in=*;op=generate_large;out=*`, handleGenerateLarge)
	runtime.Register(`cap:in=*;op=with_status;out=*`, handleWithStatus)
	runtime.Register(`cap:in=*;op=throw_error;out=*`, handleThrowError)
	runtime.Register(`cap:in=*;op=peer_echo;out=*`, handlePeerEcho)
	runtime.Register(`cap:in=*;op=nested_call;out=*`, handleNestedCall)
	runtime.Register(`cap:in=*;op=heartbeat_stress;out=*`, handleHeartbeatStress)
	runtime.Register(`cap:in=*;op=concurrent_stress;out=*`, handleConcurrentStress)
	runtime.Register(`cap:in=*;op=get_manifest;out=*`, handleGetManifest)
	runtime.Register(`cap:in=*;op=process_large;out=*`, handleProcessLarge)
	runtime.Register(`cap:in=*;op=hash_incoming;out=*`, handleHashIncoming)
	runtime.Register(`cap:in=*;op=verify_binary;out=*`, handleVerifyBinary)
	runtime.Register(`cap:in=*;op=read_file_info;out=*`, handleReadFileInfo)

	if err := runtime.Run(); err != nil {
		panic(fmt.Sprintf("plugin runtime error: %v", err))
	}
}
