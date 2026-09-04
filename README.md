<!-- README.md -->
# D&D Music Manager

Discord music bot for tabletop sessions, driven from a PyQt6 control surface.
The DM builds a library of tracks, ambient beds and one-shot SFX, then plays
them into a voice channel with crossfades and optional real-time ambient mixing.

- In-process audio mixer: music, ambient bed and SFX all play at once, and every
  control is live — changing volume or swapping the ambient bed never restarts
  the music
- Layer up to 6 music tracks simultaneously, each with its own fader and loop toggle
- Four playback modes: single track, playlist, shuffle, and multi-track layering
- Works as a plain music player too — switch the output from the Discord bot to
  this PC's speakers
- Search box over the library, plus bulk import of a folder tree or an old install
- Dockable panels: float them, tab them, arrange them; the layout is remembered
- Themes with background images, opacity and a darkening veil
- Loudness normalisation (EBU R128 / LUFS) that tames loud tracks without ever
  making anything louder
- Categorised music library that tracks the folders on disk, so you can drop
  files in with Explorer and they appear
- Playlists: single track (looped), sequential, shuffle
- Crossfade transitions with a configurable duration
- Independent music / ambient / SFX / master levels
- 8 preset themes plus a theme editor, and three visualiser styles
- Discord commands: `!join`, `!leave`, `!debug`, `!check`

---

## How the audio works

One `MixingSource` is handed to disnake when the bot joins a channel, and it
stays there until the bot leaves. FFmpeg decodes each file to raw PCM on its own
thread; the mixer sums 20 ms frames from every active voice, applies per-voice
envelopes, per-bus gains and a master gain, and hands one frame back to Discord.

```
music voice   ─┐
music voice   ─┼─► music bus  ─┐          (crossfade = two music voices,
               ┘                │           one fading out, one fading in)
ambient voice ───► ambient bus ─┼─► master ─► Discord
sfx voice     ─┐                │
sfx voice     ─┴─► sfx bus     ─┘
```

Because nothing about the FFmpeg invocation depends on volume or on what else is
playing, every control is a gain change on a live graph:

| Action | Effect on playback |
|---|---|
| Move any volume slider | 40 ms gain ramp; audio keeps flowing |
| Select an ambient bed | Fades in on its own bus, under the music |
| Fire an SFX | New voice on the SFX bus, up to 8 at once |
| Change track | Crossfade between two music voices |
| Change fade length | Applies to the *next* transition |
| Move a track's own fader | That voice only; independent of fades and of other tracks |
| Pause | Frames stop being pulled; position is held, nothing restarts |
| Toggle normalisation | Instant; the same decoders keep running |
| Toggle a track's loop | Takes effect at the end of the current pass; audio is not cut |
| Trim (dB) | A manual nudge on top of everything — the escape hatch when the target is right but the rig needs more |

The visualiser is driven by an FFT of the actual mixed output, and `!check`
reports the live voice counts.

### How the volume controls combine

Every gain in the chain multiplies:

```
track fader x music bus x master x normalisation = output
```

Two sliders at 50% is **-12 dB**, not -6 dB. With normalisation on, keep music
*and* master at 100% and set the level with the loudness target instead —
otherwise a fader silently moves you off the target you asked for. Use the faders
for quick ducking during a session. The panel prints the combined figure
under the faders (`music 50% x master 100% = -6.0 dB`) so this is never guesswork,
and the Mixer readout warns if the sum is clipping.

### Output: bot or music player

The **Output** picker at the top of the right-hand column switches between:

- **Discord bot** — streamed into the voice channel
- **This PC (MP3 player)** — straight out of your speakers, no bot involved

Everything else behaves identically in both: layers, faders, normalisation,
crossfades, loop. Local playback uses QtMultimedia, which ships with PyQt6, so
there's nothing extra to install.

Switching stops playback. A frame can only be consumed once, so the two outputs
can't share a mixer — handing a live stream over would mean duplicating every
frame into two buffers, and stopping is clearer.

The **Device** picker below it chooses which sound device local playback uses —
"System default" follows Windows, or name a specific one (handy for sending music
to a second output while you listen on a headset). The list refreshes when you
plug or unplug something, changing it applies mid-track without stopping, and a
saved device that has gone missing falls back to the default rather than failing.

