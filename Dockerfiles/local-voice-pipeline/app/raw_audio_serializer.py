import os, logging, wave, time
from datetime import datetime
from pathlib import Path
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.frames.frames import AudioRawFrame, InputAudioRawFrame

logger = logging.getLogger(__name__)

# CoreS3 mic sends 16kHz; pipeline TTS outputs at 48kHz for the CoreS3 speaker.
# Override via WEBSOCKET_INPUT_SAMPLE_RATE / WEBSOCKET_OUTPUT_SAMPLE_RATE env vars.
INPUT_SAMPLE_RATE = int(os.environ.get("WEBSOCKET_INPUT_SAMPLE_RATE", 16000))
OUTPUT_SAMPLE_RATE = int(os.environ.get("WEBSOCKET_OUTPUT_SAMPLE_RATE", 48000))
NUM_CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

class RawAudioSerializer(FrameSerializer):
    """Binary PCM ↔ Pipecat frames.
    Incoming bytes (from ESP32 mic at INPUT_SAMPLE_RATE) → InputAudioRawFrame
    AudioRawFrame (from TTS at OUTPUT_SAMPLE_RATE) → bytes → ESP32 speaker
    
    Also saves incoming audio to WAV files for STT evaluation.
    """

    def __init__(self):
        super().__init__()
        self._tts_chunk_count = 0
        self._tts_bytes_total = 0
        self._audio_recordings = {}  # session_id → wav file + stream

    async def serialize(self, frame: AudioRawFrame) -> bytes | None:
        if isinstance(frame, AudioRawFrame):
            data = frame.audio
            self._tts_chunk_count += 1
            self._tts_bytes_total += len(data)
            if self._tts_chunk_count == 1:
                logger.info(f"[TTS→WS] First audio chunk: {len(data)}B (sample_rate={frame.sample_rate})")
            elif self._tts_chunk_count % 10 == 0:
                logger.info(f"[TTS→WS] chunk={self._tts_chunk_count} sent={len(data)}B total={self._tts_bytes_total}B")
            return data
        return None

    def _get_audio_file(self, session_id: str):
        """Get or create a WAV file for recording incoming audio."""
        if session_id not in self._audio_recordings:
            recordings_dir = Path("/data/audio-recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            wav_file = recordings_dir / f"{session_id}_{timestamp}.wav"
            
            wav = wave.open(str(wav_file), 'wb')
            wav.setnchannels(NUM_CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(INPUT_SAMPLE_RATE)
            
            logger.info(f"Recording incoming audio to: {wav_file}")
            self._audio_recordings[session_id] = {
                'file': wav,
                'path': wav_file,
                'bytes': 0,
                'chunks': 0
            }
        return self._audio_recordings[session_id]

    def close_audio_file(self, session_id: str):
        """Close audio recording file when session ends."""
        if session_id in self._audio_recordings:
            rec = self._audio_recordings[session_id]
            rec['file'].close()
            logger.info(f"Closed audio recording: {rec['path']} ({rec['bytes']}B, {rec['chunks']} chunks)")
            del self._audio_recordings[session_id]

    async def deserialize(self, data: bytes) -> InputAudioRawFrame | None:
        if not data:
            return None
        
        # For now, use a fixed session_id. In production, pass session_id from context.
        session_id = "default"
        
        # Record the incoming audio
        rec = self._get_audio_file(session_id)
        rec['file'].writeframes(data)
        rec['bytes'] += len(data)
        rec['chunks'] += 1
        
        if rec['chunks'] == 1:
            logger.info(f"[MIC→WS] Recording started: {len(data)}B chunk")
        elif rec['chunks'] % 50 == 0:  # Log every 50 chunks (~3 seconds at 16kHz)
            logger.info(f"[MIC→WS] Recording: {rec['chunks']} chunks, {rec['bytes']}B total")
        
        return InputAudioRawFrame(
            audio=data,
            sample_rate=INPUT_SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
