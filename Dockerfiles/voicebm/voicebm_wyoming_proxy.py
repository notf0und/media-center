#!/usr/bin/env python3
"""VoiceBM Wyoming Proxy.

Pure proxy between Home Assistant and your existing Parakeet ASR service.
VoiceBM only handles speaker identification (Sherpa-ONNX via voicebm_stt_service).
The actual transcription is always done by the upstream Parakeet container.

Flow:
  HA → voicebm:10301 → [speaker ID via MQTT] → parakeet:10300 → transcript
                                                                      ↓
                                              publishes to voicebm/living/current_speaker
                                              (HA reads this for personalized intents)

UPSTREAM_WYOMING_URI accepts any TCP address, e.g.:
  tcp://localhost:10300         (default, direct)
  tcp://parakeet.home:10300     (hostname)
  tcp://192.168.1.50:10300      (IP)
  tcp://parakeet.test:10300     (Traefik TCP router)

Set VOICEBM_INJECT_SPEAKER=true to prepend speaker name to transcript
("Gonzalo: where is my phone") for slot-based HA intent matching.
Default is false — speaker is only available via the MQTT sensor.

All settings come from environment variables in docker-compose.yml.
To change: update docker-compose.yml → docker-compose up -d --force-recreate voicebm
"""

import asyncio
import json
import logging
import os
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

import dataclasses

import paho.mqtt.client as mqtt
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcribe, Transcript
from wyoming.client import AsyncClient
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("voicebm.proxy")

# ---------------------------------------------------------------------------
# Configuration (all from docker-compose.yml environment section)
# ---------------------------------------------------------------------------
VOICEBM_WYOMING_PORT   = int(os.getenv("VOICEBM_WYOMING_PORT", "10301"))
UPSTREAM_WYOMING_URI   = os.getenv("UPSTREAM_WYOMING_URI", "tcp://localhost:10300")
VOICEBM_SERVICE_NAME   = os.getenv("VOICEBM_SERVICE_NAME", "voicebm")  # name shown in HA
MQTT_BROKER            = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT              = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER              = os.getenv("MQTT_USER", "")
MQTT_PASS              = os.getenv("MQTT_PASS", "")
SHARED_AUDIO_DIR       = os.getenv("SHARED_AUDIO_DIR", "/data/stt_requests")
ANALYSIS_TIMEOUT       = int(os.getenv("VOICEBM_ANALYSIS_TIMEOUT", "20"))
INJECT_SPEAKER         = os.getenv("VOICEBM_INJECT_SPEAKER", "false").lower() == "true"

VB_REQUEST_TOPIC       = "voicebm/stt/analyze_request"
VB_RESPONSE_TOPIC_BASE = "voicebm/stt/analyze_response"
VB_CURRENT_SPEAKER     = "voicebm/living/current_speaker"
VB_TRANSCRIPT_TOPIC    = "voicebm/transcript/full"


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
        # Forward Describe to real Parakeet, then rename programs to VOICEBM_SERVICE_NAME
        if Describe.is_type(event.type):
            try:
                async with AsyncClient.from_uri(UPSTREAM_WYOMING_URI) as client:
                    await client.write_event(event)
                    info_event = await asyncio.wait_for(client.read_event(), timeout=10.0)
                    if info_event:
                        info = Info.from_event(info_event)
                        renamed_asr = [
                            dataclasses.replace(p, name=VOICEBM_SERVICE_NAME)
                            for p in info.asr
                        ]
                        await self.write_event(dataclasses.replace(info, asr=renamed_asr).event())
            except Exception as exc:
                _LOGGER.warning(f"Could not fetch upstream Info: {exc}")
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
            speaker_id, display_name, confidence, inject_enabled, is_blocked = \
                await loop.run_in_executor(None, request_speaker_id, audio_path)

            _LOGGER.info(
                f"Speaker: {display_name!r} conf={confidence:.3f} blocked={is_blocked}"
            )

            if is_blocked:
                await self.write_event(Transcript(text="").event())
                return

            # Transcription from the real Parakeet — no ASR model runs here
            transcript = await self._get_upstream_transcript()

            # Prepend speaker name only if VOICEBM_INJECT_SPEAKER=true
            if INJECT_SPEAKER and inject_enabled and speaker_id not in ("unknown", ""):
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

    async def _get_upstream_transcript(self) -> str:
        """Forward all buffered audio to the real Parakeet and return the transcript text."""
        try:
            async with AsyncClient.from_uri(UPSTREAM_WYOMING_URI) as client:
                await client.write_event(Transcribe(language=self._language).event())
                await client.write_event(
                    AudioStart(rate=self._rate, width=self._width, channels=self._channels).event()
                )
                for chunk in self._audio_chunks:
                    await client.write_event(chunk.event())
                await client.write_event(AudioStop().event())

                while True:
                    ev = await asyncio.wait_for(client.read_event(), timeout=60.0)
                    if ev is None:
                        break
                    if Transcript.is_type(ev.type):
                        return Transcript.from_event(ev).text

        except asyncio.TimeoutError:
            _LOGGER.error("Upstream Parakeet timed out")
        except Exception as exc:
            _LOGGER.error(f"Upstream Parakeet error: {exc}", exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    _LOGGER.info(
        f"VoiceBM Proxy  port={VOICEBM_WYOMING_PORT}  upstream={UPSTREAM_WYOMING_URI}"
    )
    _LOGGER.info(f"Speaker injection={'on' if INJECT_SPEAKER else 'off (MQTT sensor only)'}")
    server = AsyncServer.from_uri(f"tcp://0.0.0.0:{VOICEBM_WYOMING_PORT}")
    _LOGGER.info("Ready")
    await server.run(VoiceBMProxyHandler)


if __name__ == "__main__":
    asyncio.run(main())
