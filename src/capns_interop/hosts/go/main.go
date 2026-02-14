// Go test host binary for cross-language matrix tests.
//
// Reads JSON-line commands from stdin, manages a plugin subprocess
// via capns.PluginHost, and writes JSON-line responses to stdout.
package main

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"strings"
	"time"

	capns "github.com/filegrind/capns-go"
	cborlib "github.com/fxamacker/cbor/v2"
)

type goTestHost struct {
	host    *capns.PluginHost
	process *exec.Cmd
	stdin   io.WriteCloser
	stdout  io.ReadCloser
}

func main() {
	host := &goTestHost{}
	// 64MB scanner buffer for large base64 JSON lines
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024*1024), 64*1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var cmd map[string]interface{}
		if err := json.Unmarshal([]byte(line), &cmd); err != nil {
			writeResponse(map[string]interface{}{
				"ok":    false,
				"error": fmt.Sprintf("Invalid JSON: %v", err),
			})
			continue
		}

		cmdType, _ := cmd["cmd"].(string)
		var response map[string]interface{}
		var err error

		switch cmdType {
		case "spawn":
			response, err = host.handleSpawn(cmd)
		case "call":
			response, err = host.handleCall(cmd)
		case "throughput":
			response, err = host.handleThroughput(cmd)
		case "send_heartbeat":
			response, err = host.handleSendHeartbeat()
		case "get_manifest":
			response, err = host.handleGetManifest()
		case "shutdown":
			response, err = host.handleShutdown()
			if err == nil {
				writeResponse(response)
				return
			}
		default:
			response = map[string]interface{}{
				"ok":    false,
				"error": fmt.Sprintf("Unknown command: %s", cmdType),
			}
		}

		if err != nil {
			response = map[string]interface{}{
				"ok":    false,
				"error": err.Error(),
			}
		}

		writeResponse(response)
	}
}

func writeResponse(resp map[string]interface{}) {
	data, err := json.Marshal(resp)
	if err != nil {
		data = []byte(`{"ok":false,"error":"JSON marshal error"}`)
	}
	fmt.Println(string(data))
}

func (h *goTestHost) handleSpawn(cmd map[string]interface{}) (map[string]interface{}, error) {
	pluginPath, _ := cmd["plugin_path"].(string)

	var args []string
	if strings.HasSuffix(pluginPath, ".py") {
		// Use PYTHON_EXECUTABLE env var if set (passed from pytest),
		// otherwise fall back to "python3"
		pythonExe := os.Getenv("PYTHON_EXECUTABLE")
		if pythonExe == "" {
			pythonExe = "python3"
		}
		args = []string{pythonExe, pluginPath}
	} else {
		args = []string{pluginPath}
	}

	h.process = exec.Command(args[0], args[1:]...)
	h.process.Stderr = os.Stderr

	// If spawning a Python plugin, ensure PYTHONPATH includes capns-py and tagged-urn-py
	if strings.HasSuffix(pluginPath, ".py") {
		// Derive capns-py path relative to this binary's parent project
		// The plugin.py imports capns.plugin_runtime which needs capns-py/src in PYTHONPATH
		pluginDir := pluginPath
		// Walk up from plugin path to find the project root (capns-interop-tests)
		// then locate capns-py and tagged-urn-py relative to it
		// Use executable path to find project root
		execPath, _ := os.Executable()
		projectRoot := ""
		// Try to find capns-py by walking up from the executable
		dir := execPath
		for i := 0; i < 10; i++ {
			dir = dir[:strings.LastIndex(dir, "/")]
			if _, err := os.Stat(dir + "/capns-py/src"); err == nil {
				projectRoot = dir
				break
			}
		}
		if projectRoot == "" {
			// Try from plugin path
			dir = pluginDir
			for i := 0; i < 10; i++ {
				idx := strings.LastIndex(dir, "/")
				if idx < 0 {
					break
				}
				dir = dir[:idx]
				if _, err := os.Stat(dir + "/capns-py/src"); err == nil {
					projectRoot = dir
					break
				}
			}
		}
		if projectRoot != "" {
			pythonPath := projectRoot + "/capns-py/src:" + projectRoot + "/tagged-urn-py/src"
			existing := os.Getenv("PYTHONPATH")
			if existing != "" {
				pythonPath = pythonPath + ":" + existing
			}
			h.process.Env = append(os.Environ(), "PYTHONPATH="+pythonPath)
		}
	}

	var err error
	h.stdin, err = h.process.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to create stdin pipe: %w", err)
	}

	h.stdout, err = h.process.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to create stdout pipe: %w", err)
	}

	if err := h.process.Start(); err != nil {
		return nil, fmt.Errorf("failed to start plugin: %w", err)
	}

	// Create PluginHost (does CBOR handshake)
	h.host, err = capns.NewPluginHost(h.stdin, h.stdout)
	if err != nil {
		h.process.Process.Kill()
		return nil, fmt.Errorf("handshake failed: %w", err)
	}

	// Register echo and double handlers for bidirectional tests
	h.host.RegisterCapability("cap:in=media:;out=media:", func(payload []byte) ([]byte, error) {
		return payload, nil
	})

	h.host.RegisterCapability("cap:in=*;op=double;out=*", func(payload []byte) ([]byte, error) {
		var data map[string]interface{}
		if err := json.Unmarshal(payload, &data); err != nil {
			return nil, fmt.Errorf("failed to parse JSON: %w", err)
		}
		value, ok := data["value"].(float64)
		if !ok {
			return nil, fmt.Errorf("missing or invalid 'value' field")
		}
		result := int(value) * 2
		return json.Marshal(result)
	})

	manifest := h.host.Manifest()
	manifestB64 := base64.StdEncoding.EncodeToString(manifest)

	return map[string]interface{}{
		"ok":           true,
		"manifest_b64": manifestB64,
	}, nil
}

