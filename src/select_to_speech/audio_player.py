"""Audio playback using PyAudio"""

import io
import logging
import math
import threading
import traceback
from typing import Optional

import pyaudio
import wave
import numpy as np
from pedalboard import Pedalboard, PitchShift
import os

try:
    import pulsectl
except ImportError:
    pulsectl = None

logger = logging.getLogger(__name__)

class AudioDucker:
    """Manages lowering background audio volumes."""
    def __init__(self, duck_volume: float = 0.2):
        self.duck_volume = duck_volume
        self.original_volumes = {}
        self.pulse = None
        self.enabled = True

    def start_ducking(self):
        if not self.enabled or not pulsectl:
            return
        try:
            self.pulse = pulsectl.Pulse('select-to-speech-ducker')
            my_pid = os.getpid()
            for sink_input in self.pulse.sink_input_list():
                # Get properties to identify the stream
                pid_str = sink_input.proplist.get('application.process.id')
                app_name = sink_input.proplist.get('application.name', '').lower()
                
                # Check if it's our process by PID
                if pid_str and str(pid_str) == str(my_pid):
                    continue
                    
                # PyAudio via ALSA might not report PID in PipeWire, so check name
                if 'python' in app_name or 'select-to-speech' in app_name:
                    continue

                self.original_volumes[sink_input.index] = self.pulse.volume_get_all_chans(sink_input)
                self.pulse.volume_set_all_chans(sink_input, self.duck_volume)
        except Exception as e:
            logger.warning(f"Failed to duck audio: {e}")
            if self.pulse:
                self.pulse.close()
                self.pulse = None

    def ensure_own_volume_max(self):
        """Finds our own audio stream and ensures its volume is set to 100%."""
        if not self.enabled or not pulsectl:
            return
        
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
            pulse.close()
        except Exception as e:
            logger.warning(f"Failed to restore own audio volume: {e}")

    def stop_ducking(self):
        if not self.pulse:
            return
        try:
            for sink_input in self.pulse.sink_input_list():
                if sink_input.index in self.original_volumes:
                    self.pulse.volume_set_all_chans(sink_input, self.original_volumes[sink_input.index])
        except Exception as e:
            logger.warning(f"Failed to restore audio volume: {e}")
        finally:
            self.original_volumes.clear()
            self.pulse.close()
            self.pulse = None


