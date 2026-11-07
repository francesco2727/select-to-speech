import subprocess
import sys
from unittest.mock import patch

from select_to_speech import entrypoint


def test_check_flag_forwards_remaining_args():
    with patch("select_to_speech.system_check.main_check", return_value=0) as m:
        assert entrypoint.dispatch(["--check", "--lang", "it"]) == 0
    m.assert_called_once_with(argv=["--lang", "it"])


def test_audio_devices_flag():
    with patch("select_to_speech.system_check.main_audio_devices", return_value=0) as m:
        assert entrypoint.dispatch(["--audio-devices"]) == 0
    m.assert_called_once_with([])


def test_download_flag_forwards_model():
    with patch("select_to_speech.voice_manager.download_kokoro_cli") as m:
        assert entrypoint.dispatch(["--download", "--model", "kokoro-int8-multi-lang-v1_0"]) == 0
    m.assert_called_once_with(["--model", "kokoro-int8-multi-lang-v1_0"])


def test_help_does_not_start_daemon(capsys):
    with patch("select_to_speech.main.main") as daemon:
        assert entrypoint.dispatch(["--help"]) == 0
    daemon.assert_not_called()
    assert "--check" in capsys.readouterr().out


def test_no_args_starts_daemon():
    with patch("select_to_speech.main.main", return_value=0) as daemon:
        assert entrypoint.dispatch([]) == 0
    daemon.assert_called_once()


def test_check_does_not_import_heavy_modules():
    """--check must stay fast: it must not pull in lingua or sherpa-onnx.

    Runs in a subprocess so the test does not disturb modules imported by other tests.
    """
    code = (
        "import sys\n"
        "from unittest.mock import patch\n"
        "from select_to_speech import entrypoint\n"
        "with patch('select_to_speech.system_check.check_system_dependencies', return_value=True):\n"
        "    entrypoint.dispatch(['--check'])\n"
        "heavy = [m for m in ('lingua', 'sherpa_onnx', 'select_to_speech.main') if m in sys.modules]\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
