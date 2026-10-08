from fastapi.testclient import TestClient

from protocol import messages
from server.app import create_app
from server.config import Settings


def speak(ws, text):
    ws.send_text(messages.encode(messages.TextTurn(text=text)))
    result, seen = "", []
    while True:
        frame = ws.receive()
        if frame.get("bytes") is not None:
            seen.append("audio")
            continue
        message = messages.decode_server(frame["text"])
        seen.append(message.t)
        if isinstance(message, messages.Reply):
            result = message.text
        elif isinstance(message, messages.SayEnd):
            ws.send_text(messages.encode(messages.Played()))
        elif isinstance(message, messages.Status) and message.phase == "idle":
            return result, seen


def test_app_reconnect_memory_and_usage(tmp_path):
    cfg = Settings(_env_file=None, data_dir=tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert client.get("/health").json()["ok"]
        with client.websocket_connect("/ws") as ws:
            ws.send_text("invalid json")
            ws.send_text(messages.encode(messages.Hello(dev="one")))
            assert messages.decode_server(ws.receive_text()).t == "ready"
            _, events = speak(ws, "My name is Mira")
            assert events.index("act") < events.index("audio")
    # Restart the whole application, not just its socket.
    with TestClient(create_app(cfg)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(messages.encode(messages.Hello(dev="two")))
            ws.receive_text()
            reply, _ = speak(ws, "What is my name?")
            assert "Mira" in reply
        assert client.get("/usage").json()["completed"] == 2


def test_app_rejects_unconfigured_cloud_without_request(tmp_path):
    cfg = Settings(
        _env_file=None, data_dir=tmp_path, stt="deepgram", deepgram_api_key=""
    )
    with TestClient(create_app(cfg)) as client:
        health = client.get("/health").json()
        assert health["ok"] is False
        with client.websocket_connect("/ws") as ws:
            frame = messages.decode_server(ws.receive_text())
            assert frame.reason == "configuration_missing"
