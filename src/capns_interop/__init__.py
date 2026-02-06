"""Capns interoperability testing framework."""

__version__ = "0.1.0"

# Standard test capabilities implemented by all test plugins
TEST_CAPS = {
    "echo": 'cap:in="media:string;textable;form=scalar";op=echo;out="media:string;textable;form=scalar"',
    "double": 'cap:in="media:number;form=scalar";op=double;out="media:number;form=scalar"',
    "stream_chunks": 'cap:in="media:number;form=scalar";op=stream_chunks;out="media:string;textable;streamable"',
    "binary_echo": 'cap:in="media:bytes";op=binary_echo;out="media:bytes"',
    "slow_response": 'cap:in="media:number;form=scalar";op=slow_response;out="media:string;textable;form=scalar"',
    "generate_large": 'cap:in="media:number;form=scalar";op=generate_large;out="media:bytes"',
    "with_status": 'cap:in="media:number;form=scalar";op=with_status;out="media:string;textable;form=scalar"',
    "throw_error": 'cap:in="media:string;textable;form=scalar";op=throw_error;out="media:void"',
    "peer_echo": 'cap:in="media:string;textable;form=scalar";op=peer_echo;out="media:string;textable;form=scalar"',
    "nested_call": 'cap:in="media:number;form=scalar";op=nested_call;out="media:string;textable;form=scalar"',
    "heartbeat_stress": 'cap:in="media:number;form=scalar";op=heartbeat_stress;out="media:string;textable;form=scalar"',
    "concurrent_stress": 'cap:in="media:number;form=scalar";op=concurrent_stress;out="media:string;textable;form=scalar"',
    "get_manifest": 'cap:in="media:void";op=get_manifest;out="media:json"',
}

SUPPORTED_LANGUAGES = ["rust", "python", "swift"]
