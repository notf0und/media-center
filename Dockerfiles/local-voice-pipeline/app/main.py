#!/usr/bin/env python3
"""Local voice pipeline — WebSocket server entry point"""
import asyncio, logging, os, signal
from pipecat.transports.network.websocket_server import WebsocketServerParams, WebsocketServerTransport
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.vad.vad_analyzer import VADParams

from .pipeline_builder import build_pipeline
from .raw_audio_serializer import RawAudioSerializer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

HOST = os.environ.get("WEBSOCKET_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBSOCKET_PORT", 8765))
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", 0.5))
VAD_SILENCE_MS = int(os.environ.get("VAD_SILENCE_DURATION_MS", 600))
VAD_PREFIX_MS = int(os.environ.get("VAD_PREFIX_PADDING_MS", 300))

async def run_pipeline_for_connection(websocket, path):
    logger.info(f"New connection from {websocket.remote_address}")

    transport = WebsocketServerTransport(
        websocket=websocket,
        params=WebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                threshold=VAD_THRESHOLD,
                min_silence_duration_ms=VAD_SILENCE_MS,
                prefix_padding_ms=VAD_PREFIX_MS,
            )),
            vad_audio_passthrough=True,
            serializer=RawAudioSerializer(),
        ),
    )

    pipeline = await build_pipeline(transport)
    task = PipelineTask(pipeline)

    try:
        await task.run()
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
    finally:
        logger.info("Connection closed")

async def main():
    logger.info(f"Starting local-voice-pipeline on ws://{HOST}:{PORT}")

    import websockets
    server = await websockets.serve(run_pipeline_for_connection, HOST, PORT)
    logger.info(f"WebSocket server listening on ws://{HOST}:{PORT}")

    loop = asyncio.get_event_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)

    await stop
    server.close()
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