Local playback needs no bot and no token: launch with `--ui-only`, pick
**This PC**, and it's a music player. The Mixer readout shows `local frames N`
climbing while the sound card is pulling audio, or `local: no frames pulled!` if
it isn't — the first thing to check if you get silence.

### Arranging the window

Every panel is a dock — Visualiser, Library, Playlist, Playing now, Controls.
Drag one out to float it, drop it on another to tab them together, or drag it to
any edge. **View** has toggles for each panel plus *Show all panels*, *Pop all
panels out*, *Tab panels together* and *Reset layout*.

There is also a **Reset UI** button in the toolbar, next to Customize — the same
thing as *Reset layout*, but reachable without navigating a menu in a window
you've just shuffled into a mess. It puts every panel back, makes them all
visible, and saves that state immediately. Themes, levels and your library are
untouched.

Panels deliberately have **no close button**. A closed dock leaves nothing on
screen to bring it back, so it looks permanently lost. Hiding is still available
from the View menu, which can also restore them, and *Show all panels* is the
one-click way back.

The arrangement and the window geometry are saved to `ui_state.json`, along with
the selected theme, so the app opens the way you left it. The layout carries a
version stamp: when the set of panels changes between releases, the old layout is
discarded rather than restored into a window it no longer describes. If every
panel somehow ends up hidden, startup restores them.

### Backgrounds

The theme editor takes a background image with two sliders: **Image** (how
strongly it shows) and **Darken** (a black veil over it, so text stays readable
on a busy photo). Qt stylesheets can display an image but can't fade one, so the
two are composited into a cached PNG in `.background-cache/` — recomputed when
you move a slider, reused when you just reopen the theme.

Drop images in `backgrounds/` and the picker opens there by default.

### Importing an existing collection

**Library → Import folder…** walks a folder tree and copies everything in, using
each subfolder name as the category and creating categories as needed — so an
old `music_files/` tree comes back exactly as it was.

**Library → Import an old music_data.json…** reads a previous install's library
file, keeping display names and any cached loudness measurements, so nothing
needs re-analysing.

Both are idempotent: importing the same source twice adds nothing the second
time.

### Playback modes

| Mode | Playing a track… |
|---|---|
| Single Track | replaces what's playing; repeats if Loop is on |
| Playlist | replaces, then advances to the next when it ends |
| Shuffle | as Playlist, in random order |
| **Multi-track (layer)** | **adds it alongside**, leaving everything else running |

Loop and the queue modes pull in opposite directions — a repeating track never
ends, so a playlist can't advance. Selecting Playlist or Shuffle therefore turns
Loop off for you; you can turn it back on for repeat-one behaviour.

### Layering

Right-click a track → **Add as layer** plays it *alongside* whatever is going,
rather than crossfading over it. Each playing voice gets a strip in the
**Playing now** panel with its own fader and a ✕ to stop it. Up to 6 music
layers; ambient and SFX are unaffected by the limit.

Each strip has **⏸** hold, **↻** loop, and **✕** stop. There are also global
**↻** toggles next to the transport controls (music) and in the Ambient tab. Looping is handled by
`LoopingStream` rather than FFmpeg's `-stream_loop`, which is why it can be
switched on or off while a track is playing: the next pass is spawned as soon as
the decoder reports EOF — seconds before playback needs it — so the repeat is
gapless, and turning loop off simply means the current pass isn't repeated.

`Playback mode = Single Track` still starts the primary track looping, as before.

Three gains multiply per voice, which is what keeps them independent:

```
envelope (fades, engine-owned) x trim (your fader) x norm (loudness) x bus x master
```

So fading a track out and back in returns it to *your* fader position, not to
full volume.

### Loudness normalisation

"Normalise all audio" measures each file once with FFmpeg's `loudnorm` analyser
and caches the result in `music_data.json`. Playback then applies a static gain
to bring every track to the target.

A note on the target: **peak** normalisation (e.g. "-6 dB") does not balance
anything — a dense track peaking at -6 dBFS is much louder than a sparse one at
the same peak. Perceived loudness is measured in LUFS, so that is what the
target is in. And because Discord applies no normalisation of its own, and your
players' *voices* are the reference the ear judges against, a music bed has to
sit well below speech level:

