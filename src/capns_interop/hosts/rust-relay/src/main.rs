/// Multi-plugin relay host test binary for cross-language interop tests.
///
/// Creates an PluginHostRuntime managing N plugin subprocesses, with optional RelaySlave layer.
/// Communicates via raw CBOR frames on stdin/stdout OR Unix socket.
///
/// Without --relay:
///     stdin/stdout carry raw CBOR frames (PluginHostRuntime relay interface).
///
/// With --relay:
///     stdin/stdout OR socket carry CBOR frames including relay-specific types.
///     RelaySlave sits between stdin/stdout (or socket) and PluginHostRuntime.
///     Initial RelayNotify sent on startup.
///
/// With --listen <socket-path>:
///     Creates a Unix socket listener and accepts ONE connection from router.
///     Router and host are independent processes (not parent-child).
use std::os::unix::io::{FromRawFd, IntoRawFd};
use std::os::unix::net::UnixListener;
use std::process::Command;

use capns::bifaci::host_runtime::PluginHostRuntime;
use capns::bifaci::frame::Limits;
use capns::bifaci::io::{FrameReader, FrameWriter};
use capns::bifaci::relay::RelaySlave;

#[derive(Debug)]
struct Args {
    plugins: Vec<String>,
    relay: bool,
    listen_socket: Option<String>,
}

fn parse_args() -> Args {
    let mut args = Args {
        plugins: Vec::new(),
        relay: false,
        listen_socket: None,
    };
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < argv.len() {
        match argv[i].as_str() {
            "--spawn" => {
                i += 1;
                if i >= argv.len() {
                    eprintln!("ERROR: --spawn requires a path argument");
                    std::process::exit(1);
                }
                args.plugins.push(argv[i].clone());
            }
            "--relay" => {
                args.relay = true;
            }
            "--listen" => {
                i += 1;
                if i >= argv.len() {
                    eprintln!("ERROR: --listen requires a socket path argument");
                    std::process::exit(1);
                }
                args.listen_socket = Some(argv[i].clone());
            }
            other => {
                eprintln!("ERROR: unknown argument: {}", other);
                std::process::exit(1);
            }
        }
        i += 1;
    }
    args
}

fn spawn_plugin(plugin_path: &str) -> (std::process::ChildStdout, std::process::ChildStdin, std::process::Child) {
    let mut cmd = Command::new(plugin_path);

    cmd.stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit());

    let mut child = cmd.spawn().unwrap_or_else(|e| {
        eprintln!("Failed to spawn {}: {}", plugin_path, e);
        std::process::exit(1);
    });

    let stdout = child.stdout.take().unwrap();
    let stdin = child.stdin.take().unwrap();
    (stdout, stdin, child)
}

fn create_pipe() -> (std::fs::File, std::fs::File) {
    let mut fds = [0i32; 2];
    let ret = unsafe { libc::pipe(fds.as_mut_ptr()) };
    if ret != 0 {
        eprintln!("pipe() failed");
        std::process::exit(1);
    }
    unsafe {
        (
            std::fs::File::from_raw_fd(fds[0]),
            std::fs::File::from_raw_fd(fds[1]),
        )
    }
}

#[tokio::main]
async fn main() {
    let args = parse_args();

    if args.plugins.is_empty() {
        eprintln!("ERROR: at least one --spawn required");
        std::process::exit(1);
    }

    let mut host = PluginHostRuntime::new();
    let mut children: Vec<std::process::Child> = Vec::new();

    for plugin_path in &args.plugins {
        let (stdout, stdin, child) = spawn_plugin(plugin_path);
        children.push(child);

        let plugin_read = tokio::fs::File::from_std(unsafe {
            std::fs::File::from_raw_fd(stdout.into_raw_fd())
        });
        let plugin_write = tokio::fs::File::from_std(unsafe {
            std::fs::File::from_raw_fd(stdin.into_raw_fd())
        });

        if let Err(e) = host.attach_plugin(plugin_read, plugin_write).await {
            eprintln!("Failed to attach {}: {}", plugin_path, e);
            std::process::exit(1);
        }
    }

    if args.relay {
        if let Some(socket_path) = args.listen_socket {
            run_with_relay_socket(host, &socket_path).await;
        } else {
            run_with_relay(host).await;
        }
    } else {
        run_direct(host).await;
    }

    // Cleanup
    for mut child in children {
        let _ = child.kill();
        let _ = child.wait();
    }
}

async fn run_direct(mut host: PluginHostRuntime) {
    let relay_read = tokio::io::stdin();
    let relay_write = tokio::io::stdout();

    if let Err(e) = host.run(relay_read, relay_write, || Vec::new()).await {
        eprintln!("PluginHostRuntime.run error: {}", e);
        std::process::exit(1);
    }
}

