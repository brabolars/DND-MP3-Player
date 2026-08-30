<!-- docs/ARCHITECTURE.md -->
# Architecture

## The one rule

Dependencies point in one direction:

```
gui/  ──►  engine/  ──►  audio/  ──►  core/  ──►  config.py
bot/  ──►  engine/                     ▲
                                       │
                    services.py builds all of it
```

- `core/` imports nothing but `config`. No Qt, no disnake.
- `audio/pcm.py` imports only numpy — it is the format contract everything else
  agrees on.
- `audio/` may import `core/` and `discord_api`.
- `engine/` may import `audio/` and `core/`. **Never Qt.**
- `bot/` may import `engine/` and `core/`. **Never Qt.**
- `gui/` may import anything. Nothing imports `gui/` except `app.py`.

If you find yourself wanting `from ..gui import ...` inside `engine/` or
`bot/`, that's the signal to add a callback instead. The engine already has
`on_track_change`, `on_playing_change` and `on_error` for exactly this.

Why it matters in practice: `pytest` runs the whole domain layer in 0.1s with
no display and no Discord token, and a future web front end can reuse
`build_services()` unchanged.

## The mixer

`audio/mixer.py` holds one `MixingSource` per voice session. It is handed to
disnake once, on `!join`, and lives until `!leave`.

```
Voice(envelope GainRamp) ──► bus GainRamp ──► master GainRamp ──► Discord
```

Each voice has three independent gains, multiplied together:

| Gain | Owner | Purpose |
|---|---|---|
| `Voice.gain` | engine | fade envelope — crossfades, stop-with-fade |
| `Voice.trim` | user | that track's fader strip |
| `Voice.norm_gain` | `audio/loudness.py` | static loudness match; re-derived when the target changes |

They are separate so that fading a track out doesn't destroy the user's fader
position, and toggling normalisation doesn't disturb either. `MixingSource.normalise`
gates only the third.

**Pause** is the absence of a read: a paused voice is skipped entirely, so its
decoder blocks on a full queue and its position is held exactly. Resuming
continues from that sample. Nothing is torn down, which is why pause is not a
restart.

Three invariants keep it stable:

1. **`read()` never returns `b""` while active.** disnake ends playback on a
   falsy frame, so an idle mixer returns silence. Only `cleanup()` ends it.
   The mixer is created by `MusicEngine._ensure_source()` when audio is first
   queued and torn down by `suspend_if_idle()` after 3 s of silence, so an idle
   bot transmits nothing rather than streaming encoded silence.

   **Ordering matters here.** Every `_start_*` coroutine measures loudness and
   prebuffers *before* calling `_ensure_source()`, and only then adds the voice.
   Claiming the mixer first would leave it empty across those awaits — seconds,
   on a first play — and the idle suspend would tear it down mid-start.
   `_pending_starts` blocks suspension as a second line of defence.
2. **`read()` never blocks.** Every stream has its own decoder thread and a
   bounded queue; on underrun the stream yields silence rather than stalling the
   20 ms deadline.
3. **Every voice is read every frame, even at zero gain.** Skipping the read
   would desynchronise that stream's timeline.

Gain changes always go through `GainRamp`, which slides over ~40 ms. Setting a
gain directly would produce an audible click.

Finish callbacks (`Voice.on_finish`) fire on the audio thread, *outside* the
mixer lock, so a callback may safely add another voice — which is exactly what
auto-advance does. A voice faded out to be replaced sets `notify_on_finish =
False`, otherwise a crossfade would trigger a spurious track advance.

## Adding a new kind of audio source

Sources live in `audio/stream.py`. The mixer consumes anything satisfying the
`FrameStream` protocol — two methods:

```python
class FrameStream(Protocol):
    def read_frame(self) -> Optional[bytes]: ...   # one 3840-byte frame, or None at EOF
    def stop(self) -> None: ...                    # release resources
```

Three rules, and the mixer will accept it:

1. Return **exactly** `pcm.FRAME_BYTES` (3840) — 20 ms of 48 kHz stereo int16.
   `pcm.pad_frame` handles a short final chunk.
2. Return `None` only when genuinely finished. The mixer reaps the voice and
   fires `on_finish`, which is what drives auto-advance.
3. **Never block.** `read_frame()` is called on the audio thread with a 20 ms
   budget. If your source can stall, buffer it on a thread and return
   `pcm.SILENCE` on underrun, as `FFmpegPcmStream` does.

Then create it in `engine/player.py` and add it as a `Voice` on a bus. Nothing in
`mixer.py` changes.

Concrete cases:

| Source | Approach |
|---|---|
| YouTube / any URL | `FFmpegPcmStream(url, input_options=NETWORK_INPUT_OPTIONS)` — already supported; resolve the URL with yt-dlp first |
| Anything that should repeat | Wrap the factory in `LoopingStream`, which keeps the loop flag mutable |
| A fourth bus (e.g. voice-over ducking the music) | Add the name to `BUSES` in `mixer.py`, then a `set_*_volume` on the engine |
| Generated audio (tones, TTS, procedural ambience) | New class implementing the protocol; no subprocess needed |
| Live input | Same, but must buffer — a blocking capture call would break rule 3 |

## Window layout

`MainWindow` is a `QMainWindow` whose central widget is a **zero-width,
vertically expanding placeholder**. That is load-bearing in two ways, both
learned the hard way:

