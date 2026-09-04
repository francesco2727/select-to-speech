"""Audio playback using PyAudio"""

import io
import logging
import math
import os
import queue
import threading
import traceback
from typing import Optional, Any, Dict

import pyaudio
import wave
import numpy as np
import sys
from pedalboard import Pedalboard, PitchShift

pulsectl = None
if sys.platform == "linux":
    try:
        import pulsectl
    except Exception:
        pulsectl = None

pycaw_available = False
AudioUtilities = None
ISimpleAudioVolume = None
if sys.platform == "win32":
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        pycaw_available = True
    except Exception:
        pycaw_available = False

logger = logging.getLogger(__name__)


class BaseAudioDucker:
    """Base interface for platform-specific audio duckers."""

    def __init__(self, duck_volume: float = 0.2):
        self.duck_volume = duck_volume
        self._original_volumes: dict[Any, Any] = {}

    def duck(self, duck_volume: float) -> dict[Any, Any]:
        """Duck background audio volumes and return map of original volumes."""
        return {}

    def unduck(self) -> None:
        """Restore background audio volumes to original values."""
        self._original_volumes.clear()

    def ensure_own_volume_max(self) -> None:
        """Ensure current process audio volume is set to 100%."""
        pass


class PulseAudioDucker(BaseAudioDucker):
    """Audio ducker implementation for Linux using pulsectl."""

    def __init__(self, duck_volume: float = 0.2):
        super().__init__(duck_volume)
        self._original_volumes: dict[int, list[float]] = {}

    def duck(self, duck_volume: float) -> dict[int, list[float]]:
        if not pulsectl:
            return {}

        pulse = None
        try:
            pulse = pulsectl.Pulse('select-to-speech-ducker')
            my_pid = os.getpid()
            sink_inputs = pulse.sink_input_list()

            for sink_input in sink_inputs:
                pid_str = sink_input.proplist.get('application.process.id')
                app_name = sink_input.proplist.get('application.name', '').lower()

                if pid_str and str(pid_str) == str(my_pid):
                    continue
                if 'python' in app_name or 'select-to-speech' in app_name:
                    continue

                if sink_input.index not in self._original_volumes:
                    self._original_volumes[sink_input.index] = pulse.volume_get_all_chans(sink_input)

                pulse.volume_set_all_chans(sink_input, duck_volume)
            return self._original_volumes
        except Exception as e:
            logger.warning(f"Failed to duck audio via pulsectl: {e}")
            return self._original_volumes
        finally:
            if pulse:
                try:
                    pulse.close()
                except Exception:
                    pass

    def unduck(self) -> None:
        if not pulsectl or not self._original_volumes:
            self._original_volumes.clear()
            return

        pulse = None
        try:
            pulse = pulsectl.Pulse('select-to-speech-unducker')
            for sink_input in pulse.sink_input_list():
                if sink_input.index in self._original_volumes:
                    pulse.volume_set_all_chans(sink_input, self._original_volumes[sink_input.index])
        except Exception as e:
            logger.warning(f"Failed to restore audio volume via pulsectl: {e}")
        finally:
            self._original_volumes.clear()
            if pulse:
                try:
                    pulse.close()
                except Exception:
                    pass

    def ensure_own_volume_max(self) -> None:
        if not pulsectl:
            return
        pulse = None
        try:
            pulse = pulsectl.Pulse('select-to-speech-vol-fix')
            my_pid = os.getpid()
            for sink_input in pulse.sink_input_list():
                pid_str = sink_input.proplist.get('application.process.id')
                app_name = sink_input.proplist.get('application.name', '').lower()

                is_ours = False
                if pid_str and str(pid_str) == str(my_pid):
                    is_ours = True
                if 'python' in app_name or 'select-to-speech' in app_name:
                    is_ours = True

                if is_ours:
                    pulse.volume_set_all_chans(sink_input, 1.0)
        except Exception as e:
            logger.warning(f"Failed to restore own audio volume via pulsectl: {e}")
        finally:
            if pulse:
                try:
                    pulse.close()
                except Exception:
                    pass