| Use | Target |
|---|---|
| Very quiet bed | -40 LUFS |
| Quiet bed, lots of talking | -30 LUFS |
| **Bed under conversation** | **-26 LUFS — the default** |
| Console game (GANG) | -24 LUFS |
| Broadcast (EBU R128) | -23 LUFS |
| Featured music, nobody talking | -18 LUFS |
| Streaming (Spotify/YouTube) | -14 LUFS |

Raising the target makes everything **louder**, since less attenuation is
applied. The range goes down to -60 LUFS; whatever you pick is saved to
`mixer_settings.json` along with the faders, so you set it once.

If the music level *changes when people speak*, that is not this app —
normalisation here is a static per-track gain. Check Discord's Attenuation
setting and the Windows Communications ducking option; both are covered in
`docs/LOUDNESS.md`, which also explains the standards and the "anchor element"
idea behind the targets.

**Normalisation only attenuates by default.** Turning it on can never make a
track louder than the raw file: a track hotter than the target is pulled down,
a quieter one is left alone. Tick "Also boost quiet tracks" to raise quiet
material too, by up to 6 dB. Boosting is what makes normalisation feel
unpredictable — a quiet file arriving 4x louder than the last one — so it is
opt-in.

The true-peak ceiling applies either way, so a track mastered to -0.2 dBTP is
nudged down under -1 dBTP. That headroom is what lets several layers sum without
clipping.

The panel has a preset picker and an editable target — type any value between
-40 and -3 LUFS and the picker switches to "Custom". The **peak ceiling**
(default -1 dBTP) is editable too. Both apply live: changing either re-derives
the gain on every playing voice without re-decoding anything.

True peak is measured too, and a boost is held back if it would push a track
past -1 dBTP, so normalisation can never introduce clipping. Gains are capped at
+12/-24 dB so a near-silent file isn't amplified into hiss; the debug log marks
any track that hits the cap. Use the **Analyse** button to measure the whole
library up front instead of on first play.

---

## Quick start

```bash
git clone https://github.com/<you>/dnd-music-manager
cd dnd-music-manager
python -m venv .venv && .venv\Scripts\activate     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then paste your bot token into it
python main.py
```

If there's no token anywhere, the app asks for one on first run and writes it
to `.env` for you.

### Command line

| Flag | Effect |
|---|---|
| `--ui-only` | Launch the window without connecting to Discord (UI work, no token needed) |
| `--dev` | Read the token from `.env` only, skip the auth server |
| `--data-dir PATH` | Store music/library/config somewhere other than the working directory |
| `--version` | Print the version and exit |

### External dependencies

**FFmpeg** must be on `PATH` — it does all decoding, looping and mixing.
**libopus** is needed for voice output; the app looks next to the executable,
inside disnake, in system library paths, and as a last resort downloads it on
Windows. The banner printed at startup tells you if either is missing.

---

## Building the .exe

**Publish a release on GitHub and the .exe builds itself.**

1. Releases → *Draft a new release*
2. Create a tag such as `v4.1.0`, write the notes, **Publish release**
3. `.github/workflows/build.yml` runs and, a few minutes later, attaches two
   files to that release:
   - `DnDMusicManager.exe` — the bare executable
   - `DnDMusicManager-windows.zip` — the exe plus README, `.env.example` and a
     short START-HERE.txt, which is the friendlier thing to hand a player

The build runs on `windows-latest`: installs the dependencies, stamps
`APP_VERSION` from the tag (so `--version` matches what people downloaded),
gathers the native dependencies into `vendor/`, runs PyInstaller, smoke-tests
the binary, then uploads.

Where the native pieces come from, and why:

| Dependency | Source |
|---|---|
| FFmpeg | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) `latest` tag — the usual source for Windows FFmpeg binaries, and a stable URL |
| libopus | **copied out of the installed disnake package**, which ships `libopus-0.x64.dll` — no download at all |

Every one of those steps fails the build if its file is missing. An .exe without
FFmpeg cannot decode anything and one without Opus is silent, so a build that
lost them is worse than no build.