func (h *goTestHost) handleCall(cmd map[string]interface{}) (map[string]interface{}, error) {
	capUrn, _ := cmd["cap_urn"].(string)

	argsRaw, ok := cmd["arguments"].([]interface{})
	if !ok {
		return nil, fmt.Errorf("missing 'arguments' array")
	}

	var args []capns.CapArgumentValue
	for _, argRaw := range argsRaw {
		argMap, ok := argRaw.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("argument is not a map")
		}
		mediaUrn, _ := argMap["media_urn"].(string)
		valueB64, _ := argMap["value_b64"].(string)
		value, err := base64.StdEncoding.DecodeString(valueB64)
		if err != nil {
			return nil, fmt.Errorf("invalid base64 in argument: %w", err)
		}
		args = append(args, capns.NewCapArgumentValue(mediaUrn, value))
	}
	startNs := time.Now().UnixNano()
	response, err := h.host.CallWithArguments(capUrn, args)
	durationNs := time.Now().UnixNano() - startNs
	if err != nil {
		return nil, err
	}

	// Decode the response — CBOR-decode concatenated chunks
	switch response.Type {
	case capns.PluginResponseTypeStreaming:
		// Concatenate all chunk payloads
		var allData []byte
		for _, chunk := range response.Streaming {
			allData = append(allData, chunk.Payload...)
		}

		// Try to CBOR-decode multiple values
		decoded, err := decodeCborValues(allData)
		if err != nil {
			// Not CBOR — return raw chunks
			chunksB64 := make([]string, len(response.Streaming))
			for i, chunk := range response.Streaming {
				chunksB64[i] = base64.StdEncoding.EncodeToString(chunk.Payload)
			}
			return map[string]interface{}{
				"ok":          true,
				"is_streaming": true,
				"chunks_b64":  chunksB64,
				"duration_ns": durationNs,
			}, nil
		}

		if len(decoded) == 1 {
			return map[string]interface{}{
				"ok":           true,
				"payload_b64":  base64.StdEncoding.EncodeToString(decoded[0]),
				"is_streaming": false,
				"duration_ns":  durationNs,
			}, nil
		}

		chunksB64 := make([]string, len(decoded))
		for i, d := range decoded {
			chunksB64[i] = base64.StdEncoding.EncodeToString(d)
		}
		return map[string]interface{}{
			"ok":           true,
			"is_streaming": true,
			"chunks_b64":   chunksB64,
			"duration_ns":  durationNs,
		}, nil

	default:
		// Single response — CBOR-decode
		raw := response.Single
		decoded, err := decodeCborValues(raw)
		if err != nil || len(decoded) == 0 {
			return map[string]interface{}{
				"ok":           true,
				"payload_b64":  base64.StdEncoding.EncodeToString(raw),
				"is_streaming": false,
				"duration_ns":  durationNs,
			}, nil
		}

		if len(decoded) == 1 {
			return map[string]interface{}{
				"ok":           true,
				"payload_b64":  base64.StdEncoding.EncodeToString(decoded[0]),
				"is_streaming": false,
				"duration_ns":  durationNs,
			}, nil
		}

		chunksB64 := make([]string, len(decoded))
		for i, d := range decoded {
			chunksB64[i] = base64.StdEncoding.EncodeToString(d)
		}
		return map[string]interface{}{
			"ok":           true,
			"is_streaming": true,
			"chunks_b64":   chunksB64,
			"duration_ns":  durationNs,
		}, nil
	}
}

