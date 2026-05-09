"""TextForwarder — Pipecat processors that send STT/TTS text to the ESP32 display.

Two lightweight FrameProcessors are inserted into the pipeline:

  SttTextForwarder  — placed between STT and context_aggregator.user()
                      intercepts TranscriptionFrame, sends {"type":"stt_text","text":"..."}

  TtsTextForwarder  — placed between LLM and TTS
                      accumulates LLMTextFrame chunks; on LLMFullResponseEndFrame
                      sends {"type":"tts_text","text":"..."}

Both pass all frames through unchanged.
The ESP32 component fires on_stt_text / on_tts_text automations on receipt.
"""
import json
import logging

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import FrameDirection
from pipecat.processors.frame_processor import FrameProcessor

logger = logging.getLogger(__name__)


class SttTextForwarder(FrameProcessor):
    """Send STT transcription text to the ESP32 via WebSocket JSON frame."""

    def __init__(self, websocket_holder: dict):
        super().__init__()
        self._ws_holder = websocket_holder

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            if frame.text:
                await self._send("stt_text", frame.text)
        await self.push_frame(frame, direction)

    async def _send(self, msg_type: str, text: str):
        ws = self._ws_holder.get("websocket")
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": msg_type, "text": text}))
        except Exception as exc:
            logger.debug("SttTextForwarder send failed: %s", exc)


class TtsTextForwarder(FrameProcessor):
    """Accumulate LLM text and send final response text to the ESP32 display."""

    def __init__(self, websocket_holder: dict):
        super().__init__()
        self._ws_holder = websocket_holder
        self._buf: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMTextFrame):
                if frame.text:
                    self._buf.append(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                if self._buf:
                    text = "".join(self._buf).strip()
                    self._buf.clear()
                    if text:
                        await self._send("tts_text", text)
        await self.push_frame(frame, direction)

    async def _send(self, msg_type: str, text: str):
        ws = self._ws_holder.get("websocket")
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": msg_type, "text": text}))
        except Exception as exc:
            logger.debug("TtsTextForwarder send failed: %s", exc)
