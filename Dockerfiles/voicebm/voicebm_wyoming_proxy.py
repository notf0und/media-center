#!/usr/bin/env python3
"""VoiceBM Wyoming Proxy with Embedded STT.

VoiceBM handles both:
1. Speaker identification (Sherpa-ONNX speaker recognition)
2. Speech-to-text transcription (embedded Sherpa-ONNX offline recognizer)

This makes voicebm completely self-contained — no dependency on external
parakeet/sherpa-onnx-asr services.

Flow:
  HA → voicebm:10301 → [speaker ID via MQTT + embedded STT] → transcript
                                                                    ↓
                                                publishes to voicebm/living/current_speaker
                                                (HA reads this for personalized intents)

Set speaker identification via VoiceBM dashboard UI settings
("Gonzalo: where is my phone") for slot-based HA intent matching.
Default is false — speaker is only available via the MQTT sensor.

STT model selection via environment variables:
  VOICEBM_STT_MODEL    - Model name (default: cohere-transcribe)
  VOICEBM_STT_LANGUAGE - Language code (default: en)
  VOICEBM_STT_THREADS  - CPU threads (default: 4)

All settings come from environment variables in docker-compose.yml.
To change: update docker-compose.yml → docker-compose up -d --force-recreate voicebm
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

import dataclasses

import paho.mqtt.client as mqtt
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcribe, Transcript
from wyoming.event import Event
from wyoming.info import Describe, Info, AsrModel, AsrProgram, Attribution
from wyoming.server import AsyncEventHandler, AsyncServer

# Import embedded STT engine
sys.path.insert(0, "/app")
import voicebm_stt_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("voicebm.proxy")

# ---------------------------------------------------------------------------
# Configuration (all from docker-compose.yml environment section)
# ---------------------------------------------------------------------------
VOICEBM_WYOMING_PORT   = int(os.getenv("VOICEBM_WYOMING_PORT", "10301"))
VOICEBM_SERVICE_NAME   = "voicebm"  # hardcoded service name shown in HA
MQTT_BROKER            = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT              = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER              = os.getenv("MQTT_USER", "")
MQTT_PASS              = os.getenv("MQTT_PASS", "")
SHARED_AUDIO_DIR       = os.getenv("SHARED_AUDIO_DIR", "/data/stt_requests")
ANALYSIS_TIMEOUT       = int(os.getenv("VOICEBM_ANALYSIS_TIMEOUT", "20"))
SETTINGS_FILE          = "/data/meta/settings.json"

# STT configuration (embedded engine)
VOICEBM_STT_MODEL      = os.getenv("VOICEBM_STT_MODEL", "cohere-transcribe")
VOICEBM_STT_LANGUAGE   = os.getenv("VOICEBM_STT_LANGUAGE", "en")
VOICEBM_STT_THREADS    = int(os.getenv("VOICEBM_STT_THREADS", "4"))
VOICEBM_STT_MODEL_DIR  = os.getenv("VOICEBM_STT_MODEL_DIR", "/data/stt-models")

VB_REQUEST_TOPIC       = "voicebm/stt/analyze_request"
VB_RESPONSE_TOPIC_BASE = "voicebm/stt/analyze_response"
VB_CURRENT_SPEAKER     = "voicebm/living/current_speaker"
VB_TRANSCRIPT_TOPIC    = "voicebm/transcript/full"

# Global STT engine instance
_STT_ENGINE = None


# ---------------------------------------------------------------------------
# Settings management
# ---------------------------------------------------------------------------
def get_inject_identity_setting() -> bool:
    """Read the inject_identity setting from settings.json.
    
    This allows real-time control from VoiceBM UI without needing a container restart.
    Default to True if file doesn't exist or can't be read.
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                return settings.get('inject_identity', True)
    except Exception as e:
        _LOGGER.warning(f"Failed to read settings from {SETTINGS_FILE}: {e}")
    return True  # Default to True if can't read


