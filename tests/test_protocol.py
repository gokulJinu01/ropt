from protocol import audio, messages


def test_frame_math_matches_the_hardware():
    assert audio.FRAME_SAMPLES == 320
    assert audio.FRAME_BYTES == 640
    assert audio.duration_ms(b"\x00" * audio.FRAME_BYTES) == 20.0


def test_frames_drops_short_tail():
    buf = b"\x00" * (audio.FRAME_BYTES * 3 + 7)
    assert len(list(audio.frames(buf))) == 3


def test_client_frames_round_trip():
    for frame in (
        messages.Hello(dev="pet-01"),
        messages.UttStart(),
        messages.UttEnd(),
        messages.Played(),
    ):
        assert messages.decode_client(messages.encode(frame)) == frame


def test_server_frames_round_trip():
    for frame in (
        messages.Ready(),
        messages.Act(name="wiggle", dur_ms=800),
        messages.SayStart(),
        messages.SayEnd(),
        messages.Cancel(),
        messages.Heard(text="hello pip"),
    ):
        assert messages.decode_server(messages.encode(frame)) == frame


def test_ready_advertises_the_real_format():
    ready = messages.Ready()
    assert ready.fmt == audio.FORMAT
    assert ready.frame_bytes == audio.FRAME_BYTES
