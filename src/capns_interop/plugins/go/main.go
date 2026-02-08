package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	capns "github.com/filegrind/cap-sdk-go"
)

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
				InSpec("media:string;textable;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Echo", "echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "double").
				InSpec("media:number;form=scalar").
				OutSpec("media:number;form=scalar")),
			"Double", "double",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "stream_chunks").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;streamable")),
			"Stream Chunks", "stream_chunks",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "binary_echo").
				InSpec("media:bytes").
				OutSpec("media:bytes")),
			"Binary Echo", "binary_echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "slow_response").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Slow Response", "slow_response",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "generate_large").
				InSpec("media:number;form=scalar").
				OutSpec("media:bytes")),
			"Generate Large", "generate_large",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "with_status").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"With Status", "with_status",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "throw_error").
				InSpec("media:string;textable;form=scalar").
				OutSpec("media:void")),
			"Throw Error", "throw_error",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "peer_echo").
				InSpec("media:string;textable;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Peer Echo", "peer_echo",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "nested_call").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Nested Call", "nested_call",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "heartbeat_stress").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Heartbeat Stress", "heartbeat_stress",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "concurrent_stress").
				InSpec("media:number;form=scalar").
				OutSpec("media:string;textable;form=scalar")),
			"Concurrent Stress", "concurrent_stress",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "get_manifest").
				InSpec("media:void").
				OutSpec("media:json")),
			"Get Manifest", "get_manifest",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "process_large").
				InSpec("media:bytes").
				OutSpec("media:json")),
			"Process Large", "process_large",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "hash_incoming").
				InSpec("media:bytes").
				OutSpec("media:string;textable;form=scalar")),
			"Hash Incoming", "hash_incoming",
		),
		*capns.NewCap(
			mustBuild(capns.NewCapUrnBuilder().
				Tag("op", "verify_binary").
				InSpec("media:bytes").
				OutSpec("media:string;textable;form=scalar")),
			"Verify Binary", "verify_binary",
		),
		func() capns.Cap {
			stdin := "media:bytes"
			position := 0
			argDesc := "Path to file to read"

			cap := capns.NewCap(
				mustBuild(capns.NewCapUrnBuilder().
					Tag("op", "read_file_info").
					InSpec("media:bytes").
					OutSpec("media:json")),
				"Read File Info", "read_file_info",
			)
			cap.Args = []capns.CapArg{
				{
					MediaUrn: "media:file-path;textable;form=scalar",
					Required: true,
					Sources: []capns.ArgSource{
						{Stdin: &stdin},
						{Position: &position},
					},
					ArgDescription: argDesc,
				},
			}
			cap.Output = &capns.CapOutput{
				MediaUrn:          "media:json",
				OutputDescription: "File size and SHA256 checksum",
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

func parseValueRequest(payload []byte) (valueRequest, error) {
	var req valueRequest
	if err := json.Unmarshal(payload, &req); err != nil {
		return req, fmt.Errorf("invalid JSON: %w", err)
	}
	return req, nil
}

func handleEcho(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	return payload, nil
}

func handleDouble(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var value uint64
	if err := json.Unmarshal(req.Value, &value); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	result := value * 2
	return json.Marshal(result)
}

func handleStreamChunks(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var count uint64
	if err := json.Unmarshal(req.Value, &count); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	for i := uint64(0); i < count; i++ {
		chunk := fmt.Sprintf("chunk-%d", i)
		emitter.Emit([]byte(chunk))
	}

	return []byte("done"), nil
}

func handleBinaryEcho(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	return payload, nil
}

func handleSlowResponse(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var sleepMs uint64
	if err := json.Unmarshal(req.Value, &sleepMs); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	time.Sleep(time.Duration(sleepMs) * time.Millisecond)

	response := fmt.Sprintf("slept-%dms", sleepMs)
	return []byte(response), nil
}

func handleGenerateLarge(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var size uint64
	if err := json.Unmarshal(req.Value, &size); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	pattern := []byte("ABCDEFGH")
	result := make([]byte, size)
	for i := uint64(0); i < size; i++ {
		result[i] = pattern[i%uint64(len(pattern))]
	}

	return result, nil
}

func handleWithStatus(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var steps uint64
	if err := json.Unmarshal(req.Value, &steps); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	for i := uint64(0); i < steps; i++ {
		status := fmt.Sprintf("step %d", i)
		emitter.EmitStatus("processing", status)
		time.Sleep(10 * time.Millisecond)
	}

	return []byte("completed"), nil
}

func handleThrowError(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var message string
	if err := json.Unmarshal(req.Value, &message); err != nil {
		return nil, fmt.Errorf("expected string: %w", err)
	}

	return nil, fmt.Errorf("%s", message)
}

func handlePeerEcho(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	// Call host's echo capability
	args := []capns.CapArgumentValue{
		capns.NewCapArgumentValue("media:bytes", payload),
	}

	rx, err := peer.Invoke(`cap:in=*;op=echo;out=*`, args)
	if err != nil {
		return nil, fmt.Errorf("peer invoke failed: %w", err)
	}

	// Collect response
	var result []byte
	for chunk := range rx {
		if chunk.Error != nil {
			return nil, chunk.Error
		}
		result = append(result, chunk.Data...)
	}

	return result, nil
}

func handleNestedCall(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var value uint64
	if err := json.Unmarshal(req.Value, &value); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	// Call host's double capability
	input, err := json.Marshal(map[string]uint64{"value": value})
	if err != nil {
		return nil, err
	}
	args := []capns.CapArgumentValue{
		capns.NewCapArgumentValue("media:json", input),
	}

	rx, err := peer.Invoke(`cap:in=*;op=double;out=*`, args)
	if err != nil {
		return nil, fmt.Errorf("peer invoke failed: %w", err)
	}

	// Collect response
	var resultBytes []byte
	for chunk := range rx {
		if chunk.Error != nil {
			return nil, chunk.Error
		}
		resultBytes = append(resultBytes, chunk.Data...)
	}

	var hostResult uint64
	if err := json.Unmarshal(resultBytes, &hostResult); err != nil {
		return nil, fmt.Errorf("failed to parse host result: %w", err)
	}

	// Double again locally
	finalResult := hostResult * 2

	return json.Marshal(finalResult)
}

func handleHeartbeatStress(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var durationMs uint64
	if err := json.Unmarshal(req.Value, &durationMs); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	// Sleep in small chunks to allow heartbeat processing
	chunks := durationMs / 100
	for i := uint64(0); i < chunks; i++ {
		time.Sleep(100 * time.Millisecond)
	}
	time.Sleep(time.Duration(durationMs%100) * time.Millisecond)

	response := fmt.Sprintf("stressed-%dms", durationMs)
	return []byte(response), nil
}

func handleConcurrentStress(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	req, err := parseValueRequest(payload)
	if err != nil {
		return nil, err
	}

	var workUnits uint64
	if err := json.Unmarshal(req.Value, &workUnits); err != nil {
		return nil, fmt.Errorf("expected number: %w", err)
	}

	// Simulate work
	var sum uint64
	for i := uint64(0); i < workUnits*1000; i++ {
		sum += i
	}

	response := fmt.Sprintf("computed-%d", sum)
	return []byte(response), nil
}

func handleGetManifest(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	manifest := buildManifest()
	return json.Marshal(manifest)
}

func handleProcessLarge(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	// Calculate size and checksum
	size := len(payload)
	hash := sha256.Sum256(payload)
	checksum := hex.EncodeToString(hash[:])

	result := map[string]interface{}{
		"size":     size,
		"checksum": checksum,
	}

	return json.Marshal(result)
}

func handleHashIncoming(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	// Calculate SHA256 hash
	hash := sha256.Sum256(payload)
	hexHash := hex.EncodeToString(hash[:])

	return []byte(hexHash), nil
}

func handleVerifyBinary(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	// Check if all 256 byte values (0x00-0xFF) are present
	present := make(map[byte]bool)
	for _, b := range payload {
		present[b] = true
	}

	if len(present) != 256 {
		message := fmt.Sprintf("missing %d byte values", 256-len(present))
		return []byte(message), nil
	}

	return []byte("ok"), nil
}

func handleReadFileInfo(payload []byte, emitter capns.StreamEmitter, peer capns.PeerInvoker) ([]byte, error) {
	// Payload is already file bytes (auto-converted by runtime from file-path)
	size := len(payload)
	hash := sha256.Sum256(payload)
	checksum := hex.EncodeToString(hash[:])

	result := map[string]interface{}{
		"size":     size,
		"checksum": checksum,
	}

	return json.Marshal(result)
}

func main() {
	manifest := buildManifest()
	runtime, err := capns.NewPluginRuntimeWithManifest(manifest)
	if err != nil {
		panic(fmt.Sprintf("failed to create plugin runtime: %v", err))
	}

	// Register handlers with wildcard URNs (matching is done by PluginRuntime.FindHandler)
	runtime.Register(`cap:in=*;op=echo;out=*`, handleEcho)
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
