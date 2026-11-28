import contextlib
import logging
import os
import signal
import socket
import threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from select_to_speech.main import SelectToSpeechApp
from select_to_speech.config import load_config, save_config, AppConfig

logger = logging.getLogger(__name__)

# Global app instance
sts_app: SelectToSpeechApp = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global sts_app
    logger.info("Starting Select-to-Speech Core...")
    sts_app = SelectToSpeechApp()
    # Start listeners (they run in background threads within SelectToSpeechApp)
    sts_app.selection_listener.start()
    sts_app.keyboard_handler.start()

    yield

    logger.info("Shutting down Select-to-Speech Core...")
    if sts_app:
        sts_app.shutdown()


app = FastAPI(lifespan=lifespan)


class SpeakRequest(BaseModel):
    text: str


@app.get("/status")
def get_status():
    return {
        "status": "ok",
        "playing": sts_app.audio_player.is_playing if sts_app else False,
    }


@app.post("/speak")
def speak(req: SpeakRequest):
    if not sts_app:
        raise HTTPException(status_code=500, detail="App not initialized")
    sts_app._on_text_selected(req.text)
    return {"status": "started"}


@app.post("/stop")
def stop():
    if sts_app:
        sts_app._on_stop_pressed()
    return {"status": "stopped"}


@app.post("/pause")
def pause():
    if sts_app:
        sts_app._on_pause_pressed()
    return {"status": "paused_or_resumed"}


@app.post("/ocr_capture")
def ocr_capture():
    if sts_app:
        sts_app._on_ocr_pressed()
    return {"status": "ocr_started"}


@app.get("/config")
def get_config():
    if sts_app:
        return sts_app.config.model_dump()
    return load_config().model_dump()


@app.post("/config")
def update_config(new_config: dict):
    config = AppConfig(**new_config)
    save_config(config)
    if sts_app:
        sts_app.reload_config(config)
    return {"status": "updated"}


@app.get("/audio_devices")
def get_audio_devices_endpoint():
    from select_to_speech.system_check import get_audio_devices

    try:
        return get_audio_devices()
    except Exception as e:
        logger.error(f"Error getting audio devices: {e}")
        return []


@app.get("/hardware")
def get_hardware_endpoint():
    from select_to_speech.system_check import get_hardware_info

    try:
        return get_hardware_info()
    except Exception as e:
        logger.error(f"Error getting hardware info: {e}")
        return {"cpu_model": "Unknown CPU", "total_threads": 1, "optimal_threads": 1}


# Download state variables (one download at a time, Kokoro model or Piper voice)
download_status = "idle"
download_progress = 0
download_total_bytes = -1
download_downloaded_bytes = 0
download_error = None
download_engine = None
download_model_id = None
download_precision = None


def _piper_precision(precision: str | None) -> str:
    from select_to_speech.voice_manager import DEFAULT_PIPER_PRECISION, PIPER_PRECISIONS

    if precision in PIPER_PRECISIONS:
        return precision
    if sts_app:
        return sts_app.config.voice.piper_precision
    return DEFAULT_PIPER_PRECISION


def run_download_thread(
    model_id: str, force: bool, engine: str = "kokoro", precision: str | None = None
):
    global \
        download_status, \
        download_progress, \
        download_total_bytes, \
        download_downloaded_bytes, \
        download_error
    download_status = "downloading"
    download_progress = 0
    download_error = None

    from select_to_speech.voice_manager import download_kokoro, download_piper

    def progress_cb(downloaded: int, total: int):
        global download_progress, download_total_bytes, download_downloaded_bytes
        download_downloaded_bytes = downloaded
        download_total_bytes = total
        download_progress = int((downloaded / total) * 100) if total > 0 else 0

    try:
        if engine == "piper":
            success = download_piper(
                model_id, precision or "int8", force=force, progress_cb=progress_cb
            )
        else:
            success = download_kokoro(
                model_id=model_id, force=force, progress_cb=progress_cb
            )
        if success:
            download_status = "success"
            download_progress = 100
        else:
            download_status = "failed"
            download_error = "Failed to download model files."
    except Exception as e:
        download_status = "failed"
        download_error = str(e)