# ---------------------------------------------------------------------------
# Speaker identification (synchronous — runs in thread executor)
# ---------------------------------------------------------------------------
def request_speaker_id(audio_path: str) -> tuple[str, str, float, bool, bool]:
    """Ask voicebm_stt_service to identify the speaker in audio_path via MQTT.

    Returns (speaker_id, display_name, confidence, inject_enabled, is_blocked).
    Falls back to ("unknown", "unknown", 0.0, True, False) on timeout/error.
    """
    request_id = str(uuid.uuid4())
    response_topic = f"{VB_RESPONSE_TOPIC_BASE}/{request_id}"
    result: dict = {"done": False, "data": None}

    def on_connect(client, userdata, flags, rc, properties=None):
        client.subscribe(response_topic, qos=1)

    def on_message(client, userdata, msg):
        try:
            result["data"] = json.loads(msg.payload.decode())
            result["done"] = True
        except Exception as exc:
            _LOGGER.warning(f"Bad speaker-ID response: {exc}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        client.publish(VB_REQUEST_TOPIC, json.dumps({
            "request_id": request_id,
            "audio_path": audio_path,
        }), qos=1)

        deadline = time.time() + ANALYSIS_TIMEOUT
        while not result["done"] and time.time() < deadline:
            time.sleep(0.05)

        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        _LOGGER.error(f"MQTT error during speaker ID: {exc}")
        return "unknown", "unknown", 0.0, True, False

    if not result["done"] or result["data"] is None:
        _LOGGER.warning("Speaker ID timed out — proceeding as unknown")
        return "unknown", "unknown", 0.0, True, False

    d = result["data"]
    return (
        d.get("speaker_id", "unknown"),
        d.get("display_name", "unknown"),
        float(d.get("confidence", 0.0)),
        bool(d.get("inject_enabled", True)),
        bool(d.get("is_blocked", False)),
    )


def publish_speaker_state(
    speaker_id: str, display_name: str, confidence: float, transcript: str
) -> None:
    """Publish current speaker + transcript to MQTT for HA sensors."""
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        client.publish(VB_CURRENT_SPEAKER, json.dumps({
            "speaker_id": speaker_id,
            "display_name": display_name,
            "confidence": round(confidence, 4),
        }), qos=1, retain=True)
        if transcript:
            client.publish(VB_TRANSCRIPT_TOPIC, json.dumps({
                "speaker": display_name,
                "text": transcript,
                "timestamp": time.time(),
            }), qos=1, retain=True)
        time.sleep(0.15)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        _LOGGER.warning(f"Failed to publish speaker state: {exc}")