- Putting real content in the centre gives it all the leftover *horizontal*
  space and squeezes the docks to the edges.
- Making the placeholder zero-height instead means leftover *vertical* space has
  nowhere to go, and Qt hands it to the top dock area — a dead band under the
  visualiser with the panels squashed below it.

Docks need `setObjectName()` for `saveState()` to work, and the saved blob is
stamped with `LAYOUT_VERSION`; bump it whenever the set of docks changes, or an
old layout restores into a window that no longer matches.

## Output sinks

The mixer doesn't know where its audio goes. Two sinks consume it:

| Sink | Lives in | Consumes frames on |
|---|---|---|
| Discord | `voice_client.play(source)` | disnake's audio thread |
| Local speakers | `gui/local_output.py` | Qt's audio thread, pulling via `QIODevice` |

`MusicEngine.local_sink` is duck-typed (`start(source)` / `stop()`), which is what
keeps Qt out of `engine/`. `_ensure_source()` starts whichever sink the current
`OutputMode` names; `_teardown_source()` stops it.

Two thread rules make local output work, and both caused silent failures when I
got them wrong:

1. **Qt audio objects must be created on the GUI thread.** The engine calls
   `start()` from its loop thread, so `LocalAudioSink` only emits a signal there;
   the slot builds the `QAudioSink` on its own thread. Built on the wrong thread
   it produces silence with no error.
2. **Playback needs an event loop even with no bot.** `_ensure_loop()` borrows the
   bot's when there is one and otherwise runs its own daemon loop, so local
   playback works with `--ui-only` and no token.

Because the sink starts asynchronously, failures come back through the `failed`
signal to `MusicEngine.handle_output_failure()` rather than as an exception.

Guards in the start coroutines go through `_output_available()`, never
`is_connected` — the latter is Discord-specific, and using it meant local
playback returned silently with no audio and no log line. Any refusal to start is
logged with its reason.

They are mutually exclusive by design: `read()` consumes a frame, so two sinks
pulling from one mixer would each get half the audio. Supporting both at once
means a tee with a buffer per consumer — worth doing only if someone actually
wants it.

## Threading model

Four threads, and it matters which is which:

| Thread | Owns | Started by |
|---|---|---|
| Main / Qt | every widget, **and QAudioSink** | `app.run()` |
| Bot | the disnake event loop | `BotRunner.start()` |
| Engine loop | playback coroutines when there is no bot | `MusicEngine._ensure_loop()` |
| Audio | calls `MixingSource.read()` every 20 ms | disnake's audio player |
| Decoder (one per stream) | pipes FFmpeg output into a frame queue | `FFmpegPcmStream` |

Rules:

- **Widgets are only ever touched on the Qt thread.** The engine reports
  through plain callables; `gui/bridge.py` assigns Qt signal `emit` methods to
  them, so every cross-thread notification becomes a queued signal.
- **Coroutines are only scheduled through `MusicEngine._schedule`**, which uses
  `run_coroutine_threadsafe` against the bot's loop and fails loudly if the bot
  isn't running.
- The engine reaches the loop through `bind_loop(provider)` rather than holding
  a reference, because the loop doesn't exist until the bot thread starts.
- Starting a stream calls `wait_until_ready` via `asyncio.to_thread`, so
  prebuffering never happens on the audio thread or the event loop.

## Where does my change go?

| I want to... | Touch |
|---|---|
| Add a Discord command | a cog in `bot/cogs/`, then register it in `BotRunner._register_cogs` |
| Add a playback feature (ducking, seek) | `engine/player.py` — add a bus or a voice, plus a control in `gui/widgets/` |
| Add an output destination (file recording, second device) | a sink class with `start`/`stop`, then a case in `_ensure_source()` |
| Change loudness targets or measurement | `audio/loudness.py` — nothing else computes gain from LUFS |
| Investigate "too loud" reports | `MusicEngine.diagnostics()` and `effective_music_db()`; the mixer counts clipped frames |
| Change how FFmpeg is invoked | `audio/stream.py` — the only place that spawns FFmpeg |
| Change how audio is combined | `audio/mixer.py` — the only place samples are summed |
| Change the frame format | `audio/pcm.py` — everything derives from it |
| Add a library field (BPM, tags, duration) | `core/models.py` `MusicTrack`, then `to_dict`/`from_dict` |
| Add a theme | `gui/theme/presets.py` |
| Add a UI panel | new file in `gui/widgets/`, expose signals, wire it in `MainWindow._connect_signals` |
| Change where files live | `config.py` only |
| Add a startup flag | `cli.py`, then thread it through `services.build_services` |

## Widget contract

Widgets are dumb by design:

1. They render what they're given via a `set_*` method.
2. They emit a signal describing **intent** (`play_requested`, `rename_requested`).
3. They never import the library, the engine or the bot.

`MainWindow` is the only place that knows how an intent maps to an action. That
means a widget can be tested, restyled or replaced without touching logic, and
`MainWindow` reads as a table of contents for the whole app.

## Adding a second front end

`services.build_services(args)` returns everything the UI needs and imports no
Qt. A web dashboard or a headless "player node" would:

```python
from dndmusic.cli import AppArgs
from dndmusic.services import build_services

services = build_services(AppArgs(ui_only=False))
services.engine.on_track_change = my_websocket_push
BotRunner(token, BotContext(services.engine, services.library, services.debug)).start()
```

That is the whole integration surface — which is the point of the split.
