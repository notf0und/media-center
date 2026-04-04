import os
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.frames.frames import AudioRawFrame, InputAudioRawFrame

# CoreS3 mic sends 16kHz; pipeline TTS outputs at 24kHz for the CoreS3 speaker.
# Override via WEBSOCKET_INPUT_SAMPLE_RATE / WEBSOCKET_OUTPUT_SAMPLE_RATE env vars.
INPUT_SAMPLE_RATE = int(os.environ.get("WEBSOCKET_INPUT_SAMPLE_RATE", 16000))
OUTPUT_SAMPLE_RATE = int(os.environ.get("WEBSOCKET_OUTPUT_SAMPLE_RATE", 24000))
NUM_CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

class RawAudioSerializer(FrameSerializer):
    """Binary PCM ↔ Pipecat frames.
    Incoming bytes (from ESP32 mic at INPUT_SAMPLE_RATE) → InputAudioRawFrame
    AudioRawFrame (from TTS at OUTPUT_SAMPLE_RATE) → bytes → ESP32 speaker
    """

    def serialize(self, frame: AudioRawFrame) -> bytes | None:
        if isinstance(frame, AudioRawFrame):
            return frame.audio
        return None

    def deserialize(self, data: bytes) -> InputAudioRawFrame | None:
        if not data:
            return None
        return InputAudioRawFrame(
            audio=data,
            sample_rate=INPUT_SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