If the upload step fails with *"Resource not accessible by integration"*, the
workflow lacks write access to the release. `build.yml` declares
`permissions: contents: write`, which covers it; if a repository is locked down
further, check **Settings → Actions → General → Workflow permissions**.

You can also trigger it from the **Actions** tab without cutting a release
(`workflow_dispatch`); it uploads a build artifact instead of attaching to a
release.

FFmpeg and Opus are bundled, so a machine with no Python, no FFmpeg and no Opus
can run the result. A frozen build stores its data next to the `.exe` rather than
in the working directory.

Locally:

```bash
pip install pyinstaller
python build.py              # -> dist/DnDMusicManager.exe
python build.py --console    # keeps a console window, so you can read the log
python build.py --dry-run    # print the PyInstaller command without building
```

`build.py` is what the workflow runs too, so a CI build and a desk build can't
drift apart. It bundles whatever is in `vendor/`, adds the hidden imports
PyInstaller can't infer (`PyQt6.QtMultimedia` for local playback, disnake's
submodules), and drops tkinter/PyQt5/PySide6 to keep the binary smaller.

Use `--console` when an .exe won't start: the startup banner and every debug
line go to stdout instead of vanishing.

---

## Project layout

```
main.py                     launcher (3 lines of logic)
src/dndmusic/
├── config.py               all paths and constants, resolved from one root
├── cli.py                  argument parsing
├── discord_api.py          the only place disnake is imported
├── _ssl_compat.py          Windows certificate-store workaround
├── services.py             composition root — builds the object graph
├── app.py                  entry point: services -> QApplication -> window
├── core/                   domain layer (no Qt, no disnake)
│   ├── models.py           MusicTrack, PlaybackMode, MediaKind
│   ├── categories.py       CategoryRegistry + persistence
│   ├── library.py          import / rename / move / delete / disk sync / save
│   ├── playlist.py         queue, cursor, playlist files
│   └── debug.py            rolling log
├── audio/                  the audio pipeline
│   ├── pcm.py              frame format, gain maths, FFT — the shared contract
│   ├── stream.py           FrameStream protocol + FFmpegPcmStream (decoders)
│   ├── mixer.py            MixingSource, Voice, GainRamp, buses (the mixer)
│   ├── ffmpeg.py           binary detection
│   └── opus.py             DLL discovery and download
├── engine/player.py        MusicEngine — decides which voices exist, and when
├── bot/                    Discord side
│   ├── auth.py             token resolution (.env, auth server)
│   ├── client.py           BotRunner (thread + event loop), BotContext
│   └── cogs/               voice.py, diagnostics.py
└── gui/                    Qt layer
    ├── main_window.py      wiring only — no domain logic
    ├── bridge.py           engine callbacks -> Qt signals (thread-safe)
    ├── theme/              models, presets, stylesheet, manager, editor
    ├── widgets/            top bar, visualiser, library/sfx/ambient, playlist, controls
    └── dialogs/            token setup, prompt helpers
tools/diagnose_ssl_store.py diagnostic for the cert-store failure
```

The audio pipeline reads left to right: `stream.py` **produces** frames,
`mixer.py` **combines** them, `engine/player.py` **decides** what exists. A new
kind of audio source is a new class in `stream.py` and nothing else.

`docs/LOUDNESS.md` explains the loudness standards and how the target should be
chosen. Read `docs/ARCHITECTURE.md` before adding features — it covers the dependency
rules, the threading model, and where each kind of change belongs.

---

## File headers

Every file starts with a comment naming its own path:

```python
# src/dndmusic/audio/mixer.py
"""The mixer: one audio source, many voices."""
```

So a file taken out of context can always be put back where it belongs. Markdown
uses an HTML comment, YAML and Python a `#`.

## Troubleshooting the bot

### "PyNaCl library needed in order to use voice"

disnake encrypts the voice stream with PyNaCl and imports it lazily, so a
missing PyNaCl only shows up when someone runs `!join` — the bot otherwise looks
perfectly healthy.

Since the packaged app runs windowed and has no console, two things now make
this visible without one:

- **A red "Missing:" panel** at the top of Bot Status naming what is absent.
- **A log file** at `logs/session-<date>.log` beside the app, with local paths
  redacted, so it is safe to send to whoever built it. The last 10 sessions are
  kept.

