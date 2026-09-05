<!-- docs/PLAYER-GUIDE.md -->
# D&D Music Manager — the short version

For anyone who just wants to run it. No Python, no installing anything.

## Getting it going

1. Download **DnDMusicManager-windows.zip** from the
   [latest Release](../../releases/latest) and extract it somewhere you'll find
   again — the app keeps your music and settings in the same folder.
2. Run **DnDMusicManager.exe**. Windows may warn about an unrecognised app; it's
   unsigned, so that's expected — "More info" → "Run anyway".
3. It asks for a Discord bot token on first run.
   - **Running the bot?** Paste the token you were given. It's saved locally and
     never sent anywhere else.
   - **Just want a music player?** Close the prompt, set **Output** to
     *This PC*, and you're done. No token needed.

## Adding music

Drop audio files into `music_files\<Category>\` beside the .exe — for example
`music_files\Battle\`. The app notices within a second; **Rescan** in the Library
menu forces it.

Got a big collection already? **Library → Import folder…** copies a whole tree
in and uses the folder names as categories.

## Playing it

Double-click a track. Modes in the Playlist panel:

| Mode | What it does |
|---|---|
| Single Track | one track, repeats if **↻** is on |
| Playlist | works through the queue |
| Shuffle | queue in random order |
| Multi-track | **stacks** tracks — a battle theme over a rain loop |

Right-click a track → **Add as layer** to stack it on whatever is playing.
Everything currently playing appears in **Playing now**, each with its own
fader, **Hold**, **Loop** and **Stop**.

## Volume — read this bit

The app aims every track at the same loudness (**-24 LUFS**), so nothing is
suddenly ear-splitting. Two consequences:

- **Leave the Music and Master faders at 100%.** They multiply, so turning them
  down moves you off the target and makes everything inconsistent again.
- **Too loud or quiet for *you*?** Right-click the bot in Discord's voice
  channel list and use **that** volume slider. It only changes what you hear.
  Changing it in the app changes it for everyone.

If it's wrong for *everybody*, that's the **Target** in the Loudness panel.
Lower is quieter. -24 sits under conversation; -30 is a quiet bed.

## If something doesn't work

A red **Missing:** panel at the top of Bot Status names anything absent, with a
button to fix it:

- **FFmpeg missing** — a copy ships with the app, so this shouldn't happen. If
  it does, install FFmpeg and click **Locate ffmpeg.exe…**.
- **Opus missing** — click **Locate libopus-0.dll…**, or report it.
- **PyNaCl missing** — nothing you can fix; the download was built wrong. Report
  it and grab a newer release.

Either way, there's a log beside the .exe at `logs\session-<date>.log`. Send the
newest one — it lists exactly what's missing, with your folder paths blanked out.

## Where your stuff lives

Everything sits next to the .exe: `music_files\`, `playlists\`,
`mixer_settings.json`, `logs\`. Back the folder up like any document. Deleting
`mixer_settings.json` resets levels to the defaults.
