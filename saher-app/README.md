# Saher (text + voice in one app)

Double-click `start_saher.bat` (or run `python server.py` in this folder). Wait for "Saher is running at http://127.0.0.1:8767/" in the black window; the page opens by itself. Make sure Ollama is running first.

You can type, or hold the 🎙 button (or the Space bar when you are not in the text box) and talk. Both go into the same conversation, so Saher remembers what you typed when you talk and the other way round.

- **Talking**: when you let go, what Whisper heard goes into the text box (highlighted) instead of being sent. Correct it, then press إرسال or Enter. إلغاء or Esc throws it away. Messages that started as speech show 🎙.
- **🔊 الردود بصوت / 🔇 الردود صامتة**: one switch for every reply. Every reply is always shown as text; when the switch is on it is also spoken. The page remembers your choice.
- Replies to spoken messages are kept to one or two sentences; typed messages get normal-length replies.
- **وقف** (or Esc) stops a reply and its voice. Whatever was said so far stays in the conversation.
- **محادثة جديدة** clears the conversation; **إنهاء** shuts the app down.

Nothing is written to disk or logged. The conversation lives only in the open tab.

## What runs where

| Piece | Component | Runs on |
|---|---|---|
| Speech recognition | faster-whisper `small`, int8, 4 threads | CPU |
| Reply | ALLaM-7B `allam-7b-saher` via local Ollama at 127.0.0.1, streamed | GPU/CPU split as before |
| Speech | Piper `ar_JO-kareem-medium` | CPU |

Whisper and Piper stay on the CPU so ALLaM keeps all 6 GB of VRAM.

## Files it reads (never edits)

- Persona: `..\saher-chat\persona_allam_v4.txt`, re-read on every turn. Spoken messages add a short note asking for one or two sentences. Set `SAHER_PERSONA` to use another file.
- Voice: `..\saher-voice\voices\ar_JO-kareem-medium.onnx` (set `SAHER_VOICE` to move it).

Typed replies are capped at 400 tokens and spoken ones at 90. Other settings: `SAHER_MODEL`, `SAHER_PORT` (default 8767), `SAHER_NO_BROWSER=1`.
