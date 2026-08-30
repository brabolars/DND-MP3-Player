<!-- docs/LOUDNESS.md -->
# How audio engines balance loudness, and against what

## The measurement

Everything below rests on one algorithm: **ITU-R BS.1770**, which defines how to
turn a waveform into a single perceptual loudness number. Three parts matter:

- **K-weighting** — a filter that boosts midrange/treble by roughly +4 dB above
  2 kHz and rolls off deep bass, approximating human sensitivity. This is why a
  bass-heavy track and a bright track with the same peak level measure
  differently, and why a pure sine measures much lower than you'd expect.
- **Gating** — an absolute gate at -70 LUFS and a relative gate 10 LU below the
  ungated average, so silence and quiet passages don't drag the number down. A
  track with long silences would otherwise be normalised far too loud.
- **True peak (dBTP)** — computed with oversampling, so it catches inter-sample
  peaks that a naive sample-peak reading misses.

The unit is **LUFS** (Loudness Units Full Scale). ITU calls it LKFS. They are
the same thing, and 1 LU = 1 dB.

## The reference targets

| Target | Standard / platform |
|---|---|
| -24 LKFS | ATSC A/85 (US broadcast, CALM Act) |
| -23 LUFS | EBU R128 (European broadcast), true peak ≤ -1 dBTP, ±1 LU tolerance |
| -24 LUFS | console games — recommended via the Game Audio Network Guild |
| -16 LUFS | portable games; also Apple podcasts |
| -14 LUFS | Spotify, YouTube, Amazon |
| -9 LUFS and up | loudness-war mastering |

Before R128, normalisation was based on **peak** level, which is what caused the
loudness war: compress everything flat, and your peak-normalised track sounds
louder than the competition. Loudness normalisation removes the incentive
entirely — over-compression just gets turned down. This is exactly why "normalise
to -6 dB" is not a thing: -6 dBFS is a peak target, and two tracks at the same
peak can differ by 15 dB in perceived loudness.

## The anchor element — the part that matters here

Broadcast and game mixes are balanced around an **anchor element**: the thing a
listener judges the volume by, which is almost always dialogue. Everything else
is placed relative to that anchor, not to the target number.

ATSC A/85 normalises the anchor rather than the whole programme, for a concrete
reason: an action film with loud explosions and quiet dialogue measures the same
integrated loudness as a dialogue-only sitcom, but its speech is much quieter, so
viewers turn it up and then get flattened by the next explosion.

Game audio hits the same wall. A soundtrack mastered as an album is as loud as it
can be without clipping — correct for listening to the album, wrong in-game,
because every sound effect has to fit *on top of it*. That is why in-game music
is mixed quieter than its own OST release.

## What this means for a Discord bot

**Discord applies no loudness normalisation of its own.** There is no per-user
levelling in the client, which is a long-standing feature request. So whatever
this app outputs lands directly against the raw mic levels of everyone in the
channel.

The consequence: **the music is not the anchor — your players' voices are.** A
music bed must sit *below* speech, so it cannot be targeted at a speech-level
number like -16 LUFS. That is why the default here is **-26 LUFS**:

| Use | Target |
|---|---|
| Quiet bed, lots of talking | -30 LUFS |
| **Under conversation (default)** | **-24 LUFS** |
| Featured music, nobody talking | -18 LUFS |
| Streaming-style, music is the point | -14 LUFS |

The default is -24 for a specific reason. Discord runs **AGC on microphone
input**, so every human in the channel arrives auto-levelled at roughly -18
LUFS. A bot has no microphone and bypasses AGC entirely, arriving at exactly
what we send — so this app has to be its own AGC. -24 puts music a few dB under
levelled speech, and it is where the standards independently landed: ATSC A/85
is -24 LKFS, EBU R128 -23, console games -24.

