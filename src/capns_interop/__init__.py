"""Capns interoperability testing framework."""

__version__ = "0.1.0"

# E-commerce test capabilities implemented by all test plugins
# Each cap represents a business operation in an imaginary order processing system
TEST_CAPS = {
    "echo": 'cap:in="media:customer-message;textable;form=scalar";op=echo;out="media:customer-message;textable;form=scalar"',
    "double": 'cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar"',
    "stream_chunks": 'cap:in="media:update-count;json;textable;form=map";op=stream_chunks;out="media:order-updates;textable"',
    "binary_echo": 'cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes"',
    "slow_response": 'cap:in="media:payment-delay-ms;json;textable;form=map";op=slow_response;out="media:payment-result;textable;form=scalar"',
    "generate_large": 'cap:in="media:report-size;json;textable;form=map";op=generate_large;out="media:sales-report;bytes"',
    "with_status": 'cap:in="media:fulfillment-steps;json;textable;form=map";op=with_status;out="media:fulfillment-status;textable;form=scalar"',
    "throw_error": 'cap:in="media:payment-error;json;textable;form=map";op=throw_error;out="media:void"',
    "peer_echo": 'cap:in="media:customer-message;textable;form=scalar";op=peer_echo;out="media:customer-message;textable;form=scalar"',
    "nested_call": 'cap:in="media:order-value;json;textable;form=map";op=nested_call;out="media:final-price;integer;textable;numeric;form=scalar"',
    "heartbeat_stress": 'cap:in="media:monitoring-duration-ms;json;textable;form=map";op=heartbeat_stress;out="media:health-status;textable;form=scalar"',
    "concurrent_stress": 'cap:in="media:order-batch-size;json;textable;form=map";op=concurrent_stress;out="media:batch-result;textable;form=scalar"',
    "get_manifest": 'cap:in="media:void";op=get_manifest;out="media:service-capabilities;json;textable;form=map"',
    # Incoming chunking test capabilities (host sends large data TO plugin)
    "process_large": 'cap:in="media:uploaded-document;bytes";op=process_large;out="media:document-info;json;textable;form=map"',
    "hash_incoming": 'cap:in="media:uploaded-document;bytes";op=hash_incoming;out="media:document-hash;textable;form=scalar"',
    "verify_binary": 'cap:in="media:package-data;bytes";op=verify_binary;out="media:verification-status;textable;form=scalar"',
    # File-path conversion test capability (runtime auto-converts file to bytes)
    "read_file_info": 'cap:in="media:invoice-path;textable;form=scalar";op=read_file_info;out="media:invoice-metadata;json;textable;form=map"',
}

SUPPORTED_LANGUAGES = ["rust", "python", "swift", "go"]
