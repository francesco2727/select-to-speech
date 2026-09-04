"""
Tests for the AudioPlayer module
Tests cover initialization, playback, error handling, and cleanup
"""

import io
import wave
import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open, PropertyMock
import os
import sys

from select_to_speech.audio_player import (
    AudioPlayer,
    AudioDucker,
    WindowsAudioDucker,
    PulseAudioDucker,
    BaseAudioDucker,
)


class TestAudioPlayerInitialization:
    """Test AudioPlayer initialization"""

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_init_default_device(self, mock_pyaudio_class):
        """Test initialization with default device"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        
        assert player.device_id is None
        assert player.stream is None
        assert player.is_playing is False
        assert player.pyaudio == mock_pyaudio
        mock_pyaudio_class.assert_called_once()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_init_with_device_id(self, mock_pyaudio_class):
        """Test initialization with specific device ID"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer(device_id=2)
        
        assert player.device_id == 2
        assert player.stream is None
        assert player.is_playing is False


class TestAudioPlayerPlayback:
    """Test AudioPlayer playback functionality"""

    def create_valid_wav_data(self, sample_rate=22050, channels=1, duration_ms=100):
        """Helper to create valid WAV audio data"""
        num_samples = int(sample_rate * duration_ms / 1000)
        sample_width = 2  # 16-bit
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            # Write silence (zeros)
            silence = b'\x00' * (num_samples * channels * sample_width)
            wav_file.writeframes(silence)
        
        return wav_buffer.getvalue()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_valid_audio(self, mock_pyaudio_class):
        """Test playing valid audio data"""
        # Setup mocks
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8  # Dummy format
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        result = player.play(audio_data, sample_rate=22050)
        
        assert result is True
        assert player.is_playing is False  # Should be False after playback
        mock_stream.write.assert_called()
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_empty_audio_data(self, mock_pyaudio_class):
        """Test playing with empty audio data"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        result = player.play(b'', sample_rate=22050)
        
        assert result is False
        mock_pyaudio.open.assert_not_called()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_invalid_wav_data(self, mock_pyaudio_class):
        """Test playing with invalid WAV data"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        # Invalid WAV data (just random bytes)
        invalid_data = b'this is not valid wav data'
        
        result = player.play(invalid_data, sample_rate=22050)
        
        assert result is False

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_stream_open_failure(self, mock_pyaudio_class):
        """Test handling when stream fails to open on all devices"""
        mock_pyaudio = MagicMock()
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio.open.side_effect = Exception("Device not available")
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer(device_id=0)
        audio_data = self.create_valid_wav_data()
        
        result = player.play(audio_data, sample_rate=22050)
        
        assert result is False

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_write_failure(self, mock_pyaudio_class):
        """Test handling when audio write fails during playback"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_stream.write.side_effect = Exception("Write failed")
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        result = player.play(audio_data, sample_rate=22050)
        
        assert result is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_with_custom_channels(self, mock_pyaudio_class):
        """Test playing audio with multiple channels"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data(channels=2)
        
        result = player.play(audio_data, sample_rate=44100, channels=2)
        
        assert result is True
        mock_stream.write.assert_called()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_stream(self, mock_pyaudio_class):
        """Test streaming audio playback"""
        import queue
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        q = queue.Queue()
        q.put((audio_data, 22050))
        q.put(None)  # EOF
        
        result = player.play_stream(q)
        
        assert result is True
        mock_stream.write.assert_called()
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()


class TestAudioPlayerDeviceHandling:
    """Test device handling and fallback mechanisms"""

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_get_device_name_valid(self, mock_pyaudio_class):
        """Test getting device name with valid device ID"""
        mock_pyaudio = MagicMock()
        mock_device_info = {'name': 'Test Audio Device'}
        mock_pyaudio.get_device_info_by_index.return_value = mock_device_info
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        device_name = player._get_device_name(0)
        
        assert device_name == 'Test Audio Device'

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_get_device_name_none(self, mock_pyaudio_class):
        """Test getting device name with None (default device)"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        device_name = player._get_device_name(None)
        
        assert device_name == 'default/auto'

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_get_device_name_invalid(self, mock_pyaudio_class):
        """Test getting device name with invalid device ID"""
        mock_pyaudio = MagicMock()
        mock_pyaudio.get_device_info_by_index.side_effect = Exception("Invalid device")
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        device_name = player._get_device_name(999)
        
        assert device_name == 'unknown'

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_device_fallback_mechanism(self, mock_pyaudio_class):
        """Test that fallback devices are tried when primary fails"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        
        # Make first attempt fail, second succeed
        mock_pyaudio.open.side_effect = [
            Exception("Device 0 failed"),
            mock_stream  # Device 6 succeeds
        ]
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio.get_device_info_by_index.return_value = {'name': 'Test Device'}
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer(device_id=0)
        audio_data = self.create_valid_wav_data()
        
        result = player.play(audio_data, sample_rate=22050)
        
        # Should succeed on fallback device
        assert result is True
        # open() should have been called twice (first failed, second succeeded)
        assert mock_pyaudio.open.call_count == 2

    def create_valid_wav_data(self, sample_rate=22050, channels=1, duration_ms=100):
        """Helper to create valid WAV audio data"""
        num_samples = int(sample_rate * duration_ms / 1000)
        sample_width = 2
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            silence = b'\x00' * (num_samples * channels * sample_width)
            wav_file.writeframes(silence)
        return wav_buffer.getvalue()


