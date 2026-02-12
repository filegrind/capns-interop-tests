# Test Capability Specifications

E-Commerce Order Processing System - Semantic Media URN Definitions

All test plugins implement capabilities for an imaginary e-commerce order processing platform.
Each capability has a real-world business meaning in this domain.

These MUST match exactly across all plugin implementations (Rust, Python, Go, Swift).

## Input/Output Format Rules

1. JSON object inputs: `media:<semantic>;json;textable;form=map`
2. Integer outputs: `media:<semantic>;integer;textable;numeric;form=scalar`
3. Text outputs: `media:<semantic>;textable;form=scalar`
4. Bytes inputs/outputs: `media:<semantic>;bytes`
5. Void: `media:void`

## Capability Definitions

### echo - Customer Service Message Echo
- Cap: `cap:in="media:customer-message;textable;form=scalar";op=echo;out="media:customer-message;textable;form=scalar"`
- Business: Echo back a customer service message
- Input: Customer's text message
- Output: Same message (echo service test)

### double - Loyalty Points Calculator
- Cap: `cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar"`
- Business: Calculate loyalty points from order value
- Input: JSON `{"value": N}` where N is order value in cents
- Output: Integer loyalty points (2× the order value)
- Example: Order $100 (10000 cents) → 20000 loyalty points

### stream_chunks - Order Status Updates
- Cap: `cap:in="media:update-count;json;textable;form=map";op=stream_chunks;out="media:order-updates;textable"`
- Business: Generate streaming order status updates
- Input: JSON `{"value": N}` - number of status updates to send
- Output: Stream of text updates (STREAM_START + CHUNKs + STREAM_END)

### binary_echo - Product Image Echo
- Cap: `cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes"`
- Business: Echo back a product image (binary data round-trip test)
- Input: Raw image bytes
- Output: Same bytes

### slow_response - Payment Processing Simulation
- Cap: `cap:in="media:payment-delay-ms;json;textable;form=map";op=slow_response;out="media:payment-result;textable;form=scalar"`
- Business: Simulate payment processing delay
- Input: JSON `{"value": N}` - milliseconds to wait
- Output: Payment confirmation text

### generate_large - Sales Report Generator
- Cap: `cap:in="media:report-size;json;textable;form=map";op=generate_large;out="media:sales-report;bytes"`
- Business: Generate a large sales report
- Input: JSON `{"value": N}` - bytes to generate
- Output: Raw report bytes (repeated 'X')

### with_status - Order Fulfillment Tracker
- Cap: `cap:in="media:fulfillment-steps;json;textable;form=map";op=with_status;out="media:fulfillment-status;textable;form=scalar"`
- Business: Track order fulfillment progress with status updates
- Input: JSON `{"value": N}` - number of fulfillment steps
- Output: Completion message
- Side effect: Sends N LOG frames during processing

### throw_error - Payment Error Reporter
- Cap: `cap:in="media:payment-error;json;textable;form=map";op=throw_error;out="media:void"`
- Business: Report a payment processing error
- Input: JSON `{"value": "error message"}`
- Output: void (sends ERR frame)

### peer_echo - Customer Message Relay
- Cap: `cap:in="media:customer-message;textable;form=scalar";op=peer_echo;out="media:customer-message;textable;form=scalar"`
- Business: Forward customer message to another service and echo response
- Input: Customer message text
- Output: Response from peer echo service
- Peer call: Invokes host's echo capability

### nested_call - Final Price Calculator
- Cap: `cap:in="media:order-value;json;textable;form=map";op=nested_call;out="media:final-price;integer;textable;numeric;form=scalar"`
- Business: Calculate final price with double discount (loyalty points applied twice)
- Input: JSON `{"value": N}` - base order value
- Output: Final price after applying double loyalty calculation (4× original value)
- Peer call: Invokes host's double capability, then doubles the result locally (N → 2N → 4N)

### heartbeat_stress - Peak Traffic Monitor
- Cap: `cap:in="media:monitoring-duration-ms;json;textable;form=map";op=heartbeat_stress;out="media:health-status;textable;form=scalar"`
- Business: Monitor system health during peak traffic period
- Input: JSON `{"value": N}` - monitoring duration in ms
- Output: Health status report
- Side effect: Sends HEARTBEAT frames

### concurrent_stress - Order Batch Processor
- Cap: `cap:in="media:order-batch-size;json;textable;form=map";op=concurrent_stress;out="media:batch-result;textable;form=scalar"`
- Business: Process a batch of orders concurrently
- Input: JSON `{"value": N}` - number of orders to process
- Output: Batch processing result

### get_manifest - Service Capabilities Query
- Cap: `cap:in="media:void";op=get_manifest;out="media:service-capabilities;json;textable;form=map"`
- Business: Get service capabilities manifest
- Input: void
- Output: JSON manifest describing available operations

### process_large - Document Analyzer
- Cap: `cap:in="media:uploaded-document;bytes";op=process_large;out="media:document-info;json;textable;form=map"`
- Business: Analyze uploaded document (large file processing test)
- Input: Raw document bytes
- Output: JSON `{"size": N, "sample": "first 10 bytes..."}`

### hash_incoming - Document Checksum Generator
- Cap: `cap:in="media:uploaded-document;bytes";op=hash_incoming;out="media:document-hash;textable;form=scalar"`
- Business: Generate checksum for uploaded document
- Input: Raw document bytes (sent as chunks)
- Output: SHA-256 hash hex string

### verify_binary - Package Integrity Verifier
- Cap: `cap:in="media:package-data;bytes";op=verify_binary;out="media:verification-status;textable;form=scalar"`
- Business: Verify package data integrity
- Input: Raw package bytes
- Output: "Binary OK: N bytes" or error message

### read_file_info - Invoice Metadata Reader
- Cap: `cap:in="media:invoice-path;textable;form=scalar";op=read_file_info;out="media:invoice-metadata;json;textable;form=map"`
- Business: Get metadata for an invoice file
- Input: File path to invoice
- Output: JSON with file metadata `{"size": N, "exists": true}`
- Note: PluginRuntime auto-converts file-path to file content

## Implementation Requirements

ALL implementations (Rust, Python, Go, Swift) MUST:
1. Use identical media URN tags as specified above (tag order doesn't matter - tagged URN parser handles normalization)
2. Parse JSON inputs from CBOR-decoded maps
3. Return integer/text/bytes as specified

## Cross-Language Consistency

- Rust: capns-interop-tests/src/capns_interop/plugins/rust/src/main.rs
- Python: capns-interop-tests/src/capns_interop/plugins/python/plugin.py
- Go: capns-interop-tests/src/capns_interop/plugins/go/main.go
- Swift: capns-interop-tests/src/capns_interop/plugins/swift/Sources/main.swift
