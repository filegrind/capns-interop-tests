/// Rust Router Binary for Interop Tests
///
/// Position: Router (RelaySwitch + RelayMaster)
/// Communicates with test orchestration via stdin/stdout (CBOR frames)
/// Connects to independent relay host processes via Unix sockets
///
/// Usage:
///   capns-interop-router-rust --connect <socket-path> [--connect <another-socket>]
use std::os::unix::net::UnixStream;

use capns::bifaci::frame::SeqAssigner;
use capns::bifaci::io::{FrameReader, FrameWriter};
use capns::bifaci::relay_switch::RelaySwitch;

#[derive(Debug)]
struct Args {
    socket_paths: Vec<String>,
}

fn parse_args() -> Args {
    let mut args = Args { socket_paths: Vec::new() };
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < argv.len() {
        match argv[i].as_str() {
            "--connect" => {
                i += 1;
                if i >= argv.len() {
                    eprintln!("ERROR: --connect requires a socket path argument");
                    std::process::exit(1);
                }
                args.socket_paths.push(argv[i].clone());
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

fn connect_to_host(socket_path: &str) -> (UnixStream, UnixStream) {
    eprintln!("[Router] Connecting to relay host at: {}", socket_path);

    // Connect to the relay host's listening socket
    let stream = UnixStream::connect(socket_path).unwrap_or_else(|e| {
        eprintln!("ERROR: Failed to connect to {}: {}", socket_path, e);
        std::process::exit(1);
    });

    // Clone the stream for bidirectional communication
    // Router reads from one handle, writes to the other
    let read_stream = stream.try_clone().unwrap_or_else(|e| {
        eprintln!("ERROR: Failed to clone socket: {}", e);
        std::process::exit(1);
    });

    eprintln!("[Router] Connected to relay host at {}", socket_path);
    (read_stream, stream)
}

fn main() {
    let args = parse_args();

    if args.socket_paths.is_empty() {
        eprintln!("ERROR: at least one --connect <socket-path> required");
        std::process::exit(1);
    }

    // Connect to all relay host sockets
    let mut socket_pairs: Vec<(UnixStream, UnixStream)> = Vec::new();

    for socket_path in &args.socket_paths {
        let (read, write) = connect_to_host(socket_path);
        socket_pairs.push((read, write));
    }

    // Create RelaySwitch with all host connections
    eprintln!("[Router] Creating RelaySwitch with {} host(s)", socket_pairs.len());
    let mut switch = RelaySwitch::new(socket_pairs).unwrap_or_else(|e| {
        eprintln!("Failed to create RelaySwitch: {}", e);
        std::process::exit(1);
    });

    eprintln!("[Router] RelaySwitch initialized, connected to {} relay host(s)", args.socket_paths.len());

    // Send initial RelayNotify to engine with aggregate capabilities.
    // The full capabilities from hosts were consumed during identity verification
    // in RelaySwitch::new(), so the engine hasn't seen them yet.
    {
        let stdout = std::io::stdout();
        let mut init_writer = FrameWriter::new(std::io::BufWriter::new(stdout.lock()));
        let notify = capns::bifaci::frame::Frame::relay_notify(
            switch.capabilities(),
            switch.limits(),
        );
        init_writer.write(&notify).unwrap_or_else(|e| {
            eprintln!("Failed to write initial RelayNotify to engine: {}", e);
            std::process::exit(1);
        });
        eprintln!("[Router] Sent initial RelayNotify to engine ({} bytes)", switch.capabilities().len());
    }

    // Router is a pure multiplexer - two independent loops:
    //   - Thread 1: stdin → channel (continuously read stdin, send frames to channel)
    //   - Thread 2 (main): channel + RelaySwitch → stdout (multiplex stdin frames and master frames)
    //
    // No coupling between them! Frames flow independently in both directions.
    //
    // Architecture:
    //   - stdin thread sends frames to stdin_tx channel
    //   - main thread owns RelaySwitch (no mutex needed!)
    //   - main thread multiplexes: stdin_rx (non-blocking) and switch.read_from_masters() (blocking)

    use std::sync::mpsc;
    use std::thread;

    let (stdin_tx, stdin_rx) = mpsc::channel();

    // Thread 1: stdin → channel
    thread::spawn(move || {
        let stdin = std::io::stdin();
        let mut reader = FrameReader::new(std::io::BufReader::new(stdin.lock()));

        eprintln!("[Router/stdin] Starting stdin reader loop");
        loop {
            match reader.read() {
                Ok(Some(frame)) => {
                    eprintln!("[Router/stdin] Read frame: {:?} (id={:?})", frame.frame_type, frame.id);
                    if stdin_tx.send(frame).is_err() {
                        eprintln!("[Router/stdin] Channel closed, exiting");
                        break;
                    }
                }
                Ok(None) => {
                    eprintln!("[Router/stdin] EOF on stdin, exiting");
                    break;
                }
                Err(e) => {
                    eprintln!("[Router/stdin] Error reading: {}", e);
                    break;
                }
            }
        }
    });

    // Main thread: multiplex stdin_rx and RelaySwitch
    let stdout = std::io::stdout();
    let mut writer = FrameWriter::new(std::io::BufWriter::new(stdout.lock()));
    let mut stdout_seq = SeqAssigner::new();

    eprintln!("[Router/main] Starting main multiplexer loop");

    // Main loop: balanced interleaving of stdin and master frames
    // Process one stdin frame, then one master frame (with timeout), repeat
    loop {
        // Try to read ONE stdin frame (non-blocking)
        match stdin_rx.try_recv() {
            Ok(frame) => {
                eprintln!("[Router/main] Sending stdin frame to master: {:?} (id={:?})", frame.frame_type, frame.id);
                let frame_id = frame.id.clone();
                let is_req = frame.frame_type == capns::bifaci::frame::FrameType::Req;
                if let Err(e) = switch.send_to_master(frame) {
                    eprintln!("[Router/main] Error sending to master: {}", e);
                    // On REQ failure, send ERR back to engine so it doesn't hang
                    if is_req {
                        let err_frame = capns::bifaci::frame::Frame::err(frame_id, "NO_HANDLER", &e.to_string());
                        if let Err(write_err) = writer.write(&err_frame) {
                            eprintln!("[Router/main] Failed to write ERR frame: {}", write_err);
                        }
                    }
                }
            }
            Err(mpsc::TryRecvError::Empty) => {
                // No stdin frame available right now, that's OK
            }
            Err(mpsc::TryRecvError::Disconnected) => {
                eprintln!("[Router/main] stdin channel closed, shutting down");
                break;
            }
        }

        // Try to read ONE master frame (with timeout to avoid blocking forever)
        // Use a short timeout so we can quickly check stdin again
        use std::time::Duration;
        match switch.read_from_masters_timeout(Duration::from_millis(10)) {
            Ok(Some(mut frame)) => {
                eprintln!("[Router/main] Received from master: {:?} (id={:?})", frame.frame_type, frame.id);
                stdout_seq.assign(&mut frame);
                if let Err(e) = writer.write(&frame) {
                    eprintln!("[Router/main] Error writing to stdout: {}", e);
                    break;
                }
                if matches!(frame.frame_type, capns::bifaci::frame::FrameType::End | capns::bifaci::frame::FrameType::Err) {
                    stdout_seq.remove(&frame.id);
                }
            }
            Ok(None) => {
                // Timeout - no master frame available, that's OK, loop back to check stdin
            }
            Err(e) => {
                eprintln!("[Router/main] ERROR reading from masters: {} - Router exiting and closing connections!", e);
                eprintln!("[Router/main] THIS IS A BUG - Router should NOT exit while test is running!");
                break;
            }
        }
    }

    // Cleanup
    eprintln!("[Router] Shutting down - relay hosts will continue running independently");
}