class TestAudioPlayerCleanup:
    """Test cleanup and resource management"""

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_stop_with_active_stream(self, mock_pyaudio_class):
        """Test stopping with an active stream"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        player.stream = mock_stream
        player.is_playing = True
        
        player.stop()
        
        assert player._stop_requested is True
        assert player.is_playing is True  # Set to False by play thread, not stop()

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_stop_without_stream(self, mock_pyaudio_class):
        """Test stopping when no stream is active"""
        mock_pyaudio = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        player.stream = None
        
        # Should not raise any exception
        player.stop()
        
        assert player.is_playing is False

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_stop_with_stream_close_error(self, mock_pyaudio_class):
        """Test handling errors when closing stream"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_stream.stop_stream.side_effect = Exception("Stop failed")
        mock_stream.close.side_effect = Exception("Close failed")
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        player.stream = mock_stream
        
        # Should not raise exception even when close operations fail
        player.stop()
        
        assert player._stop_requested is True

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_cleanup_on_deletion(self, mock_pyaudio_class):
        """Test cleanup when object is deleted"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        player.stream = mock_stream
        
        # Trigger __del__
        del player
        
        # Verify pyaudio.terminate() was called
        mock_pyaudio.terminate.assert_called_once()


class TestAudioPlayerEdgeCases:
    """Test edge cases and error conditions"""

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_multiple_times(self, mock_pyaudio_class):
        """Test playing multiple times sequentially"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        # Play twice
        result1 = player.play(audio_data, sample_rate=22050)
        result2 = player.play(audio_data, sample_rate=22050)
        
        assert result1 is True
        assert result2 is True
        # Should open stream twice
        assert mock_pyaudio.open.call_count == 2

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_is_playing_flag(self, mock_pyaudio_class):
        """Test that is_playing flag is properly managed"""
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        # Initially false
        assert player.is_playing is False
        
        # Simulate play (would be set to True during play, then False after)
        player.is_playing = True
        assert player.is_playing is True
        
        player.play(audio_data, sample_rate=22050)
        assert player.is_playing is False

    @patch('select_to_speech.audio_player.pyaudio.PyAudio')
    def test_play_after_stop_requested(self, mock_pyaudio_class):
        """Test that play and play_stream succeed after stop() has been called previously"""
        import queue
        mock_pyaudio = MagicMock()
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8
        mock_pyaudio_class.return_value = mock_pyaudio
        
        player = AudioPlayer()
        audio_data = self.create_valid_wav_data()
        
        # Call stop explicitly (as done when interrupting previous playback)
        player.stop()
        assert player._stop_requested is True
        
        # Next call to play should clear _stop_requested and succeed
        res = player.play(audio_data, sample_rate=22050)
        assert res is True
        assert player._stop_requested is False
        
        # Same for play_stream
        player.stop()
        assert player._stop_requested is True
        q = queue.Queue()
        q.put((audio_data, 22050))
        q.put(None)
        res_stream = player.play_stream(q)
        assert res_stream is True
        assert player._stop_requested is False

    def create_valid_wav_data(self, sample_rate=22050, channels=1, duration_ms=100):
        """Helper to create valid WAV audio data"""
        num_samples = int(sample_rate * duration_ms / 1000)
        sample_width = 2
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            silence = b'\x00' * (num_samples * channels * sample_width)
            wav_file.writeframes(silence)
        return wav_buffer.getvalue()


