// Multi-plugin relay host test binary for cross-language interop tests.
//
// Creates a PluginHost managing N plugin subprocesses, with optional RelaySlave layer.
// Communicates via raw CBOR frames on stdin/stdout.
//
// Without --relay:
//
//	stdin/stdout carry raw CBOR frames (PluginHost relay interface).
//
// With --relay:
//
//	stdin/stdout carry CBOR frames including relay-specific types.
//	RelaySlave sits between stdin/stdout and PluginHost.
//	Initial RelayNotify sent on startup with aggregate manifest + limits.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"

	"github.com/filegrind/capns-go/bifaci"
)

type pluginList []string

func (p *pluginList) String() string { return strings.Join(*p, ",") }
func (p *pluginList) Set(v string) error {
	*p = append(*p, v)
	return nil
}

func main() {
	var plugins pluginList
	var relay bool
	flag.Var(&plugins, "spawn", "path to plugin binary (repeatable)")
	flag.BoolVar(&relay, "relay", false, "enable RelaySlave layer")
	flag.Parse()

	if len(plugins) == 0 {
		fmt.Fprintln(os.Stderr, "ERROR: at least one --spawn required")
		os.Exit(1)
	}

	host := bifaci.NewPluginHost()
	var processes []*exec.Cmd

	for _, pluginPath := range plugins {
		pluginRead, pluginWrite, cmd, err := spawnPlugin(pluginPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "failed to spawn %s: %v\n", pluginPath, err)
			os.Exit(1)
		}
		processes = append(processes, cmd)

		if _, err := host.AttachPlugin(pluginRead, pluginWrite); err != nil {
			fmt.Fprintf(os.Stderr, "failed to attach %s: %v\n", pluginPath, err)
			os.Exit(1)
		}
	}

	defer func() {
		for _, cmd := range processes {
			if cmd.Process != nil {
				cmd.Process.Kill()
				cmd.Wait()
			}
		}
	}()

	if relay {
		runWithRelay(host)
	} else {
		runDirect(host)
	}
}

func spawnPlugin(pluginPath string) (stdout io.ReadCloser, stdin io.WriteCloser, cmd *exec.Cmd, err error) {
	var args []string
	if strings.HasSuffix(pluginPath, ".py") {
		pythonExe := os.Getenv("PYTHON_EXECUTABLE")
		if pythonExe == "" {
			pythonExe = "python3"
		}
		args = []string{pythonExe, pluginPath}
	} else {
		args = []string{pluginPath}
	}

	cmd = exec.Command(args[0], args[1:]...)
	cmd.Stderr = os.Stderr

	// Set up PYTHONPATH for Python plugins
	if strings.HasSuffix(pluginPath, ".py") {
		cmd.Env = buildPythonEnv()
	}

	stdin, err = cmd.StdinPipe()
	if err != nil {
		return nil, nil, nil, fmt.Errorf("stdin pipe: %w", err)
	}

	stdout, err = cmd.StdoutPipe()
	if err != nil {
		return nil, nil, nil, fmt.Errorf("stdout pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, nil, nil, fmt.Errorf("start: %w", err)
	}

	return stdout, stdin, cmd, nil
}

func buildPythonEnv() []string {
	// Find project root by walking up from executable path
	execPath, _ := os.Executable()
	projectRoot := ""
	dir := execPath
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
	if projectRoot == "" {
		return os.Environ()
	}

	pythonPath := projectRoot + "/capns-py/src:" + projectRoot + "/tagged-urn-py/src"
	existing := os.Getenv("PYTHONPATH")
	if existing != "" {
		pythonPath = pythonPath + ":" + existing
	}
	return append(os.Environ(), "PYTHONPATH="+pythonPath)
}

func runDirect(host *bifaci.PluginHost) {
	if err := host.Run(os.Stdin, os.Stdout, func() []byte { return nil }); err != nil {
		fmt.Fprintf(os.Stderr, "PluginHost.Run error: %v\n", err)
		os.Exit(1)
	}
}

func runWithRelay(host *bifaci.PluginHost) {
	// Create two pipe pairs for bidirectional communication between slave and host.
	// Pipe A: slave writes → host reads
	aRead, aWrite, err := os.Pipe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "pipe A: %v\n", err)
		os.Exit(1)
	}
	// Pipe B: host writes → slave reads
	bRead, bWrite, err := os.Pipe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "pipe B: %v\n", err)
		os.Exit(1)
	}

	caps := host.Capabilities()
	if caps == nil {
		caps = []byte("[]")
	}
	limits := bifaci.DefaultLimits()

	var wg sync.WaitGroup
	var hostErr error

	// Run PluginHost in background goroutine
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer aRead.Close()
		defer bWrite.Close()
		hostErr = host.Run(aRead, bWrite, func() []byte { return nil })
	}()

	// Run RelaySlave in main goroutine
	slave := bifaci.NewRelaySlave(bRead, aWrite)
	slaveErr := slave.Run(os.Stdin, os.Stdout, &bifaci.RelayNotifyParams{
		Manifest: caps,
		Limits:   limits,
	})

	// Close slave's pipe ends to unblock host
	aWrite.Close()
	bRead.Close()

	wg.Wait()

	if slaveErr != nil {
		fmt.Fprintf(os.Stderr, "RelaySlave.Run error: %v\n", slaveErr)
	}
	if hostErr != nil {
		fmt.Fprintf(os.Stderr, "PluginHost.Run error: %v\n", hostErr)
	}
}
