"""
Tests for the AudioPlayer module
Tests cover initialization, playback, error handling, and cleanup
"""

import io
import wave
import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open
import sys

# Add src to path for imports
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.audio_player import AudioPlayer


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
        mock_stream.write.assert_called_once()
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
        mock_stream.write.assert_called_once()


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
        
        assert player.stream is None
        assert player.is_playing is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

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
        
        assert player.stream is None

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


if __name__ == '__main__':
    # Run tests with pytest
    pytest.main([__file__, '-v', '--tb=short'])