class WindowsAudioDucker(BaseAudioDucker):
    """Audio ducker implementation for Windows using pycaw / Core Audio APIs."""

    def __init__(self, duck_volume: float = 0.2):
        super().__init__(duck_volume)
        self._original_volumes: dict[Any, float] = {}

    @staticmethod
    def _init_com() -> None:
        """Initialize COM for the current thread using multithreaded apartment (MTA)."""
        try:
            import ctypes
            # COINIT_MULTITHREADED = 0x0
            COINIT_MULTITHREADED = 0x0
            hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
            # S_OK = 0, S_FALSE = 1, RPC_E_CHANGED_MODE = 0x80010106
        except Exception:
            try:
                import ctypes
                ctypes.windll.ole32.CoInitialize(None)
            except Exception:
                pass

    @staticmethod
    def _uninit_com() -> None:
        """Uninitialize COM for the current thread."""
        try:
            import ctypes
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass

    def _get_session_info(self, session: Any) -> tuple[Optional[int], str, Optional[Any]]:
        """Extract PID, process name, and SimpleAudioVolume control from a pycaw session."""
        proc_pid: Optional[int] = None
        proc_name: str = ""
        try:
            proc = getattr(session, 'Process', None)
            if proc is not None:
                try:
                    proc_pid = proc.pid
                    proc_name = (proc.name() or "").lower()
                except Exception:
                    pass
            elif hasattr(session, 'ProcessId') and session.ProcessId:
                proc_pid = session.ProcessId
        except Exception:
            pass

        volume_ctl = None
        try:
            volume_ctl = getattr(session, 'SimpleAudioVolume', None)
            if volume_ctl is None and ISimpleAudioVolume is not None and hasattr(session, '_ctl'):
                volume_ctl = session._ctl.QueryInterface(ISimpleAudioVolume)
        except Exception:
            pass

        return proc_pid, proc_name, volume_ctl

    def _is_our_process(self, proc_pid: Optional[int], proc_name: str) -> bool:
        my_pid = os.getpid()
        if proc_pid is not None and proc_pid == my_pid:
            return True
        if "python" in proc_name or "select-to-speech" in proc_name or "select_to_speech" in proc_name:
            return True
        return False

    def duck(self, duck_volume: float) -> dict[Any, float]:
        if not pycaw_available or AudioUtilities is None:
            return {}

        self._init_com()
        try:
            sessions = AudioUtilities.GetAllSessions()
            for idx, session in enumerate(sessions):
                try:
                    proc_pid, proc_name, volume_ctl = self._get_session_info(session)
                    if volume_ctl is None:
                        continue
                    if self._is_our_process(proc_pid, proc_name):
                        continue

                    session_key = proc_pid if proc_pid is not None else f"session_{idx}_{getattr(session, 'DisplayName', '')}"
                    if session_key not in self._original_volumes:
                        current_vol = volume_ctl.GetMasterVolume()
                        self._original_volumes[session_key] = current_vol

                    volume_ctl.SetMasterVolume(duck_volume, None)
                except Exception as e:
                    logger.debug(f"Failed to duck individual Windows session: {e}")
            return self._original_volumes
        except Exception as e:
            logger.warning(f"Failed to duck Windows audio sessions: {e}")
            return self._original_volumes
        finally:
            self._uninit_com()

    def unduck(self) -> None:
        if not pycaw_available or AudioUtilities is None or not self._original_volumes:
            self._original_volumes.clear()
            return

        self._init_com()
        try:
            sessions = AudioUtilities.GetAllSessions()
            for idx, session in enumerate(sessions):
                try:
                    proc_pid, proc_name, volume_ctl = self._get_session_info(session)
                    if volume_ctl is None:
                        continue
                    session_key = proc_pid if proc_pid is not None else f"session_{idx}_{getattr(session, 'DisplayName', '')}"
                    if session_key in self._original_volumes:
                        volume_ctl.SetMasterVolume(self._original_volumes[session_key], None)
                except Exception as e:
                    logger.debug(f"Failed to restore individual Windows session volume: {e}")
        except Exception as e:
            logger.warning(f"Failed to restore Windows audio sessions: {e}")
        finally:
            self._original_volumes.clear()
            self._uninit_com()

    def ensure_own_volume_max(self) -> None:
        if not pycaw_available or AudioUtilities is None:
            return

        self._init_com()
        try:
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                try:
                    proc_pid, proc_name, volume_ctl = self._get_session_info(session)
                    if volume_ctl is None:
                        continue
                    if self._is_our_process(proc_pid, proc_name):
                        volume_ctl.SetMasterVolume(1.0, None)
                except Exception as e:
                    logger.debug(f"Failed to maximize own Windows audio session: {e}")
        except Exception as e:
            logger.warning(f"Failed to maximize own Windows audio session: {e}")
        finally:
            self._uninit_com()