// decodeCborValues decodes concatenated CBOR values from raw bytes.
// Each value is converted to its byte representation:
// - bytes → raw bytes
// - string → UTF-8 bytes
// - other → JSON-encoded bytes
func decodeCborValues(raw []byte) ([][]byte, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	var results [][]byte
	offset := 0

	for offset < len(raw) {
		var value interface{}
		rest, err := cborlib.UnmarshalFirst(raw[offset:], &value)
		if err != nil {
			if offset == 0 {
				return nil, err
			}
			break
		}
		consumed := len(raw[offset:]) - len(rest)
		offset += consumed

		switch v := value.(type) {
		case []byte:
			results = append(results, v)
		case string:
			results = append(results, []byte(v))
		default:
			encoded, err := json.Marshal(v)
			if err != nil {
				return nil, err
			}
			results = append(results, encoded)
		}
	}

	return results, nil
}

func (h *goTestHost) handleThroughput(cmd map[string]interface{}) (map[string]interface{}, error) {
	if h.host == nil {
		return nil, fmt.Errorf("no host")
	}

	payloadMB := 5
	if v, ok := cmd["payload_mb"].(float64); ok {
		payloadMB = int(v)
	}
	payloadSize := payloadMB * 1024 * 1024
	capUrn := `cap:in="media:number;form=scalar";op=generate_large;out="media:bytes"`

	inputJSON, _ := json.Marshal(map[string]interface{}{"value": payloadSize})
	args := []capns.CapArgumentValue{capns.NewCapArgumentValue("media:json", inputJSON)}

	start := time.Now()
	response, err := h.host.CallWithArguments(capUrn, args)
	elapsed := time.Since(start).Seconds()
	if err != nil {
		return nil, err
	}

	// CBOR-decode to get exact payload bytes
	var raw []byte
	switch response.Type {
	case capns.PluginResponseTypeStreaming:
		for _, chunk := range response.Streaming {
			raw = append(raw, chunk.Payload...)
		}
	default:
		raw = response.Single
	}
	decoded, err := decodeCborValues(raw)
	if err != nil {
		return nil, fmt.Errorf("CBOR decode: %w", err)
	}
	totalBytes := 0
	for _, d := range decoded {
		totalBytes += len(d)
	}

	if totalBytes != payloadSize {
		return nil, fmt.Errorf("expected %d bytes, got %d", payloadSize, totalBytes)
	}

	mbPerSec := float64(payloadMB) / elapsed

	return map[string]interface{}{
		"ok":         true,
		"payload_mb": payloadMB,
		"duration_s": math.Round(elapsed*10000) / 10000,
		"mb_per_sec": math.Round(mbPerSec*100) / 100,
	}, nil
}

func (h *goTestHost) handleSendHeartbeat() (map[string]interface{}, error) {
	// Go PluginHost handles heartbeats transparently in readerLoop
	return map[string]interface{}{"ok": true}, nil
}

func (h *goTestHost) handleGetManifest() (map[string]interface{}, error) {
	manifest := h.host.Manifest()
	manifestB64 := base64.StdEncoding.EncodeToString(manifest)
	return map[string]interface{}{
		"ok":           true,
		"manifest_b64": manifestB64,
	}, nil
}

func (h *goTestHost) handleShutdown() (map[string]interface{}, error) {
	if h.host != nil {
		h.host.Close()
	}
	if h.stdin != nil {
		h.stdin.Close()
	}
	if h.process != nil && h.process.Process != nil {
		h.process.Process.Kill()
		h.process.Wait()
	}
	return map[string]interface{}{"ok": true}, nil
}
