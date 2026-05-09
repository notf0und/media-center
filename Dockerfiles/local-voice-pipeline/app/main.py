#!/usr/bin/env python3
"""Local voice pipeline — WebSocket server entry point"""
import asyncio, logging, os, signal
from pipecat.transports.websocket.server import WebsocketServerParams, WebsocketServerTransport
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from .pipeline_builder import build_pipeline
from .raw_audio_serializer import RawAudioSerializer
from .text_forwarder import SttTextForwarder, TtsTextForwarder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEBUG_VAD = os.environ.get("DEBUG_VAD", "false").lower() == "true"


import numpy as np

class LoggingSileroVAD(SileroVADAnalyzer):
    """Wraps SileroVADAnalyzer to log confidence values AND audio RMS for diagnostics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frame_count = 0
        self._max_conf = 0.0

    def voice_confidence(self, buffer) -> float:
        conf = super().voice_confidence(buffer)
        self._frame_count += 1
        val = float(conf) if not hasattr(conf, '__len__') else float(conf[0])
        if val > self._max_conf:
            self._max_conf = val
        if self._frame_count % 50 == 0:
            # Also log RMS to detect near-silent audio
            try:
                samples = np.frombuffer(buffer, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2)))
                rms_pct = rms / 327.67  # % of full scale
                logger.info(
                    f"[VAD] frames={self._frame_count} latest_conf={val:.4f} max_conf={self._max_conf:.4f} "
                    f"rms={rms:.1f} ({rms_pct:.2f}%)"
                )
            except Exception:
                logger.info(f"[VAD] frames={self._frame_count} latest_conf={val:.4f} max_conf={self._max_conf:.4f}")
        return conf

HOST = os.environ.get("WEBSOCKET_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBSOCKET_PORT", 8765))
VAD_CONFIDENCE = float(os.environ.get("VAD_CONFIDENCE", 0.7))
VAD_MIN_VOLUME = float(os.environ.get("VAD_MIN_VOLUME", 0.05))
VAD_START_SECS = float(os.environ.get("VAD_START_SECS", 0.4))
VAD_STOP_SECS = float(os.environ.get("VAD_STOP_SECS", 0.3))
SESSION_TIMEOUT_SECS = int(os.environ.get("SESSION_TIMEOUT_SECS", 30))

async def main():
    logger.info(f"Starting local-voice-pipeline on ws://{HOST}:{PORT}")

    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=int(os.environ.get("WEBSOCKET_OUTPUT_SAMPLE_RATE", 48000)),
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=LoggingSileroVAD(params=VADParams(
                confidence=VAD_CONFIDENCE,
                min_volume=VAD_MIN_VOLUME,
                start_secs=VAD_START_SECS,
                stop_secs=VAD_STOP_SECS,
            )),
            vad_audio_passthrough=True,
            serializer=RawAudioSerializer(),
        ),
        host=HOST,
        port=PORT,
    )

    # Shared holder so forwarders can send text frames to the connected ESP32
    ws_holder: dict = {"websocket": None}

    # pipeline_builder returns (pipeline, context, system_messages, memory)
    pipeline, context, system_messages, memory = await build_pipeline(
        transport, ws_holder=ws_holder
    )
    task = PipelineTask(pipeline, idle_timeout_secs=None)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, websocket):
        logger.info(f"Client connected: {websocket.remote_address}")
        ws_holder["websocket"] = websocket
        # Reset conversation history for each new connection (fresh context)
        context.set_messages(list(system_messages))
        # Re-inject entity memory so known entities are still available
        memory.inject_into_context(context)

        async def _session_timeout():
            await asyncio.sleep(SESSION_TIMEOUT_SECS)
            if ws_holder.get("websocket") is websocket:
                logger.info(f"Session timeout ({SESSION_TIMEOUT_SECS}s), closing connection")
                try:
                    await websocket.close()
                except Exception:
                    pass

        asyncio.ensure_future(_session_timeout())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, websocket):
        logger.info(f"Client disconnected: {websocket.remote_address}")
        ws_holder["websocket"] = None

    runner = PipelineRunner(handle_sigterm=True)
    await runner.run(task)

if __name__ == "__main__":
    asyncio.run(main())
