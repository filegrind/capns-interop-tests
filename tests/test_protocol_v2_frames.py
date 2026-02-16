"""Protocol v2 frame type tests.

Tests that all implementations correctly encode/decode the new frame types
introduced in Protocol v2: STREAM_START and STREAM_END.
"""

import pytest
import io

from capns.cbor_frame import Frame, FrameType, MessageId, PROTOCOL_VERSION, compute_checksum
from capns.cbor_io import encode_frame, decode_frame, FrameWriter, FrameReader, Limits


def test_protocol_version_is_2():
    """Verify Protocol v2 constant."""
    assert PROTOCOL_VERSION == 2, "PROTOCOL_VERSION must be 2"


def test_stream_start_frame_type_value():
    """Verify STREAM_START has value 8."""
    assert FrameType.STREAM_START == 8


def test_stream_end_frame_type_value():
    """Verify STREAM_END has value 9."""
    assert FrameType.STREAM_END == 9


def test_stream_start_constructor():
    """Test Frame.stream_start() constructor."""
    req_id = MessageId.new_uuid()
    stream_id = "test-stream-123"
    media_urn = "media:bytes"

    frame = Frame.stream_start(req_id, stream_id, media_urn)

    assert frame.frame_type == FrameType.STREAM_START
    assert frame.id == req_id
    assert frame.stream_id == stream_id
    assert frame.media_urn == media_urn
    assert frame.version == 2


def test_stream_end_constructor():
    """Test Frame.stream_end() constructor."""
    req_id = MessageId.new_uuid()
    stream_id = "test-stream-456"

    frame = Frame.stream_end(req_id, stream_id, 0)

    assert frame.frame_type == FrameType.STREAM_END
    assert frame.id == req_id
    assert frame.stream_id == stream_id
    assert frame.media_urn is None  # StreamEnd should not have media_urn
    assert frame.version == 2


def test_stream_start_encode_decode_roundtrip():
    """Test STREAM_START frame survives encode/decode."""
    req_id = MessageId.new_uuid()
    stream_id = "roundtrip-stream"
    media_urn = "media:json"

    original = Frame.stream_start(req_id, stream_id, media_urn)
    encoded = encode_frame(original)
    decoded = decode_frame(encoded)

    assert decoded.frame_type == FrameType.STREAM_START
    assert decoded.id == req_id
    assert decoded.stream_id == stream_id
    assert decoded.media_urn == media_urn


def test_stream_end_encode_decode_roundtrip():
    """Test STREAM_END frame survives encode/decode."""
    req_id = MessageId.new_uuid()
    stream_id = "end-stream"

    original = Frame.stream_end(req_id, stream_id, 0)
    encoded = encode_frame(original)
    decoded = decode_frame(encoded)

    assert decoded.frame_type == FrameType.STREAM_END
    assert decoded.id == req_id
    assert decoded.stream_id == stream_id
    assert decoded.media_urn is None


def test_stream_frames_with_wire_format():
    """Test STREAM_START and STREAM_END with length-prefixed wire format."""
    buf = io.BytesIO()
    writer = FrameWriter(buf, Limits.default())
    req_id = MessageId.new_uuid()

    # Write STREAM_START
    start_frame = Frame.stream_start(req_id, "stream-1", "media:bytes")
    writer.write(start_frame)

    # Write STREAM_END
    end_frame = Frame.stream_end(req_id, "stream-1", 0)
    writer.write(end_frame)

    # Read back
    buf.seek(0)
    reader = FrameReader(buf)

    decoded_start = reader.read()
    assert decoded_start is not None
    assert decoded_start.frame_type == FrameType.STREAM_START
    assert decoded_start.stream_id == "stream-1"
    assert decoded_start.media_urn == "media:bytes"

    decoded_end = reader.read()
    assert decoded_end is not None
    assert decoded_end.frame_type == FrameType.STREAM_END
    assert decoded_end.stream_id == "stream-1"
    assert decoded_end.media_urn is None