@app.post("/download_model")
def start_download(
    model_id: str = "kokoro-multi-lang-v1_0",
    force: bool = True,
    engine: str = "kokoro",
    precision: str | None = None,
):
    global download_status, download_engine, download_model_id, download_precision
    if download_status == "downloading":
        return {"status": "already_downloading"}
    if engine not in ("kokoro", "piper"):
        raise HTTPException(status_code=400, detail=f"Unknown engine '{engine}'")

    from select_to_speech.voice_manager import parse_voice_ref, resolve_piper_precision

    if engine == "piper":
        model_id, _ = parse_voice_ref(model_id)
        precision = resolve_piper_precision(model_id, _piper_precision(precision))
    else:
        precision = None

    download_engine, download_model_id, download_precision = engine, model_id, precision
    # Set before the thread starts so an immediate /download_status poll sees it
    download_status = "downloading"
    threading.Thread(
        target=run_download_thread,
        args=(model_id, force, engine, precision),
        daemon=True,
    ).start()
    return {"status": "started"}


@app.get("/download_status")
def get_download_status():
    return {
        "status": download_status,
        "progress": download_progress,
        "downloaded_bytes": download_downloaded_bytes,
        "total_bytes": download_total_bytes,
        "error": download_error,
        "engine": download_engine,
        "model_id": download_model_id,
        "precision": download_precision,
    }


@app.get("/engines")
def get_engines():
    from select_to_speech.voice_manager import DEFAULT_PIPER_PRECISION, PIPER_PRECISIONS

    return [
        {"id": "kokoro", "name": "Kokoro"},
        {
            "id": "piper",
            "name": "Piper",
            "precisions": list(PIPER_PRECISIONS),
            "default_precision": DEFAULT_PIPER_PRECISION,
        },
    ]


@app.get("/voices")
def get_voices(engine: str = "kokoro", precision: str | None = None):
    """Voices per language for an engine; languages without voices are omitted.

    Shape: ``{lang: [{"id", "name", "quality", "precision", "size_bytes", "installed", "speakers"}]}``.
    Kokoro voices are speakers of one model, so their size/installed fields are null.
    """
    if engine == "piper":
        from select_to_speech.voice_manager import get_piper_languages, get_piper_voices

        precision = _piper_precision(precision)
        return {
            lang: get_piper_voices(lang, precision) for lang in get_piper_languages()
        }

    from select_to_speech.tts_engine import kokoro_languages, get_kokoro_voices

    return {
        lang: [
            {
                "id": v,
                "name": v,
                "quality": None,
                "precision": None,
                "size_bytes": None,
                "installed": None,
                "speakers": [],
            }
            for v in get_kokoro_voices(lang)
        ]
        for lang in kokoro_languages()
    }


@app.get("/ocr_languages")
def get_ocr_languages():
    if sts_app:
        return sorted(sts_app.ocr_engine.get_available_languages())
    return []


@app.get("/ocr_status")
def get_ocr_status():
    """Whether Tesseract is installed, and which language packs it has."""
    if sts_app:
        engine = sts_app.ocr_engine
        installed = engine.is_available()
        langs = sorted(engine.get_available_languages()) if installed else []
        return {"installed": installed, "languages": langs}
    return {"installed": False, "languages": []}


@app.get("/model_installed")
def get_model_installed(
    model_id: str = "kokoro-multi-lang-v1_0",
    engine: str = "kokoro",
    precision: str | None = None,
):
    from select_to_speech.voice_manager import (
        is_kokoro_installed,
        is_piper_installed,
        parse_voice_ref,
    )

    if engine == "piper":
        key, _ = parse_voice_ref(model_id)
        return {"installed": is_piper_installed(key, _piper_precision(precision))}
    return {"installed": is_kokoro_installed(model_id)}


@app.get("/available_models")
def get_available_models():
    from select_to_speech.voice_manager import KOKORO_MODELS, is_kokoro_installed
    from select_to_speech.tts_engine import kokoro_languages

    supported_langs = kokoro_languages()
    return [
        {
            "id": mid,
            "name": info["name"],
            "size_mb": info["size_mb"],
            "installed": is_kokoro_installed(mid),
            "supported_languages": supported_langs,
        }
        for mid, info in KOKORO_MODELS.items()
    ]


