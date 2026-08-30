<!-- docs/SECURITY.md -->
# Security notes

What this app touches, what was reviewed before publishing, and what to watch.

## Your bot token

- Read from the `DISCORD_TOKEN` environment variable, or a `.env` beside the app.
- **Never** appears in source; the only literals are `your-bot-token-here` in
  `.env.example` and the `MTQxMjM2...` placeholder in the setup dialog.
- `.env` is git-ignored and is not in the release archive.
- It is stored in **plain text**, which is normal for a local desktop app but
  means the token travels with the folder. Don't zip your working directory to
  share with a player — hand them the built `.exe`, which prompts for its own.
- It is never written to the debug log.

## What a Discord user can do

Four commands, and none of them read or play arbitrary files — playback is
driven entirely from the desktop UI, so there is no remote file access.

| Command | Who |
|---|---|
| `!join` / `!leave` | anyone in the voice channel |
| `!check` | anyone (shows bot name, server count, active channels) |
| `!debug` | **bot owner or a member with Manage Server only** |

`!debug` DMs the diagnostic log, which names tracks, folders and servers. It was
originally open to anyone; it is now restricted, and the log has local paths
replaced with `<data>` and `<home>` so it cannot leak a Windows username or
directory layout.

## Command execution

FFmpeg is invoked with an **argument list, never a shell string** (`shell=True`
appears nowhere). A filename containing quotes or semicolons is passed as a
single argv entry and cannot become shell syntax — there is a test for exactly
that.

No `eval`, `exec`, `pickle` or `yaml.load` anywhere; all persistence is JSON.

## Filesystem

Category names become directory names, so they are sanitised: path separators,
Windows-illegal characters and leading dots are stripped, and the result is
capped at 64 characters. Both typed names and names loaded from
`custom_categories.json` go through it, so a hand-edited file can't escape the
data root either.

Imported files are copied under their basename only, so a crafted filename
cannot traverse out of the library.

## Network

| What | When | Notes |
|---|---|---|
| Discord API | always | via disnake, HTTPS |
| Opus DLL download | **opt-in only** | see below |
| Auth server | only if `AUTH_SERVER_URL` is set | posts a hashed machine fingerprint and `APP_SECRET` |

The Opus download fetches a DLL and loads it, which is code execution. There is
no signature to verify it against, so it is **off by default** — set
`DND_ALLOW_OPUS_DOWNLOAD=1` to enable. It is rarely needed: disnake ships libopus
in its own package, which is where it is normally found. When enabled it refuses
non-HTTPS URLs and checks the file is actually a DLL before loading it.

The same reasoning applies to `build.yml`, which downloads FFmpeg and Opus while
building the release binary. If you publish that `.exe` for others, you are
vouching for those downloads.

## The SSL workaround

`_ssl_compat.py` sounds alarming but **does not weaken verification**. When
Python cannot load the Windows certificate store as one blob, it loads the
certificates individually and skips only the ones OpenSSL rejects, falling back
to the certifi bundle if none load. Certificate validation stays on throughout.

## Not addressed

- `!join` has no permission check, so anyone in the server can move the bot
  between voice channels. Add a `@commands.has_permissions(...)` check if that
  matters for your server.
- No rate limiting on commands.
- The library and settings files are trusted; someone with write access to your
  data folder already has write access to your machine.