async fn run_with_relay(mut host: PluginHostRuntime) {
    // Create pipe pairs for slave ↔ host communication
    // Pipe A: slave writes → host reads
    let (a_read, a_write) = create_pipe();
    // Pipe B: host writes → slave reads
    let (b_read, b_write) = create_pipe();

    // Run host in a tokio task with async pipe ends
    let host_relay_read = tokio::fs::File::from_std(a_read);
    let host_relay_write = tokio::fs::File::from_std(b_write);

    let host_handle = tokio::spawn(async move {
        host.run(host_relay_read, host_relay_write, || Vec::new()).await
    });

    // Run slave in a blocking thread with sync pipe ends + owned stdin/stdout.
    // Use raw fd to get owned File handles (stdin.lock() is not Send).
    let stdin_file = unsafe { std::fs::File::from_raw_fd(0) };
    let stdout_file = unsafe { std::fs::File::from_raw_fd(1) };

    let slave_handle = tokio::task::spawn_blocking(move || {
        let slave = RelaySlave::new(b_read, a_write);

        let socket_reader = FrameReader::new(std::io::BufReader::new(stdin_file));
        let socket_writer = FrameWriter::new(std::io::BufWriter::new(stdout_file));

        // Send initial RelayNotify with CAP_IDENTITY (always available).
        // PluginHostRuntime will send updated RelayNotify after plugins connect.
        let initial_caps = vec![capns::standard::caps::CAP_IDENTITY.to_string()];
        let initial_caps_json = serde_json::to_vec(&initial_caps)
            .expect("Failed to serialize initial caps array");
        eprintln!("[RelayHost] Initial RelayNotify payload: {} bytes: {:?}",
                  initial_caps_json.len(),
                  std::str::from_utf8(&initial_caps_json).unwrap_or("<invalid UTF-8>"));
        let limits = Limits::default();
        let result = slave.run(
            socket_reader,
            socket_writer,
            Some((&initial_caps_json, &limits)),
        );

        if let Err(e) = result {
            eprintln!("RelaySlave.run error: {}", e);
        }
    });

    // Wait for slave to finish (master closed connection)
    let _ = slave_handle.await;
    // Abort host (slave pipes are closed, host should exit)
    host_handle.abort();
    let _ = host_handle.await;
}

async fn run_with_relay_socket(mut host: PluginHostRuntime, socket_path: &str) {
    // Remove existing socket if it exists
    let _ = std::fs::remove_file(socket_path);

    // Create Unix socket listener
    let listener = UnixListener::bind(socket_path).unwrap_or_else(|e| {
        eprintln!("Failed to bind socket {}: {}", socket_path, e);
        std::process::exit(1);
    });

    eprintln!("[RelayHost] Listening on socket: {}", socket_path);

    // Accept ONE connection from router
    let (socket, _addr) = listener.accept().unwrap_or_else(|e| {
        eprintln!("Failed to accept connection: {}", e);
        std::process::exit(1);
    });

    eprintln!("[RelayHost] Router connected");

    // Create pipe pairs for slave ↔ host communication
    // Pipe A: slave writes → host reads
    let (a_read, a_write) = create_pipe();
    // Pipe B: host writes → slave reads
    let (b_read, b_write) = create_pipe();

    // Run host in a tokio task with async pipe ends
    let host_relay_read = tokio::fs::File::from_std(a_read);
    let host_relay_write = tokio::fs::File::from_std(b_write);

    let host_handle = tokio::spawn(async move {
        host.run(host_relay_read, host_relay_write, || Vec::new()).await
    });

    // Clone socket for bidirectional communication
    let socket_read = socket.try_clone().unwrap_or_else(|e| {
        eprintln!("Failed to clone socket: {}", e);
        std::process::exit(1);
    });

    // Run slave in a blocking thread with sync pipe ends + socket
    let slave_handle = tokio::task::spawn_blocking(move || {
        let slave = RelaySlave::new(b_read, a_write);

        let socket_reader = FrameReader::new(std::io::BufReader::new(socket_read));
        let socket_writer = FrameWriter::new(std::io::BufWriter::new(socket));

        // Send initial RelayNotify with CAP_IDENTITY (always available).
        // PluginHostRuntime will send updated RelayNotify after plugins connect.
        let initial_caps = vec![capns::standard::caps::CAP_IDENTITY.to_string()];
        let initial_caps_json = serde_json::to_vec(&initial_caps)
            .expect("Failed to serialize initial caps array");
        eprintln!("[RelayHost] Initial RelayNotify payload: {} bytes: {:?}",
                  initial_caps_json.len(),
                  std::str::from_utf8(&initial_caps_json).unwrap_or("<invalid UTF-8>"));
        let limits = Limits::default();
        let result = slave.run(
            socket_reader,
            socket_writer,
            Some((&initial_caps_json, &limits)),
        );

        if let Err(e) = result {
            eprintln!("RelaySlave.run error: {}", e);
        }

        eprintln!("[RelayHost] Slave finished, router disconnected");
    });

    // Wait for slave to finish (router closed connection)
    let _ = slave_handle.await;
    // Abort host (slave pipes are closed, host should exit)
    host_handle.abort();
    let _ = host_handle.await;

    eprintln!("[RelayHost] Shutting down");
}