class AudioDucker:
    """Manages lowering background audio volumes asynchronously via a dedicated worker queue."""

    def __init__(self, duck_volume: float = 0.2):
        self.duck_volume = duck_volume
        self.enabled = True
        self._queue: queue.Queue = queue.Queue()
        self._backend: BaseAudioDucker
        if sys.platform == "win32":
            self._backend = WindowsAudioDucker(duck_volume=self.duck_volume)
        elif sys.platform == "linux":
            self._backend = PulseAudioDucker(duck_volume=self.duck_volume)
        else:
            self._backend = BaseAudioDucker(duck_volume=self.duck_volume)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AudioDucker-Worker"
        )
        self._worker_thread.start()

    @property
    def _original_volumes(self) -> dict[Any, Any]:
        return getattr(self._backend, "_original_volumes", {})

    @property
    def is_available(self) -> bool:
        if sys.platform == "win32":
            return pycaw_available
        elif sys.platform == "linux":
            return pulsectl is not None
        return False

    def _worker_loop(self) -> None:
        """Dedicated background loop that serializes all audio ducking operations safely."""
        while True:
            action = self._queue.get()
            try:
                if action == "start":
                    self._do_duck()
                elif action == "stop":
                    self._do_unduck()
                elif action == "ensure_max":
                    self._do_ensure_own_volume_max()
            except Exception as e:
                logger.warning(f"AudioDucker action '{action}' failed: {e}")
            finally:
                self._queue.task_done()

    def _do_duck(self) -> None:
        if not self.enabled or not self.is_available:
            return
        self._backend.duck(self.duck_volume)

    def _do_unduck(self) -> None:
        if not self.is_available:
            self._backend.unduck()
            return
        self._backend.unduck()

    def _do_ensure_own_volume_max(self) -> None:
        if not self.enabled or not self.is_available:
            return
        self._backend.ensure_own_volume_max()

    def start_ducking(self) -> None:
        """Enqueue ducking request."""
        if not self.enabled or not self.is_available:
            return
        self._queue.put("start")

    def stop_ducking(self) -> None:
        """Enqueue volume restoration request."""
        if not self.enabled or not self.is_available:
            return
        self._queue.put("stop")

    def ensure_own_volume_max(self) -> None:
        """Enqueue stream volume maximization request."""
        if not self.enabled or not self.is_available:
            return
        self._queue.put("ensure_max")