class TestWindowsAudioDucker:
    """Tests for WindowsAudioDucker pycaw integration"""

    def test_duck_and_unduck_sessions(self):
        """Test ducking background sessions and unducking them on Windows"""
        ducker = WindowsAudioDucker(duck_volume=0.25)

        # Mock other process session
        mock_other_proc = MagicMock()
        mock_other_proc.pid = 9999
        mock_other_proc.name.return_value = "spotify.exe"

        mock_other_volume = MagicMock()
        mock_other_volume.GetMasterVolume.return_value = 0.8

        mock_other_session = MagicMock()
        mock_other_session.Process = mock_other_proc
        mock_other_session.SimpleAudioVolume = mock_other_volume

        # Mock own process session
        mock_own_proc = MagicMock()
        mock_own_proc.pid = os.getpid()
        mock_own_proc.name.return_value = "python.exe"

        mock_own_volume = MagicMock()
        mock_own_volume.GetMasterVolume.return_value = 1.0

        mock_own_session = MagicMock()
        mock_own_session.Process = mock_own_proc
        mock_own_session.SimpleAudioVolume = mock_own_volume

        mock_audio_utils = MagicMock()
        mock_audio_utils.GetAllSessions.return_value = [mock_other_session, mock_own_session]

        with patch('select_to_speech.audio_player.pycaw_available', True), \
             patch('select_to_speech.audio_player.AudioUtilities', mock_audio_utils):

            # Duck
            orig_vols = ducker.duck(0.25)
            assert 9999 in orig_vols
            assert orig_vols[9999] == 0.8
            mock_other_volume.SetMasterVolume.assert_called_with(0.25, None)
            mock_own_volume.SetMasterVolume.assert_not_called()

            # Unduck
            ducker.unduck()
            mock_other_volume.SetMasterVolume.assert_called_with(0.8, None)
            assert len(ducker._original_volumes) == 0

    def test_ensure_own_volume_max(self):
        """Test setting own process session to max volume on Windows"""
        ducker = WindowsAudioDucker()

        mock_own_proc = MagicMock()
        mock_own_proc.pid = os.getpid()
        mock_own_proc.name.return_value = "python.exe"

        mock_own_volume = MagicMock()
        mock_own_session = MagicMock()
        mock_own_session.Process = mock_own_proc
        mock_own_session.SimpleAudioVolume = mock_own_volume

        mock_audio_utils = MagicMock()
        mock_audio_utils.GetAllSessions.return_value = [mock_own_session]

        with patch('select_to_speech.audio_player.pycaw_available', True), \
             patch('select_to_speech.audio_player.AudioUtilities', mock_audio_utils):
            ducker.ensure_own_volume_max()
            mock_own_volume.SetMasterVolume.assert_called_with(1.0, None)

    def test_windows_ducker_pycaw_missing(self):
        """Test that WindowsAudioDucker gracefully handles missing pycaw"""
        ducker = WindowsAudioDucker()
        with patch('select_to_speech.audio_player.pycaw_available', False), \
             patch('select_to_speech.audio_player.AudioUtilities', None):
            assert ducker.duck(0.2) == {}
            ducker.unduck()
            ducker.ensure_own_volume_max()


class TestPulseAudioDucker:
    """Tests for PulseAudioDucker pulsectl integration"""

    def test_duck_and_unduck_pulsectl(self):
        """Test ducking and restoring with mock pulsectl"""
        ducker = PulseAudioDucker(duck_volume=0.2)

        mock_pulse = MagicMock()
        mock_sink_other = MagicMock()
        mock_sink_other.index = 1
        mock_sink_other.proplist = {'application.process.id': '9999', 'application.name': 'vlc'}

        mock_sink_own = MagicMock()
        mock_sink_own.index = 2
        mock_sink_own.proplist = {'application.process.id': str(os.getpid()), 'application.name': 'python'}

        mock_pulse.sink_input_list.return_value = [mock_sink_other, mock_sink_own]
        mock_pulse.volume_get_all_chans.return_value = [0.9, 0.9]

        mock_pulsectl = MagicMock()
        mock_pulsectl.Pulse.return_value = mock_pulse

        with patch('select_to_speech.audio_player.pulsectl', mock_pulsectl):
            # Duck
            orig_vols = ducker.duck(0.2)
            assert 1 in orig_vols
            assert orig_vols[1] == [0.9, 0.9]
            mock_pulse.volume_set_all_chans.assert_called_with(mock_sink_other, 0.2)

            # Unduck
            ducker.unduck()
            mock_pulse.volume_set_all_chans.assert_called_with(mock_sink_other, [0.9, 0.9])
            assert len(ducker._original_volumes) == 0

    def test_pulse_ducker_missing(self):
        """Test that PulseAudioDucker gracefully handles missing pulsectl"""
        ducker = PulseAudioDucker()
        with patch('select_to_speech.audio_player.pulsectl', None):
            assert ducker.duck(0.2) == {}
            ducker.unduck()
            ducker.ensure_own_volume_max()


class TestAudioDuckerCrossPlatform:
    """Tests for unified AudioDucker platform selection and queue operations"""

    def test_platform_backend_selection_windows(self):
        """Test that Windows platform uses WindowsAudioDucker backend"""
        with patch('sys.platform', 'win32'):
            ducker = AudioDucker()
            assert isinstance(ducker._backend, WindowsAudioDucker)

    def test_platform_backend_selection_linux(self):
        """Test that Linux platform uses PulseAudioDucker backend"""
        with patch('sys.platform', 'linux'):
            ducker = AudioDucker()
            assert isinstance(ducker._backend, PulseAudioDucker)

    def test_start_and_stop_ducking_queue(self):
        """Test that start_ducking and stop_ducking enqueue commands properly"""
        ducker = AudioDucker()
        mock_backend = MagicMock()
        ducker._backend = mock_backend

        with patch.object(AudioDucker, 'is_available', new_callable=PropertyMock, return_value=True):
            ducker.start_ducking()
            ducker._queue.join()
            mock_backend.duck.assert_called_with(ducker.duck_volume)

            ducker.stop_ducking()
            ducker._queue.join()
            mock_backend.unduck.assert_called_once()

            ducker.ensure_own_volume_max()
            ducker._queue.join()
            mock_backend.ensure_own_volume_max.assert_called_once()


if __name__ == '__main__':
    # Run tests with pytest
    pytest.main([__file__, '-v', '--tb=short'])