# ---------------------------------------------------------------------------
# Wyoming proxy handler (one instance per HA connection)
# ---------------------------------------------------------------------------
class VoiceBMProxyHandler(AsyncEventHandler):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._audio_chunks: list[AudioChunk] = []
        self._rate: int = 16000
        self._width: int = 2
        self._channels: int = 1
        self._language: Optional[str] = None
        Path(SHARED_AUDIO_DIR).mkdir(parents=True, exist_ok=True)

    async def handle_event(self, event: Event) -> bool:
        # Describe: return info about embedded STT + speaker ID
        if Describe.is_type(event.type):
            try:
                info = Info(
                    asr=[
                        AsrProgram(
                            name=VOICEBM_SERVICE_NAME,
                            description="VoiceBM (embedded STT + speaker ID)",
                            version="1.0",
                            attribution=Attribution(
                                name="VoiceBM + sherpa-onnx",
                                url="https://github.com/cybericebyte/VoiceBM",
                            ),
                            installed=True,
                            models=[
                                AsrModel(
                                    name=VOICEBM_STT_MODEL,
                                    description=VOICEBM_STT_MODEL,
                                    version="1.0",
                                    attribution=Attribution(
                                        name="k2-fsa", url="https://github.com/k2-fsa/sherpa-onnx"
                                    ),
                                    installed=True,
                                    languages=[VOICEBM_STT_LANGUAGE],
                                )
                            ],
                        )
                    ]
                )
                await self.write_event(info.event())
            except Exception as exc:
                _LOGGER.warning(f"Error building Describe response: {exc}")
            return True

        if Transcribe.is_type(event.type):
            self._language = Transcribe.from_event(event).language
            return True

        if AudioStart.is_type(event.type):
            a = AudioStart.from_event(event)
            self._rate, self._width, self._channels = a.rate, a.width, a.channels
            self._audio_chunks = []
            return True

        if AudioChunk.is_type(event.type):
            self._audio_chunks.append(AudioChunk.from_event(event))
            return True

        if AudioStop.is_type(event.type):
            await self._process_audio()
            return True

        return True

    async def _process_audio(self) -> None:
        if not self._audio_chunks:
            await self.write_event(Transcript(text="").event())
            return

        filename = f"{uuid.uuid4()}.wav"
        audio_path = os.path.join(SHARED_AUDIO_DIR, filename)
        try:
            with wave.open(audio_path, "wb") as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(self._width)
                wf.setframerate(self._rate)
                for chunk in self._audio_chunks:
                    wf.writeframes(chunk.audio)

            loop = asyncio.get_running_loop()
            
            # Run speaker ID and STT in parallel for better performance
            speaker_result, transcript = await asyncio.gather(
                loop.run_in_executor(None, request_speaker_id, audio_path),
                self._get_embedded_transcript()
            )
            
            speaker_id, display_name, confidence, inject_enabled, is_blocked = speaker_result

            _LOGGER.info(
                f"Speaker: {display_name!r} conf={confidence:.3f} blocked={is_blocked}"
            )

            if is_blocked:
                await self.write_event(Transcript(text="").event())
                return

            # Prepend speaker name only if injection is enabled in settings
            inject_speaker = get_inject_identity_setting()
            if inject_speaker and inject_enabled and speaker_id not in ("unknown", "") and display_name not in ("unknown", "", None):
                final_text = f"{display_name}: {transcript}"
            else:
                final_text = transcript

            # Publish who spoke to MQTT → HA sensor → used by intent scripts
            await loop.run_in_executor(
                None, publish_speaker_state, speaker_id, display_name, confidence, final_text
            )

            _LOGGER.info(f"Transcript: {final_text!r}")
            await self.write_event(Transcript(text=final_text).event())

        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

    async def _get_embedded_transcript(self) -> str:
        """Recognize speech using embedded STT engine."""
        if not self._audio_chunks or not _STT_ENGINE:
            return ""

        try:
            loop = asyncio.get_running_loop()
            
            # Combine audio chunks into a single buffer
            raw_audio = b"".join(chunk.audio for chunk in self._audio_chunks)
            
            # Run STT in executor (it's CPU-intensive)
            text = await loop.run_in_executor(
                None, _STT_ENGINE.recognize, raw_audio, self._rate
            )
            return text
        except Exception as exc:
            _LOGGER.error(f"Embedded STT error: {exc}", exc_info=True)
            return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    global _STT_ENGINE
    
    inject_status = get_inject_identity_setting()
    _LOGGER.info(
        f"VoiceBM Proxy  port={VOICEBM_WYOMING_PORT}  STT={VOICEBM_STT_MODEL}"
    )
    _LOGGER.info(f"Speaker injection={inject_status} (from {SETTINGS_FILE})")
    
    # Initialize embedded STT engine
    try:
        _STT_ENGINE = voicebm_stt_engine.init_stt_engine(
            model_name=VOICEBM_STT_MODEL,
            model_dir=VOICEBM_STT_MODEL_DIR,
            language=VOICEBM_STT_LANGUAGE,
            num_threads=VOICEBM_STT_THREADS,
        )
        _LOGGER.info("Embedded STT engine ready")
    except Exception as exc:
        _LOGGER.error(f"Failed to initialize STT engine: {exc}")
        raise
    
    server = AsyncServer.from_uri(f"tcp://0.0.0.0:{VOICEBM_WYOMING_PORT}")
    _LOGGER.info("Ready")
    await server.run(VoiceBMProxyHandler)


if __name__ == "__main__":
    asyncio.run(main())
