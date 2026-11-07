"""Single CLI entry point for the select-to-speech binary.

Subcommands are selected by flag only (no argv[0]/symlink dispatch). Each branch
imports only what it needs, so e.g. ``--check`` never loads lingua or sherpa-onnx.
"""

import sys

USAGE = """\
Select-to-Speech daemon & backend server
Usage: select-to-speech [command] [options]

Commands:
  (none)             Start the backend daemon (normally launched by the GUI)
  --check            Run system dependency check (--lang en|it|fr|es)
  --audio-devices    List available audio output devices
  --download         Download Kokoro TTS model files (--model <id>)
  -h, --help         Show this help message and exit
"""


def dispatch(argv: list[str] | None = None) -> int:
    """Run the subcommand selected by ``argv`` (defaults to ``sys.argv[1:]``)."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--check" in args:
        args.remove("--check")
        from select_to_speech.system_check import main_check
        return main_check(argv=args)

    if "--audio-devices" in args:
        args.remove("--audio-devices")
        from select_to_speech.system_check import main_audio_devices
        return main_audio_devices(args)

    if "--download" in args:
        args.remove("--download")
        from select_to_speech.voice_manager import download_kokoro_cli
        download_kokoro_cli(args)
        return 0

    if "-h" in args or "--help" in args:
        print(USAGE, end="")
        return 0

    from select_to_speech.main import main
    return main()


if __name__ == "__main__":
    sys.exit(dispatch())