If PyNaCl is reported missing:

- **running from source:** `pip install -r requirements.txt` (PyNaCl is listed
  explicitly, so this cannot silently skip it)
- **running the .exe:** it was built without PyNaCl bundled. `build.py` passes
  `--collect-all nacl`, which includes the compiled `_sodium` extension as well
  as the Python modules — so make sure the .exe came from a release built
  *after* that change, not an earlier one.

### Opus: a library, not a program

Opus works differently from FFmpeg and it is worth knowing which you are
debugging. FFmpeg is a **program** this app runs as a subprocess, found via
`PATH`. Opus is a **library** that disnake loads into the process with ctypes —
no PATH, no subprocess, just a specific file handed to `load_opus()`. Without it
disnake refuses to open a voice connection and the bot is silent.

It is normally a non-issue, because **disnake ships libopus itself**
(`disnake/bin/libopus-0.x64.dll`). The search order is:

1. an explicitly configured path (see below)
2. disnake's own bundled copy — the usual answer
3. `libopus-0.dll` beside the .exe, in `vendor/`, or in the working directory
4. system library names, then ctypes' library finder

If all of that fails, a **Locate libopus-0.dll…** button appears next to the
FFmpeg one. Because Opus is loaded rather than executed, choosing a file takes
effect immediately — disnake only needs it before a voice connection, not before
startup.

There is deliberately **no automatic download**. An earlier version tried to
fetch a DLL from the xiph GitHub releases; those contain source only, so the URL
404s and the "recovery" never worked. Downloading a library and loading it is
also code execution with nothing to verify it against.

### FFmpeg: bundled, discovered, or chosen by hand

Three layers, so a missing FFmpeg is recoverable without a reinstall:

1. **Bundled.** The release .exe carries `ffmpeg.exe`, and the bundle directory
   is prepended to `PATH` at startup so it is found.
