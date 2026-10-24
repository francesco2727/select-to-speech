"""Standalone multi-call entry point for Nuitka packaging."""

import os
import sys
from pathlib import Path


def dispatch() -> int:
    """Dispatch to appropriate CLI function based on binary name or flags."""
    prog_names = {Path(sys.argv[0]).name} if sys.argv else {"select-to-speech"}
    onefile_bin = os.environ.get("NUITKA_ONEFILE_BINARY")
    if onefile_bin:
        prog_names.add(Path(onefile_bin).name)

    if "select-to-speech-check" in prog_names or "--check" in sys.argv:
        if "--check" in sys.argv:
            sys.argv.remove("--check")
        from select_to_speech.system_check import main_check
        return main_check()

    if "select-to-speech-audio" in prog_names or "--audio-devices" in sys.argv:
        if "--audio-devices" in sys.argv:
            sys.argv.remove("--audio-devices")
        from select_to_speech.system_check import main_audio_devices
        return main_audio_devices()

    if "select-to-speech-download" in prog_names or "--download" in sys.argv:
        if "--download" in sys.argv:
            sys.argv.remove("--download")
        from select_to_speech.voice_manager import download_kokoro_cli
        download_kokoro_cli()
        return 0

    if len(sys.argv) > 1 and any(a in sys.argv for a in ("-h", "--help")):
        print("Select-to-Speech daemon & backend server")
        print("Usage: select-to-speech [options]")
        print("\nOptions:")
        print("  -h, --help         Show this help message and exit")
        print("  --check            Run system dependency check")
        print("  --audio-devices    List available audio output devices")
        print("  --download         Download Kokoro TTS model files")
        return 0

    from select_to_speech.main import main
    return main()


if __name__ == "__main__":
    sys.exit(dispatch())