def test_multiple_stream_ids_preserved():
    """Test that multiple different stream IDs are preserved."""
    req_id = MessageId.new_uuid()
    stream_ids = ["stream-a", "stream-b", "stream-c"]

    buf = io.BytesIO()
    writer = FrameWriter(buf, Limits.default())

    # Write multiple stream starts
    for sid in stream_ids:
        frame = Frame.stream_start(req_id, sid, "media:bytes")
        writer.write(frame)

    # Read back and verify
    buf.seek(0)
    reader = FrameReader(buf)

    for expected_sid in stream_ids:
        frame = reader.read()
        assert frame is not None
        assert frame.stream_id == expected_sid


def test_empty_stream_id_allowed():
    """Test that empty stream_id is allowed (validation happens at protocol level)."""
    req_id = MessageId.new_uuid()
    frame = Frame.stream_start(req_id, "", "media:bytes")

    assert frame.stream_id == ""

    # Should encode/decode successfully
    encoded = encode_frame(frame)
    decoded = decode_frame(encoded)
    assert decoded.stream_id == ""


def test_empty_media_urn_allowed():
    """Test that empty media_urn is allowed (validation happens at protocol level)."""
    req_id = MessageId.new_uuid()
    frame = Frame.stream_start(req_id, "stream-1", "")

    assert frame.media_urn == ""

    # Should encode/decode successfully
    encoded = encode_frame(frame)
    decoded = decode_frame(encoded)
    assert decoded.media_urn == ""


def test_chunk_frame_with_stream_id():
    """Test that CHUNK frames can reference a stream_id."""
    req_id = MessageId.new_uuid()
    stream_id = "chunk-stream"

    # Create chunk with stream_id (Protocol v2: stream_id required)
    frame = Frame.chunk(req_id, stream_id, 0, b"test data", 0, compute_checksum(b"test data"))

    encoded = encode_frame(frame)
    decoded = decode_frame(encoded)

    assert decoded.frame_type == FrameType.CHUNK
    assert decoded.stream_id == stream_id


def test_all_frame_types_have_correct_values():
    """Verify all FrameType values are correct."""
    assert FrameType.HELLO == 0
    assert FrameType.REQ == 1
    # RES (2) removed in Protocol v2
    assert FrameType.CHUNK == 3
    assert FrameType.END == 4
    assert FrameType.LOG == 5
    assert FrameType.ERR == 6
    assert FrameType.HEARTBEAT == 7
    assert FrameType.STREAM_START == 8
    assert FrameType.STREAM_END == 9


def test_frame_type_from_u8_returns_stream_types():
    """Test FrameType.from_u8 recognizes stream frame types."""
    assert FrameType.from_u8(8) == FrameType.STREAM_START
    assert FrameType.from_u8(9) == FrameType.STREAM_END


def test_frame_type_from_u8_accepts_relay_frames():
    """Test FrameType.from_u8 accepts RELAY_NOTIFY (10) and RELAY_STATE (11)."""
    assert FrameType.from_u8(10) == FrameType.RELAY_NOTIFY
    assert FrameType.from_u8(11) == FrameType.RELAY_STATE


def test_frame_type_from_u8_rejects_12():
    """Test FrameType.from_u8 returns None for value 12 (one past RELAY_STATE)."""
    assert FrameType.from_u8(12) is None


@pytest.mark.asyncio
async def test_protocol_v2_handshake():
    """Test that handshake negotiates Protocol v2."""
    from capns.cbor_io import handshake, handshake_accept

    # Create host and plugin pipes
    host_to_plugin = io.BytesIO()
    plugin_to_host = io.BytesIO()

    # Host initiates handshake
    host_limits = Limits.default()

    # Write host HELLO to pipe
    from capns.cbor_frame import Frame
    hello_frame = Frame.hello(host_limits.max_frame, host_limits.max_chunk)
    from capns.cbor_io import write_frame

    write_frame(host_to_plugin, hello_frame, host_limits)
    host_to_plugin.seek(0)

    # Plugin responds with manifest
    manifest = b'{"name":"test","version":"1.0.0","caps":[]}'
    plugin_hello = Frame.hello_with_manifest(
        host_limits.max_frame, host_limits.max_chunk, manifest
    )
    write_frame(plugin_to_host, plugin_hello, host_limits)

    # Both should see version 2 in the frames
    assert hello_frame.version == 2
    assert plugin_hello.version == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
