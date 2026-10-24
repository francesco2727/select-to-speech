"""Audio playback using PyAudio"""

import io
import logging
import math
import os
import queue
import threading
import time
import traceback
from typing import Optional

import pyaudio
import wave
import numpy as np
from pedalboard import Pedalboard, PitchShift

try:
    import pulsectl
except (ImportError, OSError):
    pulsectl = None

logger = logging.getLogger(__name__)

class AudioDucker:
    """Manages lowering background audio volumes asynchronously via a dedicated worker queue."""

    def __init__(self, duck_volume: float = 0.2):
        self.duck_volume = duck_volume
        self.enabled = True
        self._original_volumes: dict[int, list[float]] = {}
        self._pulse = None
        self._queue: queue.Queue = queue.Queue()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AudioDucker-Worker"
        )
        self._worker_thread.start()

    def _get_pulse(self):
        """Return a persistent Pulse connection for the worker thread, reconnecting if needed."""
        if not pulsectl:
            return None
        if self._pulse is None:
            self._pulse = pulsectl.Pulse('select-to-speech-ducker')
        return self._pulse

    def _reset_pulse(self) -> None:
        if self._pulse is not None:
            try:
                self._pulse.close()
            except Exception:
                pass
            self._pulse = None

    def _worker_loop(self) -> None:
        """Dedicated background loop that serializes all PulseAudio operations safely without leaks."""
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
                self._reset_pulse()
            finally:
                self._queue.task_done()

    def _is_own_sink_input(self, sink_input, my_pid: str) -> bool:
        """Check whether a PulseAudio/PipeWire sink-input belongs to this process."""
        pid_str = sink_input.proplist.get('application.process.id')
        if pid_str and str(pid_str) == my_pid:
            return True
        app_name = sink_input.proplist.get('application.name', '').lower()
        proc_bin = sink_input.proplist.get('application.process.binary', '').lower()
        if any(k in app_name or k in proc_bin for k in ('select-to-speech', 'run_main', 'python', 'alsa plug-in')):
            return True
        return False

    def _do_duck(self) -> None:
        if not self.enabled or not pulsectl:
            return

        try:
            pulse = self._get_pulse()
            if not pulse:
                return
            my_pid = str(os.getpid())
            sink_inputs = pulse.sink_input_list()

            for sink_input in sink_inputs:
                if self._is_own_sink_input(sink_input, my_pid):
                    continue

                if sink_input.index not in self._original_volumes:
                    self._original_volumes[sink_input.index] = pulse.volume_get_all_chans(sink_input)

                pulse.volume_set_all_chans(sink_input, self.duck_volume)
        except Exception as e:
            logger.warning(f"Failed to duck audio: {e}")
            self._reset_pulse()

    def _do_unduck(self) -> None:
        if not self.enabled or not pulsectl:
            self._original_volumes.clear()
            return

        if not self._original_volumes:
            return

        try:
            pulse = self._get_pulse()
            if not pulse:
                return
            for sink_input in pulse.sink_input_list():
                if sink_input.index in self._original_volumes:
                    pulse.volume_set_all_chans(sink_input, self._original_volumes[sink_input.index])
        except Exception as e:
            logger.warning(f"Failed to restore audio volume: {e}")
            self._reset_pulse()
        finally:
            self._original_volumes.clear()

    def _do_ensure_own_volume_max(self) -> None:
        if not pulsectl:
            return
        try:
            pulse = self._get_pulse()
            if not pulse:
                return
            my_pid = str(os.getpid())
            for sink_input in pulse.sink_input_list():
                if self._is_own_sink_input(sink_input, my_pid):
                    pulse.volume_set_all_chans(sink_input, 1.0)
        except Exception as e:
            logger.warning(f"Failed to restore own audio volume: {e}")
            self._reset_pulse()

    def start_ducking(self) -> None:
        """Enqueue ducking request."""
        if not self.enabled or not pulsectl:
            return
        self._queue.put("start")

    def stop_ducking(self) -> None:
        """Enqueue volume restoration request."""
        if not self.enabled or not pulsectl:
            return
        self._queue.put("stop")

    def ensure_own_volume_max(self) -> None:
        """Enqueue stream volume maximization request."""
        if not pulsectl:
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

            pipewire_ids: list[int] = []
            pulse_ids: list[int] = []

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
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Error scanning audio devices: {e}")

            devices.extend(pipewire_ids)
            devices.extend(pulse_ids)
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

                # Drain hardware buffer so the last frames are not truncated
                if not self._stop_requested and self.stream:
                    try:
                        latency = self.stream.get_output_latency()
                        drain_time = max(0.15, min(latency * 1.2, 1.5))
                    except Exception:
                        drain_time = 0.3
                    end_drain = time.time() + drain_time
                    while time.time() < end_drain and not self._stop_requested:
                        time.sleep(0.04)

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
            board: Optional[Pedalboard] = None
            if pitch != 1.0:
                try:
                    semitones = 12 * math.log2(pitch)
                    board = Pedalboard([PitchShift(semitones=semitones)])
                except Exception as e:
                    logger.error(f"Failed to initialize pitch shift board: {e}", exc_info=True)

            try:
                while not self._stop_requested:
                    try:
                        chunk_data = audio_generator_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if chunk_data is None:
                        break

                    audio_data, sample_rate = chunk_data
                    if audio_data is None or (isinstance(audio_data, (bytes, np.ndarray)) and len(audio_data) == 0):
                        continue

                    if isinstance(audio_data, np.ndarray):
                        n_channels = 1
                        sample_width = 2
                        frame_rate = sample_rate
                        audio_float = np.asarray(audio_data, dtype=np.float32)
                        if board is not None:
                            try:
                                audio_float = board(audio_float, sample_rate=frame_rate, reset=False)
                            except Exception as e:
                                logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)
                        frames = (np.clip(audio_float, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                    else:
                        audio_buffer = io.BytesIO(audio_data)
                        with wave.open(audio_buffer, "rb") as wav_file:
                            n_channels = wav_file.getnchannels()
                            sample_width = wav_file.getsampwidth()
                            frame_rate = wav_file.getframerate()
                            frames = wav_file.readframes(wav_file.getnframes())

                        if not frames:
                            continue

                        if board is not None and sample_width == 2:
                            try:
                                audio_int16 = np.frombuffer(frames, dtype=np.int16)
                                audio_float = audio_int16.astype(np.float32) / 32768.0
                                processed_audio = board(audio_float, sample_rate=frame_rate, reset=False)
                                processed_int16 = (np.clip(processed_audio, -1.0, 1.0) * 32767.0).astype(np.int16)
                                frames = processed_int16.tobytes()
                            except Exception as e:
                                logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)

                    if not frames:
                        continue

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

                # Drain hardware buffer so the trailing words are not truncated on stream close
                if not self._stop_requested and self.stream and stream_opened:
                    try:
                        latency = self.stream.get_output_latency()
                        drain_time = max(0.15, min(latency * 1.2, 1.5))
                    except Exception:
                        drain_time = 0.3
                    end_drain = time.time() + drain_time
                    while time.time() < end_drain and not self._stop_requested:
                        time.sleep(0.04)

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
