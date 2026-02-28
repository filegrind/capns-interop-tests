"""Capns interoperability testing framework."""

__version__ = "0.1.0"

# E-commerce test capabilities implemented by all test plugins
# Each cap represents a business operation in an imaginary order processing system
TEST_CAPS = {
    "echo": 'cap:in="media:";op=echo;out="media:"',
    "double": 'cap:in="media:order-value;json;textable;record";op=double;out="media:loyalty-points;integer;textable;numeric"',
    "stream_chunks": 'cap:in="media:update-count;json;textable;record";op=stream_chunks;out="media:order-updates;textable"',
    "binary_echo": 'cap:in="media:product-image";op=binary_echo;out="media:product-image"',
    "slow_response": 'cap:in="media:payment-delay-ms;json;textable;record";op=slow_response;out="media:payment-result;textable"',
    "generate_large": 'cap:in="media:report-size;json;textable;record";op=generate_large;out="media:sales-report"',
    "with_status": 'cap:in="media:fulfillment-steps;json;textable;record";op=with_status;out="media:fulfillment-status;textable"',
    "throw_error": 'cap:in="media:payment-error;json;textable;record";op=throw_error;out="media:void"',
    "peer_echo": 'cap:in="media:customer-message;textable";op=peer_echo;out="media:customer-message;textable"',
    "nested_call": 'cap:in="media:order-value;json;textable;record";op=nested_call;out="media:final-price;integer;textable;numeric"',
    "heartbeat_stress": 'cap:in="media:monitoring-duration-ms;json;textable;record";op=heartbeat_stress;out="media:health-status;textable"',
    "concurrent_stress": 'cap:in="media:order-batch-size;json;textable;record";op=concurrent_stress;out="media:batch-result;textable"',
    "get_manifest": 'cap:in="media:void";op=get_manifest;out="media:service-capabilities;json;textable;record"',
    # Incoming chunking test capabilities (host sends large data TO plugin)
    "process_large": 'cap:in="media:uploaded-document";op=process_large;out="media:document-info;json;textable;record"',
    "hash_incoming": 'cap:in="media:uploaded-document";op=hash_incoming;out="media:document-hash;textable"',
    "verify_binary": 'cap:in="media:package-data";op=verify_binary;out="media:verification-status;textable"',
    # File-path conversion test capability (runtime auto-converts file to bytes)
    "read_file_info": 'cap:in="media:invoice-path;textable";op=read_file_info;out="media:invoice-metadata;json;textable;record"',
}

SUPPORTED_LANGUAGES = ["rust", "python", "swift", "go"]
