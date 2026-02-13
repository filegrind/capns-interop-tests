/// Multi-plugin relay host test binary for cross-language interop tests.
///
/// Creates an AsyncPluginHost managing N plugin subprocesses, with optional RelaySlave layer.
/// Communicates via raw CBOR frames on stdin/stdout.
///
/// Without --relay:
///     stdin/stdout carry raw CBOR frames (AsyncPluginHost relay interface).
///
/// With --relay:
///     stdin/stdout carry CBOR frames including relay-specific types.
///     RelaySlave sits between stdin/stdout and AsyncPluginHost.
///     Initial RelayNotify sent on startup.
use std::os::unix::io::{FromRawFd, IntoRawFd};
use std::process::Command;

use capns::async_plugin_host::AsyncPluginHost;
use capns::cbor_frame::Limits;
use capns::cbor_io::{FrameReader, FrameWriter};
use capns::plugin_relay::RelaySlave;

#[derive(Debug)]
struct Args {
    plugins: Vec<String>,
    relay: bool,
}

fn parse_args() -> Args {
    let mut args = Args {
        plugins: Vec::new(),
        relay: false,
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
    let mut cmd = if plugin_path.ends_with(".py") {
        let python_exe = std::env::var("PYTHON_EXECUTABLE").unwrap_or_else(|_| "python3".to_string());
        let mut c = Command::new(&python_exe);
        c.arg(plugin_path);
        c
    } else {
        Command::new(plugin_path)
    };

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

    let mut host = AsyncPluginHost::new();
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
        run_with_relay(host).await;
    } else {
        run_direct(host).await;
    }

    // Cleanup
    for mut child in children {
        let _ = child.kill();
        let _ = child.wait();
    }
}

async fn run_direct(mut host: AsyncPluginHost) {
    let relay_read = tokio::io::stdin();
    let relay_write = tokio::io::stdout();

    if let Err(e) = host.run(relay_read, relay_write, || Vec::new()).await {
        eprintln!("AsyncPluginHost.run error: {}", e);
        std::process::exit(1);
    }
}

async fn run_with_relay(mut host: AsyncPluginHost) {
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

        // Send initial empty RelayNotify (plugins haven't connected yet)
        // AsyncPluginHost will send updated RelayNotify after plugins connect
        let empty_manifest = br#"{"capabilities":[]}"#;
        let limits = Limits::default();
        let result = slave.run(
            socket_reader,
            socket_writer,
            Some((empty_manifest.as_slice(), &limits)),
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
