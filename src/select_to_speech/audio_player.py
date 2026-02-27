"""Audio playback using PyAudio"""

import io
import logging
import math
import traceback
from typing import Optional

import pyaudio
import wave
import numpy as np
from pedalboard import Pedalboard, PitchShift


logger = logging.getLogger(__name__)


class AudioPlayer:
    """Audio playback handler using PyAudio"""

    def __init__(self, device_id: Optional[int] = None):
        """
        Initialize the audio player.

        Args:
            device_id: Audio device ID (None for default)
        """
        self.device_id = device_id
        self.pyaudio = pyaudio.PyAudio()
        self.stream = None
        self.is_playing = False
        self._stop_requested = False

    def _list_devices(self) -> None:
        """List all available audio devices"""
        device_count = self.pyaudio.get_device_count()
        logger.info(f"Available audio devices ({device_count} total):")
        for i in range(device_count):
            info = self.pyaudio.get_device_info_by_index(i)
            logger.info(f"  {i}: {info['name']} (channels: {info['maxOutputChannels']})")

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
            devices_to_try = []
            
            # Build list of devices to try
            if self.device_id is not None:
                devices_to_try.append(self.device_id)
                logger.info(f"Trying configured device: {self.device_id}")
            
            # Add fallback devices: pipewire, pulse, default, auto
            devices_to_try.extend([6, 7, 8, None])
            
            for attempt, device_id in enumerate(devices_to_try, 1):
                try:
                    device_name = self._get_device_name(device_id)
                    logger.debug(f"Attempt {attempt}: Trying device {device_id} ({device_name})")
                    
                    self.stream = self.pyaudio.open(
                        format=self.pyaudio.get_format_from_width(sample_width),
                        channels=n_channels,
                        rate=frame_rate,
                        output=True,
                        output_device_index=device_id,
                    )
                    
                    logger.info(f"✓ Successfully opened audio device {device_id} ({device_name})")
                    stream_opened = True
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
                        
                    chunk = frames[i:i + chunk_size]
                    self.stream.write(chunk)
                    bytes_written += len(chunk)
                    
                logger.debug(f"Wrote {bytes_written} bytes to stream")
                
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
                self.is_playing = False
                
                if self._stop_requested:
                    return False
                    
                logger.info("✓ Playback completed successfully")
                return True
                
            except Exception as playback_error:
                logger.error(f"Error during playback: {playback_error}", exc_info=True)
                try:
                    if self.stream:
                        self.stream.stop_stream()
                        self.stream.close()
                        self.stream = None
                except:
                    pass
                self.is_playing = False
                return False

        except wave.Error as wave_error:
            logger.error(f"Invalid WAV data: {wave_error}")
            logger.error(f"Audio data size: {len(audio_data)} bytes")
            return False
            
        except Exception as e:
            logger.error(f"Fatal playback error: {e}", exc_info=True)
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

    def stop(self) -> None:
        """Stop playback and cleanup"""
        self._stop_requested = True
        # We don't close the stream here anymore.
        # The play() loop will detect _stop_requested, break, and close the stream safely.
        # Closing it here while play() is writing to it causes ALSA/PyAudio crashes.
        logger.info("Audio player stop requested")

    def __del__(self) -> None:
        """Cleanup on object destruction"""
        self.stop()
        if self.pyaudio:
            self.pyaudio.terminate()
