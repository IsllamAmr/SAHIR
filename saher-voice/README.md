# Saher voice (push-to-talk)

Double-click `start_voice.bat`. A page opens at http://127.0.0.1:8766/. Hold the button or the Space bar, talk, then let go. Saher starts speaking his first sentence while ALLaM is still writing the rest of the reply. Each reply on the page shows its four timings.

## What runs where

| Piece | Component | Runs on | License |
|---|---|---|---|
| Speech recognition | faster-whisper `small`, int8, 4 threads | CPU (~0.5 GB RAM) | MIT |
| Reply | ALLaM-7B `allam-7b-saher` via local Ollama, streamed | 65% GPU / 35% CPU (unchanged) | Apache-2.0 |
| Speech | Piper 1.8 `ar_JO-kareem-medium` | CPU (~0.2 GB RAM) | piper-tts GPL-3.0, voice per its model card |

No speech component uses the GPU, so ALLaM keeps all the VRAM it had.

The persona comes from `..\saher-chat\persona_core.txt`. It is read on every turn and never edited. A short note asks for one or two sentences, because the reply is spoken. To use a different persona file, set `SAHER_PERSONA`. Replies are capped at 90 tokens.

## Timings (`python bench.py 3`, 15 turns, GPU idle)

Each timing is measured from the moment you let go of the button.

| | median | min | max |
|---|---|---|---|
| Transcribed | 1.66 s | 1.29 s | 1.91 s |
| First text | 2.08 s | 1.61 s | 2.46 s |
| First audio (Saher starts speaking) | 2.31 s | 2.05 s | 3.01 s |
| Full reply generated and voiced | 4.11 s | 2.63 s | 5.58 s |

The test questions were spoken by the Piper voice, not by a person. A real voice will transcribe less cleanly, and a longer question takes a little longer to transcribe. Raw runs are in `results\`.

## Why it is fast now

- Ollama is called at `127.0.0.1`, not `localhost`. On this Windows setup, `localhost` added about 2.1 s to every request, apparently from trying IPv6 first. `saher-chat\chat_server.py` still uses `localhost`.
- The first chunk is sent to speech at the first comma, or after 6 words, so audio starts before the first sentence is finished.
- Whisper runs best with 4 threads here: 1.3 s, against 1.6 s with 8 threads and 2.1 s with 12.