class AudioPlayer:
    """Audio playback handler using PyAudio"""

    def __init__(self, device_id: Optional[int] = None):
        """
        Initialize the audio player.

        Args:
            device_id: Audio device ID (None for default)
            ducking: Whether to enable audio ducking
        """
        self.device_id = device_id
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

    def _list_devices(self) -> None:
        """List all available audio devices"""
        device_count = self.pyaudio.get_device_count()
        logger.info(f"Available audio devices ({device_count} total):")
        for i in range(device_count):
            info = self.pyaudio.get_device_info_by_index(i)
            logger.info(f"  {i}: {info['name']} (channels: {info['maxOutputChannels']})")

    def _find_output_devices(self) -> list[Optional[int]]:
        """Build an ordered list of output device indices to try.

        Priority:
        1. User-configured ``device_id`` (if any).
        2. Devices whose name contains "pipewire" or "pulse" (virtual
           sound servers that correctly multiplex ALSA access).
        3. ``None`` (PyAudio/PortAudio default).
        """
        devices: list[Optional[int]] = []

        if self.device_id is not None:
            devices.append(self.device_id)

        # Prefer PipeWire > PulseAudio > default
        pipewire_ids: list[int] = []
        pulse_ids: list[int] = []

        for i in range(self.pyaudio.get_device_count()):
            try:
                info = self.pyaudio.get_device_info_by_index(i)
                if info["maxOutputChannels"] <= 0:
                    continue
                name = info["name"].lower()
                if "pipewire" in name:
                    pipewire_ids.append(i)
                elif "pulse" in name:
                    pulse_ids.append(i)
            except Exception:
                continue

        devices.extend(pipewire_ids)
        devices.extend(pulse_ids)
        devices.append(None)  # PortAudio default as final fallback

        # De-duplicate while keeping order
        seen: set[Optional[int]] = set()
        unique: list[Optional[int]] = []
        for d in devices:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        return unique

    @property
    def is_paused(self) -> bool:
        """Return True if playback is currently paused"""
        return not self._pause_event.is_set()

    def pause(self) -> None:
        """Pause playback"""
        self._pause_event.clear()
        logger.info("Playback paused")

    def resume(self) -> None:
        """Resume playback"""
        self._pause_event.set()
        logger.info("Playback resumed")

    def play(self, audio_data: bytes, sample_rate: int, channels: int = 1, pitch: float = 1.0) -> bool:
        """
        Play audio data.

        Args:
            audio_data: WAV audio data as bytes
            sample_rate: Sample rate in Hz
            channels: Number of audio channels
            pitch: Pitch multiplier (1.0 is normal)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Log what we received for debugging
            logger.debug(f"play() called with: audio_data type={type(audio_data)}, len={len(audio_data) if audio_data else 0}, sample_rate={sample_rate}, pitch={pitch}")
            
            if not audio_data:
                logger.error("No audio data provided")
                logger.error("Call stack:")
                for line in traceback.format_stack():
                    logger.error(line.strip())
                return False

            with self._play_lock:
                self.is_playing = True
                self._stop_requested = False
                self.ducker.start_ducking()

                # Parse WAV header
                audio_buffer = io.BytesIO(audio_data)
                with wave.open(audio_buffer, "rb") as wav_file:
                    n_channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    frame_rate = wav_file.getframerate()
                    frames = wav_file.readframes(wav_file.getnframes())

                if not frames:
                    logger.error("No audio frames extracted from WAV data")
                    return False

                # Apply pitch shifting if needed
                if pitch != 1.0:
                    try:
                        logger.debug(f"Applying pitch shift: {pitch}x")
                        # Convert bytes to numpy array (assuming 16-bit PCM)
                        if sample_width == 2:
                            audio_int16 = np.frombuffer(frames, dtype=np.int16)
                            # Normalize to float32 [-1.0, 1.0] for pedalboard
                            audio_float = audio_int16.astype(np.float32) / 32768.0
                            
                            # Calculate semitones from pitch multiplier
                            semitones = 12 * math.log2(pitch)
                            
                            # Apply pitch shift
                            board = Pedalboard([PitchShift(semitones=semitones)])
                            processed_audio = board(audio_float, sample_rate=frame_rate, reset=False)
                            
                            # Convert back to int16 bytes
                            processed_int16 = (processed_audio * 32767.0).astype(np.int16)
                            frames = processed_int16.tobytes()
                        else:
                            logger.warning(f"Pitch shifting not supported for sample width {sample_width}. Skipping.")
                    except Exception as e:
                        logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)

                logger.debug(
                    f"WAV info: {n_channels}ch, {frame_rate}Hz, {sample_width} bytes/sample, {len(frames)} bytes"
                )

                # Open audio stream with fallback to other devices
                stream_opened = False
                devices_to_try = self._find_output_devices()

                for attempt, device_id in enumerate(devices_to_try, 1):
                    try:
                        device_name = self._get_device_name(device_id)
                        logger.debug(f"Attempt {attempt}: Trying device {device_id} ({device_name})")

                        with self._stream_lock:
                            self.stream = self.pyaudio.open(
                                format=self.pyaudio.get_format_from_width(sample_width),
                                channels=n_channels,
                                rate=frame_rate,
                                output=True,
                                output_device_index=device_id,
                            )
                        
                        logger.info(f"✓ Successfully opened audio device {device_id} ({device_name})")
                        stream_opened = True
                        self.ducker.ensure_own_volume_max()
                        break
                        
                    except Exception as device_error:
                        logger.debug(f"Device {device_id} failed: {device_error}")
                        continue

                if not stream_opened:
                    logger.error("❌ All audio devices are busy or unavailable. Check PulseAudio/PipeWire status.")
                    logger.error("Available audio output devices:")
                    self._list_devices()
                    return False

                self.is_playing = True
                self._stop_requested = False
                logger.debug(f"Playing audio: {len(frames)} bytes")

                # Play audio in chunks to allow interruption
                try:
                    chunk_size = 4096
                    bytes_written = 0
                    
                    for i in range(0, len(frames), chunk_size):
                        if self._stop_requested:
                            logger.info("Playback interrupted by user")
                            break
                            
                        self._pause_event.wait()

                        if self._stop_requested:
                            logger.info("Playback interrupted by user")
                            break
                            
                        chunk = frames[i:i + chunk_size]
                        # Pad the final chunk to a full chunk_size so ALSA doesn't
                        # get a short write that triggers an underrun / xrun.
                        if len(chunk) < chunk_size:
                            chunk = chunk + b'\x00' * (chunk_size - len(chunk))
                        with self._stream_lock:
                            if self.stream and not self._stop_requested:
                                self.stream.write(chunk)
                        bytes_written += len(chunk)
                        
                    logger.debug(f"Wrote {bytes_written} bytes to stream")

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
                    
                    if self._stop_requested:
                        return False
                        
                    logger.info("✓ Playback completed successfully")
                    return True
                    
                except Exception as playback_error:
                    logger.error(f"Error during playback: {playback_error}", exc_info=True)
                    with self._stream_lock:
                        try:
                            if self.stream:
                                self.stream.stop_stream()
                                self.stream.close()
                                self.stream = None
                        except Exception:
                            self.stream = None
                    self.is_playing = False
                    self.ducker.stop_ducking()
                    return False

        except wave.Error as wave_error:
            logger.error(f"Invalid WAV data: {wave_error}")
            logger.error(f"Audio data size: {len(audio_data)} bytes")
            return False
            
        except Exception as e:
            logger.error(f"Fatal playback error: {e}", exc_info=True)
            self.ducker.stop_ducking()
            return False

    def _get_device_name(self, device_id: Optional[int]) -> str:
        """Get the name of an audio device"""
        if device_id is None:
            return "default/auto"
        try:
            info = self.pyaudio.get_device_info_by_index(device_id)
            return info['name']
        except:
            return "unknown"

    def play_stream(self, audio_generator_queue, pitch: float = 1.0) -> bool:
        """
        Play audio stream from a queue.

        Args:
            audio_generator_queue: Queue containing (audio_data, sample_rate) tuples
            pitch: Pitch multiplier (1.0 is normal)

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._play_lock:
                self.is_playing = True
                self._stop_requested = False
                stream_opened = False
                first_chunk = True
                self.ducker.start_ducking()

                while not self._stop_requested:
                    chunk_data = audio_generator_queue.get()
                    if chunk_data is None:  # EOF
                        break
                    
                    audio_data, sample_rate = chunk_data
                    
                    if not audio_data:
                        continue

                    # Parse WAV header to extract raw PCM data
                    audio_buffer = io.BytesIO(audio_data)
                    with wave.open(audio_buffer, "rb") as wav_file:
                        n_channels = wav_file.getnchannels()
                        sample_width = wav_file.getsampwidth()
                        frame_rate = wav_file.getframerate()
                        frames = wav_file.readframes(wav_file.getnframes())

                    if not frames:
                        continue

                    # Apply pitch shifting if needed
                    if pitch != 1.0:
                        try:
                            if sample_width == 2:
                                audio_int16 = np.frombuffer(frames, dtype=np.int16)
                                audio_float = audio_int16.astype(np.float32) / 32768.0
                                semitones = 12 * math.log2(pitch)
                                board = Pedalboard([PitchShift(semitones=semitones)])
                                processed_audio = board(audio_float, sample_rate=frame_rate, reset=False)
                                processed_int16 = (processed_audio * 32767.0).astype(np.int16)
                                frames = processed_int16.tobytes()
                        except Exception as e:
                            logger.error(f"Failed to apply pitch shift: {e}", exc_info=True)

                    if first_chunk:
                        # Open stream on the first valid chunk
                        devices_to_try = self._find_output_devices()

                        for attempt, device_id in enumerate(devices_to_try, 1):
                            try:
                                with self._stream_lock:
                                    self.stream = self.pyaudio.open(
                                        format=self.pyaudio.get_format_from_width(sample_width),
                                        channels=n_channels,
                                        rate=frame_rate,
                                        output=True,
                                        output_device_index=device_id,
                                    )
                                stream_opened = True
                                first_chunk = False
                                self.ducker.ensure_own_volume_max()
                                break
                            except Exception as device_error:
                                continue

                        if not stream_opened:
                            logger.error("❌ All audio devices are busy or unavailable.")
                            return False

                    # Write chunks to the open stream
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

                # Cleanup stream after finishing queue or stopping
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
                return not self._stop_requested
            
        except Exception as e:
            logger.error(f"Fatal stream playback error: {e}", exc_info=True)
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
            return False

    def stop(self) -> None:
        """Stop playback and cleanup"""
        self._stop_requested = True
        self._pause_event.set()  # unblock any paused write loop
        logger.info("Audio player stop requested")

    def __del__(self) -> None:
        """Cleanup on object destruction"""
        self._stop_requested = True
        self._pause_event.set()
        with self._stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
        if self.pyaudio:
            self.pyaudio.terminate()