class AudioPlayer:
    """Audio playback handler using PyAudio"""

    def __init__(self, device_id: Optional[int] = None):
        self._device_id = device_id
        self._cached_devices: Optional[list[Optional[int]]] = None
        self._device_lock = threading.Lock()
        self.ducker = AudioDucker()
        self.ducker.enabled = False
        self.pyaudio = pyaudio.PyAudio()
        self.stream = None
        self.is_playing = False
        self._stop_requested = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stream_lock = threading.Lock()
        self._play_lock = threading.Lock()

    @property
    def device_id(self) -> Optional[int]:
        with self._device_lock:
            return self._device_id

    @device_id.setter
    def device_id(self, value: Optional[int]) -> None:
        with self._device_lock:
            if self._device_id != value:
                self._device_id = value
                self._cached_devices = None

    def invalidate_device_cache(self) -> None:
        with self._device_lock:
            self._cached_devices = None

    def _list_devices(self) -> None:
        try:
            device_count = self.pyaudio.get_device_count()
            logger.info(f"Available audio devices ({device_count} total):")
            for i in range(device_count):
                info = self.pyaudio.get_device_info_by_index(i)
                logger.info(f"  {i}: {info['name']} (channels: {info['maxOutputChannels']})")
        except Exception as e:
            logger.warning(f"Error listing audio devices: {e}")

    def _get_device_name(self, device_id: Optional[int]) -> str:
        """Get the name of an audio device"""
        if device_id is None:
            return "default/auto"
        try:
            info = self.pyaudio.get_device_info_by_index(device_id)
            return info['name']
        except Exception:
            return "unknown"

    def _find_output_devices(self, force_refresh: bool = False) -> list[Optional[int]]:
        with self._device_lock:
            if not force_refresh and self._cached_devices is not None:
                return list(self._cached_devices)

            devices: list[Optional[int]] = []
            if self._device_id is not None:
                devices.append(self._device_id)

            # Try default output device index first
            try:
                default_info = self.pyaudio.get_default_output_device_info()
                if default_info and "index" in default_info:
                    devices.append(default_info["index"])
            except Exception:
                pass

            pipewire_ids: list[int] = []
            pulse_ids: list[int] = []
            other_ids: list[int] = []

            try:
                device_count = self.pyaudio.get_device_count()
                for i in range(device_count):
                    try:
                        info = self.pyaudio.get_device_info_by_index(i)
                        if info.get("maxOutputChannels", 0) <= 0:
                            continue
                        name = info.get("name", "").lower()
                        if "pipewire" in name:
                            pipewire_ids.append(i)
                        elif "pulse" in name:
                            pulse_ids.append(i)
                        else:
                            other_ids.append(i)
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Error scanning audio devices: {e}")

            devices.extend(pipewire_ids)
            devices.extend(pulse_ids)
            devices.extend(other_ids)
            devices.append(None)  # Default fallback

            seen: set[Optional[int]] = set()
            unique: list[Optional[int]] = []
            for d in devices:
                if d not in seen:
                    seen.add(d)
                    unique.append(d)

            self._cached_devices = unique
            return list(self._cached_devices)

    def _open_stream_with_fallback(self, sample_width: int, n_channels: int, frame_rate: int) -> bool:
        """Open a PyAudio output stream using cached devices, falling back to a fresh scan on failure."""
        devices = self._find_output_devices(force_refresh=False)
        for attempt in (1, 2):
            for dev_id in devices:
                try:
                    with self._stream_lock:
                        self.stream = self.pyaudio.open(
                            format=self.pyaudio.get_format_from_width(sample_width),
                            channels=n_channels,
                            rate=frame_rate,
                            output=True,
                            output_device_index=dev_id,
                        )
                    return True
                except Exception:
                    continue
            if attempt == 1:
                devices = self._find_output_devices(force_refresh=True)
        return False

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def pause(self) -> None:
        self._pause_event.clear()
        logger.info("Playback paused")

    def resume(self) -> None:
        self._pause_event.set()
        logger.info("Playback resumed")

    def play(self, audio_data: bytes, sample_rate: int, channels: int = 1, pitch: float = 1.0) -> bool:
        if not audio_data:
            logger.error("No audio data provided")
            return False

        with self._play_lock:
            self.is_playing = True
            self._stop_requested = False
            self.ducker.start_ducking()
            try:
                audio_buffer = io.BytesIO(audio_data)
                with wave.open(audio_buffer, "rb") as wav_file:
                    n_channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    frame_rate = wav_file.getframerate()
                    frames = wav_file.readframes(wav_file.getnframes())

                if not frames:
                    logger.error("No audio frames extracted from WAV data")
                    return False

                if pitch != 1.0 and sample_width == 2:
                    try:
                        audio_int16 = np.frombuffer(frames, dtype=np.int16)
                        audio_float = audio_int16.astype(np.float32) / 32768.0
                        semitones = 12 * math.log2(pitch)
                        board = Pedalboard([PitchShift(semitones=semitones)])
                        processed_audio = board(audio_float, sample_rate=frame_rate, reset=False)
                        processed_int16 = (processed_audio * 32767.0).astype(np.int16)
                        frames = processed_int16.tobytes()
                    except Exception as e:
                        logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)

                if not self._open_stream_with_fallback(sample_width, n_channels, frame_rate):
                    logger.error("❌ All audio devices are busy or unavailable.")
                    self._list_devices()
                    return False

                self.ducker.ensure_own_volume_max()

                chunk_size = 4096
                for i in range(0, len(frames), chunk_size):
                    if self._stop_requested:
                        break
                    self._pause_event.wait()
                    if self._stop_requested:
                        break

                    chunk = frames[i:i + chunk_size]
                    if len(chunk) < chunk_size:
                        chunk = chunk + b'\x00' * (chunk_size - len(chunk))

                    with self._stream_lock:
                        if self.stream and not self._stop_requested:
                            self.stream.write(chunk)

                return not self._stop_requested

            except Exception as e:
                logger.error(f"Playback error: {e}", exc_info=True)
                return False
            finally:
                with self._stream_lock:
                    if self.stream:
                        try:
                            self.stream.stop_stream()
                            self.stream.close()
                        except Exception:
                            pass
                        self.stream = None
                self.is_playing = False
                self.ducker.stop_ducking()

    def play_stream(self, audio_generator_queue, pitch: float = 1.0) -> bool:
        with self._play_lock:
            self.is_playing = True
            self._stop_requested = False
            self.ducker.start_ducking()
            stream_opened = False

            try:
                while not self._stop_requested:
                    chunk_data = audio_generator_queue.get()
                    if chunk_data is None:
                        break

                    audio_data, sample_rate = chunk_data
                    if not audio_data:
                        continue

                    audio_buffer = io.BytesIO(audio_data)
                    with wave.open(audio_buffer, "rb") as wav_file:
                        n_channels = wav_file.getnchannels()
                        sample_width = wav_file.getsampwidth()
                        frame_rate = wav_file.getframerate()
                        frames = wav_file.readframes(wav_file.getnframes())

                    if not frames:
                        continue

                    if pitch != 1.0 and sample_width == 2:
                        try:
                            audio_int16 = np.frombuffer(frames, dtype=np.int16)
                            audio_float = audio_int16.astype(np.float32) / 32768.0
                            semitones = 12 * math.log2(pitch)
                            board = Pedalboard([PitchShift(semitones=semitones)])
                            processed_audio = board(audio_float, sample_rate=frame_rate, reset=False)
                            processed_int16 = (processed_audio * 32767.0).astype(np.int16)
                            frames = processed_int16.tobytes()
                        except Exception as e:
                            logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)

                    if not stream_opened:
                        if not self._open_stream_with_fallback(sample_width, n_channels, frame_rate):
                            logger.error("❌ All audio devices are busy or unavailable.")
                            return False
                        stream_opened = True
                        self.ducker.ensure_own_volume_max()

                    chunk_size = 4096
                    for i in range(0, len(frames), chunk_size):
                        if self._stop_requested:
                            break
                        self._pause_event.wait()
                        if self._stop_requested:
                            break

                        chunk = frames[i:i + chunk_size]
                        if len(chunk) < chunk_size:
                            chunk = chunk + b'\x00' * (chunk_size - len(chunk))

                        with self._stream_lock:
                            if self.stream and not self._stop_requested:
                                self.stream.write(chunk)

                return not self._stop_requested

            except Exception as e:
                logger.error(f"Fatal stream playback error: {e}", exc_info=True)
                return False
            finally:
                with self._stream_lock:
                    if self.stream:
                        try:
                            self.stream.stop_stream()
                            self.stream.close()
                        except Exception:
                            pass
                        self.stream = None
                self.is_playing = False
                self.ducker.stop_ducking()

    def stop(self) -> None:
        self._stop_requested = True
        self._pause_event.set()
        logger.info("Audio player stop requested")

    def __del__(self) -> None:
        self._stop_requested = True
        if hasattr(self, '_pause_event') and self._pause_event:
            self._pause_event.set()
        if hasattr(self, '_stream_lock'):
            with self._stream_lock:
                if hasattr(self, 'stream') and self.stream:
                    try:
                        self.stream.stop_stream()
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
        if hasattr(self, 'pyaudio') and self.pyaudio:
            try:
                self.pyaudio.terminate()
            except Exception:
                pass
