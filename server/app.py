"""Local pet server. One persistent journal and allowance shared by sessions."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from protocol import audio, messages
from server.config import make_llm, make_stt, make_tts, make_vad, settings
from server.memory import Memory
from server.session import Session
from server.storage import Store

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("pet.app")


def create_app(cfg=None):
    cfg = cfg or settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(cfg.data_dir / "pet.sqlite3")
        yield
        app.state.store.close()

    app = FastAPI(title="Robopet brain", lifespan=lifespan)

    @app.get("/health")
    async def health():
        issues = cfg.setup_issues()
        return {
            "app": "robopet-brain",
            "pet_id": cfg.pet_id,
            "ok": not issues,
            "issues": issues,
            "mode": cfg.mode,
            "name": cfg.name,
            "pipeline": {
                "stt": cfg.stt,
                "llm": cfg.llm,
                "tts": cfg.tts,
                "vad": cfg.vad,
            },
            "memory": cfg.memory,
            "cloud_enabled": cfg.uses_cloud,
            "audio": {"rate": audio.RATE, "frame_bytes": audio.FRAME_BYTES},
        }

    @app.get("/usage")
    async def usage():
        return app.state.store.summary(cfg.pet_id)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        session = None
        providers = []
        try:
            if cfg.setup_issues():
                await ws.send_text(
                    messages.encode(messages.Cancel(reason="configuration_missing"))
                )
                await ws.close(code=1013, reason="Run python -m clients.doctor")
                return
            # Construct inside cleanup scope, including partially created clients.
            memory = Memory(app.state.store, cfg)
            stt = make_stt(cfg)
            providers.append(stt)
            llm = make_llm(cfg)
            providers.append(llm)
            tts = make_tts(cfg)
            providers.append(tts)
            session = Session(
                ws,
                stt=stt,
                llm=llm,
                tts=tts,
                vad=make_vad(cfg),
                cfg=cfg,
                store=app.state.store,
                memory=memory,
            )
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (data := msg.get("bytes")) is not None:
                    await session.on_frame(data)
                elif (raw := msg.get("text")) is not None:
                    try:
                        frame = messages.decode_client(raw)
                    except ValueError:
                        log.warning("Invalid control message ignored")
                        continue
                    await session.dispatch(frame)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("Connection failed (%s); run setup doctor", type(exc).__name__)
            try:
                await ws.send_text(
                    messages.encode(messages.Cancel(reason="server_error"))
                )
                await ws.close(code=1011)
            except Exception:
                pass
        finally:
            if session:
                await session.close()
            else:
                for provider in providers:
                    if close := getattr(provider, "close", None):
                        await close()

    return app


app = create_app()


def main():
    import uvicorn

    cfg = settings()
    uvicorn.run("server.app:app", host=cfg.host, port=cfg.port, ws_max_size=64 * 1024)


if __name__ == "__main__":
    main()