2. **Discovered.** If that fails, startup scans `PATH` and the usual install
   locations (`C:\ffmpeg\bin`, winget's shim, the working directory) and saves
   whatever it finds.
3. **Chosen.** If both fail, a **Locate ffmpeg.exe…** button appears under the
   warning in Bot Status. Pick the binary and it is validated (it must answer to
   `-version`) before being saved to `mixer_settings.json`.

So "just install FFmpeg and point at it" is a valid fallback rather than the
only option. Every part of the app that shells out — playback, loudness
measurement — goes through one `executable()` function, so the setting applies
everywhere.

### "FFmpeg: MISSING" in a packaged build

Two causes, and the log tells them apart. If Opus and PyNaCl are missing too,
the build simply didn't include them — check the Actions log for the
*Fetch native dependencies* step (it now fails the build rather than shipping a
broken .exe) and for `--collect-all nacl` in the build command.

If only FFmpeg is missing, it was bundled but not findable: `--add-binary`
extracts to a temp folder that is not on `PATH`. `add_bundle_to_path()` prepends
it at startup, so a build after that fix finds its own copy.

### Diagnosing someone else's copy

Ask for `logs/session-*.log` from beside their .exe. The first few lines list
FFmpeg, disnake, Opus and PyNaCl, which settles most "it doesn't work" reports
immediately. For anything deeper, `python build.py --console` produces a build
that keeps a console window open.

## Security

Your token is never in source, `.env` is git-ignored and not in the release
archive, FFmpeg is never invoked through a shell, and `!debug` is limited to the
bot owner or a server manager. `docs/SECURITY.md` covers the full review,
including the two things that are opt-in on purpose.

## Verifying a checkout

If you copied files in by hand, check the tree before debugging anything:

```bash
python tools/verify_layout.py             # report
python tools/verify_layout.py --fix       # also repair trailing newlines
python tools/verify_layout.py --generate  # make the current tree the new baseline
```

It reports missing files, files that are an older version, and files deleted
upstream that are still sitting in your copy — all three of which otherwise
surface as confusing import errors. Line endings are ignored, and your music,
playlists and `.env` are not inspected.

The baseline is `tools/manifest.txt`, plain text with a declared file count so a
truncated or empty copy is detected rather than silently checking half the tree.
Run `--generate` once you start making your own changes, so your edits become the
baseline instead of being reported as stale forever.

If a lot of files are reported as "nearly identical; whitespace or a hand edit",
one line short, they are probably just missing the path header:

```bash
python tools/add_path_headers.py --dry-run   # check
python tools/add_path_headers.py             # add them in place
```

That is faster than re-copying 50 files for a one-line comment.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

25 tests covering the playlist state machine, the library round-trip, the
category registry, the FFmpeg option builder and the stylesheet generator.
None of them need a display, a token or a voice connection — that's the payoff
from keeping `core/` and `audio/` free of Qt and disnake. CI runs them on every
push (`.github/workflows/ci.yml`).

---

## Troubleshooting

### `ssl.SSLError: [ASN1: NOT_ENOUGH_DATA]` on startup

The traceback ends in `ssl.py -> _load_windows_store_certs` while importing
disnake. Nothing to do with this app's code: aiohttp builds a default SSL
context at import time, Python hands the whole Windows certificate store to
OpenSSL as one blob, and OpenSSL rejects the batch.

Two different faults look identical from the traceback, so diagnose before
touching anything:

```bash
python tools/diagnose_ssl_store.py
```

**If a handful of certificates are reported as truncated**, they are genuinely
damaged — delete them in `certlm.msc` (Local Machine) or `certmgr.msc` (Current
User), matching the subject and serial the script prints.

**If every certificate is rejected but all are structurally complete**, your
OpenSSL install is broken and the certificates are innocent. The usual cause is
a Python built against one OpenSSL running against another — a conda env after
an `openssl` upgrade, or a stray `libcrypto-3-x64.dll` earlier on `PATH`.
Rebuild the environment instead:

```bash
conda create -n dnd-music python=3.12 -y
conda activate dnd-music
pip install -r requirements.txt
```

Python 3.9 with OpenSSL 3.5 is a known-bad pairing of this kind. A clean
python.org 3.12 + `venv` is better still if you intend to build the .exe, since
it matches what the GitHub Actions runner uses.

`src/dndmusic/_ssl_compat.py` softens both cases at runtime: when the stock path
fails it loads certificates individually, skipping only the ones OpenSSL
rejects, and falls back to the certifi bundle if the store yields nothing.
That gets the app running, but it is a bandage — a broken OpenSSL will still
bite you in pip, requests and anything else. Set `DND_SKIP_SSL_WORKAROUND=1` to
disable it.

---

## Notes on the refactor

### Audio engine rewrite

The original design baked every parameter into an FFmpeg command line — volume
as `-af volume=`, ambient as `-filter_complex`, looping as `-stream_loop` — so
changing any of them meant a new FFmpeg process and a new `voice_client.play()`,
which restarted the track. A voice client also holds only one source, so SFX
had to stop the music. Both problems are gone: FFmpeg now only decodes, and all
mixing happens in Python.

Removed along the way: the real-time/pre-compile mix mode and the Compile
button. Both existed only to avoid respawning FFmpeg, which no longer happens.
`temp_mixes/` is no longer used.

### Earlier fixes

Behaviour is otherwise unchanged, with these exceptions that were bugs:

1. **Tree lookups no longer match on display names.** Each item carries its
   `MusicTrack` object, so two tracks with the same name in one category can't
   shadow each other.
2. **Auto-advance no longer touches widgets from the bot thread.** The engine
   reports through callbacks that the GUI bridge turns into queued Qt signals.
   The old `_auto_next` called `setCurrentRow` from the audio callback thread,
   which is undefined behaviour in Qt and a plausible source of random crashes.
3. **`music_data.json` is written atomically** (temp file + replace), so a crash
   mid-save can't leave a truncated library.
4. **Paths resolve from one root.** Previously every path was relative to the
   working directory, which breaks when the .exe is launched from a shortcut.
5. **The library follows the filesystem.** Files copied into `music_files/` by
   hand are picked up on startup, on a 600 ms-debounced filesystem watch, and
   via the Rescan button; entries whose file has been deleted are dropped, which
   is what caused the "this music does not exist" errors.

Still open: `!join` is the only way to get the bot into a channel, seeking within
a track isn't exposed, and per-track gain trim would be a natural next addition
now that the mixer supports it.