@app.get("/installed_models")
def get_installed_models():
    """Downloaded Kokoro models and Piper voices, with disk usage and whether they are in use."""
    from select_to_speech.voice_manager import list_installed_models, parse_voice_ref

    in_use: set[tuple[str, str, str | None]] = set()
    if sts_app:
        voice = sts_app.config.voice
        in_use.add(("kokoro", voice.model, None))
        for ref in voice.piper_language_models.values():
            if ref:
                in_use.add(("piper", parse_voice_ref(ref)[0], voice.piper_precision))
    models = list_installed_models()
    for m in models:
        m["in_use"] = (m["engine"], m["id"], m["precision"]) in in_use
    return models


@app.delete("/installed_models")
def delete_installed_model(engine: str, model_id: str, precision: str | None = None):
    from select_to_speech.voice_manager import delete_kokoro, delete_piper

    if download_status == "downloading" and (download_engine, download_model_id) == (
        engine,
        model_id,
    ):
        raise HTTPException(status_code=409, detail="This model is being downloaded")
    if engine == "piper":
        precision = _piper_precision(precision)
        deleted = delete_piper(model_id, precision)
    elif engine == "kokoro":
        deleted = delete_kokoro(model_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engine '{engine}'")
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not installed")
    if sts_app:
        sts_app.tts_engine.release_model(engine, model_id, precision)
    return {"status": "deleted"}


# Punctuation download state variables
punct_download_status = "idle"
punct_download_progress = 0
punct_download_error = None


def run_punct_download_thread():
    global punct_download_status, punct_download_progress, punct_download_error
    punct_download_status = "downloading"
    punct_download_progress = 0
    punct_download_error = None

    from select_to_speech.punctuation_engine import download_punct_model

    def progress_cb(downloaded: int, total: int):
        global punct_download_progress
        punct_download_progress = int((downloaded / total) * 100) if total > 0 else 0

    try:
        success = download_punct_model(force=True, progress_cb=progress_cb)
        if success:
            punct_download_status = "success"
            punct_download_progress = 100
        else:
            punct_download_status = "failed"
            punct_download_error = "Failed to download punctuation model."
    except Exception as e:
        punct_download_status = "failed"
        punct_download_error = str(e)


@app.get("/punctuation_status")
def get_punctuation_status():
    from select_to_speech.punctuation_engine import (
        is_punct_model_installed,
        PUNCT_MODEL_INFO,
    )

    return {
        "installed": is_punct_model_installed(),
        "model_name": PUNCT_MODEL_INFO["name"],
        "supported_languages": PUNCT_MODEL_INFO["supported_languages"],
        "download_status": punct_download_status,
        "download_progress": punct_download_progress,
        "download_error": punct_download_error,
    }


@app.post("/download_punctuation")
def start_punctuation_download():
    if punct_download_status == "downloading":
        return {"status": "already_downloading"}

    threading.Thread(target=run_punct_download_thread, daemon=True).start()
    return {"status": "started"}


def is_server_running(socket_path: str) -> bool:
    """Check if a backend server instance is already running and responding."""
    if not os.path.exists(socket_path):
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        sock.connect(socket_path)
        sock.sendall(
            b"GET /status HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        response = sock.recv(1024)
        return bool(b"200 OK" in response or b"status" in response)
    except OSError:
        return False
    finally:
        sock.close()


def run_server() -> int:
    socket_path = os.path.expanduser("~/.local/state/select-to-speech/ipc.sock")
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    if is_server_running(socket_path):
        logger.info(
            "Select-to-Speech backend server is already running. Exiting cleanly."
        )
        return 0

    with contextlib.suppress(OSError):
        os.remove(socket_path)

    logger.info(f"Starting API server on UDS: {socket_path}")
    config = uvicorn.Config(app, uds=socket_path)
    server = uvicorn.Server(config)

    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM, initiating graceful shutdown...")
        server.should_exit = True
        if callable(original_sigterm) and original_sigterm not in (
            signal.SIG_DFL,
            signal.SIG_IGN,
        ):
            original_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    server.run()
    return 0
