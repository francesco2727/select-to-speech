import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from select_to_speech.main import SelectToSpeechApp
from select_to_speech.config import load_config, save_config, AppConfig

logger = logging.getLogger(__name__)

# Global app instance
sts_app: SelectToSpeechApp = None

@asynccontextmanager
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
    return {"status": "ok", "playing": sts_app.audio_player.is_playing if sts_app else False}

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

# Download state variables
download_status = "idle"
download_progress = 0
download_total_bytes = -1
download_downloaded_bytes = 0
download_error = None

def run_download_thread(force: bool):
    global download_status, download_progress, download_total_bytes, download_downloaded_bytes, download_error
    download_status = "downloading"
    download_progress = 0
    download_error = None
    
    from select_to_speech.voice_manager import download_kokoro
    
    def progress_cb(downloaded: int, total: int):
        global download_progress, download_total_bytes, download_downloaded_bytes
        download_downloaded_bytes = downloaded
        download_total_bytes = total
        if total > 0:
            download_progress = int((downloaded / total) * 100)
        else:
            download_progress = 0
            
    try:
        success = download_kokoro(force=force, progress_cb=progress_cb)
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
def start_download(force: bool = True):
    global download_status
    if download_status == "downloading":
        return {"status": "already_downloading"}
    
    import threading
    thread = threading.Thread(target=run_download_thread, args=(force,), daemon=True)
    thread.start()
    return {"status": "started"}

@app.get("/download_status")
def get_download_status():
    global download_status, download_progress, download_total_bytes, download_downloaded_bytes, download_error
    return {
        "status": download_status,
        "progress": download_progress,
        "downloaded_bytes": download_downloaded_bytes,
        "total_bytes": download_total_bytes,
        "error": download_error
    }

@app.get("/voices")
def get_voices():
    from select_to_speech.tts_engine import _KOKORO_LANG_PREFIXES, get_kokoro_voices
    
    fallback_voices = {
        "en": [
            "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
            "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
            "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
            "bm_daniel", "bm_fable", "bm_george", "bm_lewis"
        ],
        "es": ["ef_dora", "em_alex", "em_santa"],
        "fr": ["ff_siwis"],
        "hi": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
        "it": ["if_sara", "im_nicola"],
        "ja": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
        "ko": [],
        "pt": ["pf_dora", "pm_alex", "pm_santa"],
        "zh": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"]
    }
    
    dynamic_voices = {}
    for lang in _KOKORO_LANG_PREFIXES.keys():
        voices = get_kokoro_voices(lang)
        if voices:
            dynamic_voices[lang] = voices
            
    return dynamic_voices if dynamic_voices else fallback_voices

@app.get("/ocr_languages")
def get_ocr_languages():
    if sts_app:
        langs = list(sts_app.ocr_engine.get_available_languages())
        langs.sort()
        return langs
    return []


def run_server():
    socket_path = os.path.expanduser("~/.local/state/select-to-speech/ipc.sock")
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)
    if os.path.exists(socket_path):
        try:
            os.remove(socket_path)
        except OSError:
            pass
    
    logger.info(f"Starting API server on UDS: {socket_path}")
    config = uvicorn.Config(app, uds=socket_path)
    server = uvicorn.Server(config)
    
    import signal as _signal
    original_sigterm = _signal.getsignal(_signal.SIGTERM)
    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM, initiating graceful shutdown...")
        server.should_exit = True
        if callable(original_sigterm) and original_sigterm not in (_signal.SIG_DFL, _signal.SIG_IGN):
            original_sigterm(signum, frame)
    _signal.signal(_signal.SIGTERM, _handle_sigterm)
    
    server.run()
