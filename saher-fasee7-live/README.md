# Saher hands-free trial (three voices)

| Launcher | Voice | Port | Reply ready after your speech arrives (measured) |
|---|---|---|---|
| `start_fast_piper.bat` | Piper ar_JO-kareem, CPU (fastest) | 8771 | 2.9-3.8 s |
| `start_saudi_namaa.bat` | NAMAA Saudi TTS, GPU | 8772 | 7.0-10.7 s |
| `start_fasee7_live.bat` | Fasee7 Najdi Small, GPU | 8770 | 47-95 s |

Saher speaks Modern Standard Arabic only here (`persona_fusha.txt` in this folder, plus a voice note asking for
fusha). Set `SAHER_STYLE=saudi` to use the Saudi dialect persona from saher-chat instead. A launcher refuses to start
if its port is already taken by another open copy.

Of those times, Whisper takes ~2.1 s and ALLaM ~0.5-1 s; the rest is the voice. Run one launcher at a time.
`test_reply_*.wav` are replies from each voice to the same question. The rest of this file describes the Fasee7 trial.

Experimental and separate from saher-app and saher-voice. Double-click `start_fasee7_live.bat`, wait for the page
(Fasee7 takes about 1.5 minutes to load), press "ابدأ المحادثة" once, then just talk. Port 8770.

- Speech recognition: faster-whisper small on CPU. LLM: allam-7b-saher in Ollama with persona_allam_v4.txt (read only).
- Voice: Fasee7 Najdi Small on VoxCPM2, default voice (seed 1234), run by `tts_worker.py` inside
  `saher-tts-compare\venv-voxcpm` (nothing installed or changed there).
- Hands-free: an energy detector in the page with an adaptive noise floor. Speech starts after ~130 ms above the
  threshold and ends after 0.9 s of silence. The mic is ignored while Saher thinks or speaks. Slider = sensitivity.
- One short sentence: asked for in the prompt and enforced in code (first sentence, at most 14 words; an echoed
  opening question is dropped when an answer follows it). A ✂ on a reply means the code cut it.
- Playback: audio streams only if Fasee7 runs faster than real time; otherwise the whole reply is generated first and
  played in one go. On this laptop it is always the second case.
- Memory: the worker streams the base weights to the GPU tensor by tensor from a plain file read. voxcpm's own loader
  (and safetensors' mmap loader) reserve another 4.6 GB of commit memory and crashed with an access violation next to ALLaM.

`e2e_test.py question.wav` runs one turn without a microphone against a running server.
`test_reply.wav` is the reply from the first verified exchange.
