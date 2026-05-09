# Copilot Instructions

## What This Repo Is

A self-hosted home media center and smart home stack, orchestrated via a single `docker-compose.yml`. Two layers:

1. **Media stack** — Plex, Sonarr, Radarr, Bazarr, Prowlarr, Transmission, Kavita, Threadfin, Music Assistant
2. **Local voice AI pipeline** — fully offline STT → LLM → TTS stack for ESP32 satellite voice control, integrated with Home Assistant

Custom code lives entirely in `Dockerfiles/` and `scripts/`. Everything else is third-party image configuration.

---

## Common Commands

```bash
# Start / restart services
docker-compose up -d                              # bring up all services
docker-compose up -d <service>                   # start one service
docker-compose up -d --force-recreate <service>  # apply env var changes (no rebuild)
docker-compose up -d --build <service>           # rebuild image + restart

# Logs
docker-compose logs -f <service>
docker logs -f <service>

# Update Муз-ТВ stream URL (when it breaks) and restart streamlink
python3 scripts/update-muztv-link.py

# llama.cpp helper (start/stop/restart/logs/status/test/benchmark/models/health/rebuild)
./scripts/llama-manage.sh <command>
```

---

## Architecture

### Networking

- All services sit behind an external **Traefik** reverse proxy.
- Services reachable at `<service-name>.test` hostnames (e.g. `https://homeassistant.test`).
- TLS is provided by a local root CA at `/home/gonzalo/code/traefik/generate_certificates/root-certificates/root-ca.crt`.
- Services that use the Wyoming voice protocol or need mDNS use `network_mode: host`.
- Web-only services join the `app-bridge` bridge network (`172.21.0.0/16`) and get Traefik labels.
- Sensitive services (bazarr, zigbee2mqtt) have `traefik.http.routers.*-https.middlewares: authentik-outpost@docker`.

### Voice AI Pipeline

The most custom part of the repo. Audio path:

```
ESP32 mic → WebSocket (port 8765) → local-voice-pipeline → STT → LLM → TTS → WebSocket → ESP32 speaker
```

Key services and their ports:

| Service | Wyoming (HA) | OpenAI API | Notes |
|---|---|---|---|
| `parakeet-asr` | 10300 | 5052 | NeMo Parakeet batch ASR |
| `voicebm` | 10301 | — | Speaker ID proxy wrapping parakeet |
| `sherpa-onnx-asr` | 10303 | 5054 | Cohere/Whisper/SenseVoice batch ASR |
| `kokoro-tts` | 10210 | 5051 | Kokoro TTS |
| `supertonic-tts` | — | 5050 | Diffusion TTS |
| `bonsai-llm` | — | 8085 | Qwen3 1.7B quantized (ik_llama.cpp) |
| `ollama` | — | 11434 | Full Ollama server |
| `local-voice-pipeline` | — | WS 8765 | Pipecat pipeline (STT+LLM+TTS) |

`voicebm` (port 10301) is a Wyoming proxy: HA sends audio here → speaker is identified via MQTT → audio is forwarded to `parakeet` (10300) for transcription → result returned to HA with optional speaker prefix.

### `local-voice-pipeline` internals (`Dockerfiles/local-voice-pipeline/`)

Built on [Pipecat AI](https://github.com/pipecat-ai/pipecat). The pipeline stages in order:

```
transport.input → STT → [SttTextForwarder] → context_aggregator.user → LLM
  → [TtsTextForwarder] → TTS → transport.output → context_aggregator.assistant
```

`SttTextForwarder` and `TtsTextForwarder` send JSON text frames to the ESP32 for display.

**Factory pattern** — STT, LLM, and TTS services are instantiated from env vars via `app/services/{stt,llm,tts}_factory.py`. No code changes needed to switch providers; only env vars in `docker-compose.yml`.

**LLM tool integration** — either MCP (preferred, `MCP_SERVER_URL`) or direct HA REST (`HA_TOKEN`). The `EntityMemory` class (`app/services/entity_memory.py`) caches discovered `entity_id → friendly_name` mappings to `/data/entity_memory.json` to skip repeat searches.

### Media Stack

- `./downloads/` is the shared data volume for all *arr services.
- Per-service config dirs are at `./config/<service>/`.
- `streams.yaml` defines TV channels for the `streamlink` service — one entry per channel with `name`, `stream` (URL), and `port` (46200–46250 range).

---

## Key Conventions

### Changing models or config

All custom services load config entirely from environment variables. To switch a model or tune a parameter:
1. Edit the relevant `environment:` block in `docker-compose.yml`
2. Run `docker-compose up -d --force-recreate <service>` — **no rebuild needed** for env-only changes
3. Only `docker-compose up -d --build <service>` is needed when `Dockerfile` or source code changes

### Qwen3 / Bonsai models

Qwen3-based models (including `bonsai-llm`) require `/nothink\n\n` prepended to the system prompt to suppress chain-of-thought reasoning. `pipeline_builder.py` does this automatically when `LLM_PROVIDER=bonsai` or the model name contains `qwen3`.

### Custom entrypoints via mounted scripts

Custom services use a mounted entrypoint script (e.g. `./config/<service>/start_services.sh` or `./scripts/<service>/entrypoint.sh`) rather than baking scripts into the image. This allows editing the startup script without a Docker rebuild.

### Two-router Traefik pattern

Every service that needs HTTP→HTTPS redirect has two Traefik routers: `<name>` (HTTP, with `redirectScheme` middleware) and `<name>-https` (HTTPS with TLS). Services that shouldn't redirect (e.g. Music Assistant) omit the redirect middleware.

### `streams.yaml` format

```yaml
- name: Channel Name
  stream: https://youtube.com/@channel/live
  port: 462XX
```

The `streamlink` container reads this at startup and spawns one `streamlink` process per entry. To add a channel, add an entry and restart the container.

### Adding a new Dockerised service

Follow the existing pattern:
- `build.context: ./Dockerfiles/<name>`, `build.dockerfile: Dockerfile`
- Mount config to `./config/<name>:/data`
- Use `network_mode: host` if it needs Wyoming/mDNS; otherwise join `app-bridge` with Traefik labels
- Use `entrypoint: ["/bin/bash", "/data/start_services.sh"]` with the script mounted as a volume so it's editable without rebuilds
- All tunable parameters via `environment:` block

### ASR model selection (parakeet-asr, sherpa-onnx-asr)

Both services download models on first start and cache them in `./config/<service>/`. Change `PARAKEET_MODEL` or `SHERPA_MODEL` env var and `--force-recreate` to switch. CPU RTFx benchmarks are documented in the compose file comments.