Once the target is this low, **turning "Also boost quiet tracks" on is worth
it**: everything loud is being attenuated anyway, there is ample peak headroom,
and the +6 dB cap is rarely reached by real music. Without it, an unusually quiet
file simply stays quiet instead of matching the rest.

Raising the target number makes everything **louder**, because less attenuation
is applied. If it's too loud, go more negative.

## "It gets quieter when people talk"

Nothing in this app does that. Normalisation here is a **static gain per track**,
computed once from the file's measured loudness — it cannot react to speech. If
the music level moves when someone talks, the ducking is happening outside the
app, and there are two usual culprits:

1. **Discord → Settings → Voice & Video → Attenuation.** This lowers other audio
   when you or others speak. Set the slider to 0%, and untick "When others
   speak" / "When I speak".
2. **Windows → Sound Control Panel → Communications tab.** "Reduce the volume of
   other sounds by 80%" is the Windows default. Set it to **Do nothing**.

Either of those will make music duck under speech automatically, which feels
like broken normalisation but is a separate feature entirely — and worth turning
off here, since this app already puts the music below speech by design.

## Why attenuation is not capped, but boosting is

Normalisation gain is limited to +6 dB up and 60 dB down, deliberately
asymmetric. Boosting raises the noise floor along with the signal, so a
near-silent file amplified 20 dB is hiss. Attenuation has no such cost.

An earlier version capped cuts at 24 dB and it broke matching at low targets: at
a -40 LUFS target a loud master needs -32 dB, hit the cap at -24, and landed 8 dB
above everything else — so tracks were *not* matched, which is the whole point of
normalising. If a cut limit is ever reachable by real material, it is too tight.

## Idle hiss, and why the bot stops transmitting

A single persistent mixer is what makes live volume changes possible, but taken
naively it means the bot encodes and sends 50 Opus packets a second forever,
even with nothing playing. That has two audible costs: the bot is permanently
marked "speaking", and constant-bitrate Opus on digital silence is where a faint
idle hiss comes from.

So the mixer is created **on demand** and torn down after 3 seconds of true
silence (`IDLE_SUSPEND_SECONDS`). Joining a channel transmits nothing at all;
queueing anything starts the mixer transparently. Nothing is playing when the
suspend fires, so there is no state to lose — and crucially, it can only fire
when the mixer is empty, so it never interferes with a volume change or a
crossfade.

## Faders break the target — put music at 100%

The target is an **absolute** level; the faders are trims that move you away from
it. They all multiply:

```
file loudness + normalisation + music fader + master = output
```

So with a target of -26 LUFS and the music fader at 50%, the output is -32 LUFS,
not -26. Speech in a voice call sits around -20 LUFS, so that is roughly 12 dB
*under* the conversation — playing, but effectively inaudible.

**Recommended setup:** music and master at 100%, and set the level with the
target alone. Then the number in the panel means what it says, and the faders are
free for quick ducking during a session.

The debug log prints the whole chain whenever a track starts:

```
[GAIN] file -6.5 LUFS  norm -19.5  music -6.0  master +0.0  = -25.5 dB  =>  about -32.0 LUFS out
```

If music is too loud or too quiet, that line answers why — no guessing.

## Calibration, and why you should trust your ears over the meter

Standards give you *consistency*, not correctness. Every mixing guide converges
on the same advice: set your playback volume to something comfortable using
reference material you trust, then mix to that — the meter is for checking, not
deciding.

For this app that means: get your Discord output volume and headphones to a
comfortable level with your players *talking*, then adjust the loudness target
until music sits underneath them. Once it's right, it stays right for every
track in the library, which is the actual payoff of normalising.

## Sources

- ITU-R BS.1770 — measurement algorithm (K-weighting, gating, true peak)
- EBU R128 — -23 LUFS, -1 dBTP, Loudness Range; EBU Tech 3341/3343 for metering
- ATSC A/85 — -24 LKFS, anchor-element normalisation
- Game Audio Network Guild recommendations for console and portable titles
