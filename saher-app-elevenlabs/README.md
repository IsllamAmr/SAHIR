# Saher with an ElevenLabs voice (trial only)

This is an experiment, kept apart from `..\saher-app\`. ElevenLabs is a paid cloud service, so this copy breaks the project's open-source, self-hosted rule. Fasee7 stays Saher's target voice.

**What leaves your computer:** the text of every reply that is spoken (sentence by sentence) goes to ElevenLabs and uses your credits. Your voice, the transcript and the conversation history do not; Whisper and ALLaM still run here. With the 🔇 switch, nothing is sent to ElevenLabs.

## Put your API key in (once)

1. On elevenlabs.io: Profile → API Keys → create a key. Giving it only the "Text to Speech" permission and a credit limit is a good idea.
2. In this folder, open PowerShell and run:
   ```
   copy .env.example .env
   notepad .env
   ```
3. Paste the key right after `ELEVENLABS_API_KEY=` (no spaces, no quotes), save, close Notepad.

The key stays in `.env` in this folder. It is never printed, logged or sent anywhere except to ElevenLabs. Don't share or upload this folder with `.env` in it. (An `ELEVENLABS_API_KEY` environment variable also works and wins over `.env`.)

## Start it

Make sure Ollama is running, then double-click `start_saher_elevenlabs.bat`. Wait for "Saher (ElevenLabs trial) is running at http://127.0.0.1:8769/"; the page opens by itself. It uses port 8769, so it can run next to the main app (8767), though both share the same ALLaM.

Everything works like the main app: typing, push-to-talk (🎙 or Space) with the transcript to review before sending, one shared conversation, the 🔊/🔇 switch, وقف, محادثة جديدة and إنهاء.

Under each reply: **first text** (ALLaM's first words), **first audio** (first ElevenLabs audio back), **full text**, **full reply** (last audio received) and **heard** (when sound actually started in the browser). If ElevenLabs fails (wrong key, no credits, no internet), the text reply still arrives and the line ends with "الصوت وقف:" and the reason.

## Settings

- Voice: `rpGHcNQJvO8dFNNFNj1v` (`ELEVENLABS_VOICE_ID` to change it).
- Model: `eleven_flash_v2_5`, ElevenLabs' lowest-latency multilingual model, with Arabic (`ELEVENLABS_MODEL` to try e.g. `eleven_turbo_v2_5` or `eleven_multilingual_v2`).
- Audio: 22.05 kHz PCM, streamed to the page in about 0.2 s pieces. Each sentence goes out as soon as ALLaM finishes it, with the previous sentences as context so the intonation flows.
- Persona: read (never edited) from `..\saher-chat\persona_allam_v4.txt` on every turn.
- Also: `SAHER_MODEL`, `SAHER_PORT`, `SAHER_NO_BROWSER=1`, as in the main app.
