# Frame One

**A calm, local-first e-paper status plate for a developer's desk.**

Frame One turns a Raspberry Pi Zero 2 W and a 7.5-inch Waveshare e-paper panel into a long, low dashboard for weather, AI allowance, Gmail unread count, and one daily quote. It is designed for slow, deliberate updates—not a constantly moving screen.

> **Early prototype:** the deterministic renderer, weather, quote, automatic Claude Code allowance capture, Codex, Gmail unread adapters, refresh service, and first parametric desk enclosure are ready. Gmail and Codex each require one explicit local sign-in before their first live use; the enclosure still needs a physical fit check against the exact panel and cable stack.

## What it will show

- Current conditions and a Today / Tonight / Tomorrow forecast
- Claude five-hour and weekly allowance, read on-device so the panel stays standalone
- Codex rate-limit windows through the local App Server
- Gmail unread count only—never subjects or message content
- One live Quote of the Day

See [DESIGN.md](DESIGN.md) for the exact screen system and [DATA_SOURCES.md](DATA_SOURCES.md) for provider, privacy, and refresh decisions.

## Planned hardware

| Part | Choice |
| --- | --- |
| Compute | Raspberry Pi Zero 2 W |
| Display | Waveshare 7.5-inch, 800 × 480 black-and-white e-paper HAT |
| Power | 5 V USB power supply |
| Storage | microSD card |
| Enclosure | A custom, A1-mini-printable white desk frame with a recessed display and plinth |

The case is an A1-mini-printable modular desk frame: the broad face splits at
the frame corners so no seam crosses the screen. Its parametric OpenSCAD source
and assembly notes live in
[`enclosure/`](enclosure/README.md); it needs one small fit print before the
full case, because Waveshare listings include more than one physical panel
assembly.

## Try the renderer

Requires Python 3.11+ and Pillow.

```sh
python3 -m pip install -e .
frame-one \
  --input samples/dashboard-state.json \
  --output output/dashboard.png
```

Or, without installing the package:

```sh
PYTHONPATH=src python3 -m frame_one.cli \
  --input samples/dashboard-state.json \
  --output output/dashboard.png
```

The result is a strict 1-bit 800 × 480 PNG suitable for the target panel.

Frame One bundles Barlow Condensed SemiBold, IBM Plex Mono Medium, and IBM Plex
Serif Italic so the dashboard looks the same on the Pi and on a development
computer. Their license files live in `src/frame_one/assets/fonts/`. Set
`FRAME_ONE_DISPLAY_FONT`, `FRAME_ONE_MONO_FONT`, or `FRAME_ONE_SERIF_FONT` only
to intentionally override those defaults.

### Show it on the Waveshare panel

Frame One supports the monochrome 800 × 480 Waveshare 7.5-inch V2 panel through
Waveshare's official `epd7in5_V2` library. First follow Waveshare's demo setup
and confirm that their test image works. The driver uses Raspberry Pi OS's
`spidev`, `gpiozero`, and `lgpio` modules. If Frame One has its own virtual
environment, create it with access to those system packages:

```sh
python3 -m venv --system-site-packages ~/frame-one/.venv
```

Then install Frame One in that environment and send the sample screen:

```sh
source ~/frame-one/.venv/bin/activate
python -m pip install -e ~/frame-one

frame-one \
  --input ~/frame-one/samples/dashboard-state.json \
  --output ~/frame-one/output/dashboard.png \
  --display waveshare-7in5-v2
```

The display adapter performs one full, clean refresh and then puts the panel to
sleep. It loads the official driver from
`~/waveshare-e-paper/RaspberryPi_JetsonNano/python/lib` by default. Set
`FRAME_ONE_WAVESHARE_LIB` if you cloned it elsewhere.

### Live Quote of the Day

Add `--live-quote` to fetch a fresh daily quote from ZenQuotes into memory for that render:

```sh
PYTHONPATH=src python3 -m frame_one.cli \
  --input samples/dashboard-state.json \
  --output output/dashboard.png \
  --live-quote
```

There is deliberately no quote cache, bundled quote list, fallback, or sidecar JSON. A failed or unsuitable quote leaves the quote area quiet while the rest of the screen still refreshes. ZenQuotes attribution belongs in the eventual local setup/about page.

### Automatic Pi refresh

The supplied systemd units make the Pi self-starting: weather, Claude, Codex,
and Gmail refresh every five minutes, while a separate run at 2:00 AM local
time also fetches the daily quote. Both use the same lock, so the e-paper panel
is never driven by two refreshes at once. The system timer is persistent, so a
missed run is made up once after a reboot when the network becomes available.

Set the location as explicit coordinates—never a street address—in the local,
owner-readable configuration file:

```sh
install -d -m 700 ~/.config/frame-one
install -m 600 deploy/systemd/dashboard.env.example ~/.config/frame-one/dashboard.env
# Edit WEATHER_LATITUDE, WEATHER_LONGITUDE, and WEATHER_TIMEZONE as needed.
```

Install and enable the boot-persistent units:

```sh
sudo install -m 644 deploy/systemd/frame-one-refresh.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/frame-one-refresh.timer /etc/systemd/system/
sudo install -m 644 deploy/systemd/frame-one-quote.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/frame-one-quote.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frame-one-refresh.timer frame-one-quote.timer
systemctl list-timers 'frame-one-*'
```

The five-minute timer starts about 30 seconds after boot, then continues on
five-minute wall-clock boundaries.

### Live weather

Open-Meteo needs no account or key for this personal dashboard. Provide an
explicit latitude and longitude—the software does not infer your location—and
it will replace the sample weather data for that render. A failed request falls
back to the last good forecast, then to `—`; it never blocks the other tiles.

```sh
frame-one \
  --input ~/frame-one/samples/dashboard-state.json \
  --output ~/frame-one/output/dashboard.png \
  --live-weather \
  --weather-latitude 40.0000 \
  --weather-longitude -75.0000 \
  --weather-timezone America/New_York \
  --display waveshare-7in5-v2
```

### Claude allowance — standalone (recommended)

The Pi reads your five-hour and weekly allowance directly, with no second
machine involved. Authorize it once:

```sh
frame-one-claude-login
```

It prints a URL. Open it in a browser on any machine, approve, then paste the
address bar back — the page will fail to load, which is expected; the code is
in the URL. The credential is written to `~/.config/frame-one/claude-oauth.json`
with `0600` permissions and refreshes itself from then on.

Refresh tokens do eventually expire outright. When that happens the Claude tile
reports `not authorized yet; run frame-one-claude-login` and shows `—`; re-run
the login command. That is a re-authorization, not a fault.

```sh
frame-one --input ~/frame-one/samples/dashboard-state.json \
  --output ~/frame-one/output/dashboard.png \
  --claude-oauth-credentials ~/.config/frame-one/claude-oauth.json
```

Two things to know before choosing this. The usage endpoint is **not part of
Anthropic's published API**, so it may change without notice — the provider
validates every field and shows `—` rather than guessing when it does. And the
credential carries the `user:inference` scope, meaning a token on this device
could in principle spend allowance, not only read it. Treat the Pi accordingly,
and revoke the credential by deleting the file if the device leaves your hands.

### Claude allowance via Claude Code (no extra credential)

Frame One uses Claude Code's documented **status-line** `rate_limits` object.
After an ordinary Claude Code response, it provides the five-hour and seven-day
usage percentages plus their exact reset timestamps. The collector preserves
only those four values—never a prompt, transcript, repository name, account
identifier, or credential.

This alternative needs no extra credential, but it only produces data in
**rendered interactive terminal sessions** — the Claude Code desktop app and
`claude -p` never invoke a status line, so neither produces a snapshot. It also
reports nothing while you are not actively working, and nothing at all about
usage from claude.ai. It requires the machine running Claude Code to reach the
Pi, so the panel is no longer standalone.

Install this repository on the machine where you run terminal `claude`, then add
the command below as Claude Code's `statusLine.command`. If you already use a
custom status line, call this collector from that wrapper rather than replacing
your existing command.

```sh
python3 -m pip install -e ~/frame-one
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "frame-one-claude-statusline --output ~/.config/frame-one/claude-status.json --timezone America/New_York --sync-to YOUR_PI_USER@frame-one.local:~/.config/frame-one/claude-status.json --identity-file ~/.ssh/frame-one-pi"
  }
}
```

The optional `--sync-to` copies the tiny snapshot to the Pi only after a
successful Claude response and no more than once every 15 minutes. It needs a
one-time, passwordless SSH key setup; it never copies the Claude credential.
Then the Pi's normal render command reads the automatically generated file:

```sh
frame-one --input ~/frame-one/samples/dashboard-state.json \
  --output ~/frame-one/output/dashboard.png \
  --claude-status-file ~/.config/frame-one/claude-status.json
```

Codex is read from the local App Server rather than from browser
cookies, the desktop app, or token files. Once Codex CLI is installed and
signed in on the Pi, add `--live-codex` to a normal render command.

Gmail reads only `threadsUnread` from the `INBOX` label—the conversation count
shown by the Gmail interface, without inflating the badge when one thread has
multiple unread messages. First create a Google
Cloud project, enable the Gmail API, configure its OAuth consent screen, and
create a **Desktop** OAuth client. Download its JSON on the Pi to an ignored,
owner-readable path such as `~/.config/frame-one/google-client.json`. The
consent screen needs the restricted `gmail.readonly` scope; in Google testing
mode, add the mailbox owner as a test user.

Then, from a Mac terminal, create a temporary loopback tunnel:

```sh
ssh -N -L 8765:127.0.0.1:8765 rgehrsitz@frame-one.local
```

On the Pi, start the authorization command and open the printed URL in the Mac
browser:

```sh
frame-one-gmail-login \
  --client-secrets ~/.config/frame-one/google-client.json
```

It writes `~/.config/frame-one/gmail.token.json` with `0600` permissions. That
file is ignored by Git and contains the refreshable credential; Frame One uses
it only for INBOX label metadata and never asks for Gmail messages, senders,
subjects, or bodies. Add it to a normal render command with
`--gmail-token ~/.config/frame-one/gmail.token.json`.

## Verify

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Privacy principles

- The Pi fetches only values necessary for the screen.
- Gmail uses read-only label metadata; no messages, senders, subjects, or bodies are displayed or logged.
- Claude and Codex allowances are read as allowance figures only — percentages and reset times, never conversations, prompts, or project data.
- Reading a meter through an undocumented vendor interface is allowed when it is the only thing that works; such providers fail to `—` rather than guess.
- Credentials stay on their local source device and are never committed. `.gitignore` excludes local secrets and generated dashboard output.

## Attribution

- Weather data: [Open-Meteo](https://open-meteo.com/)
- Daily quote provider: [ZenQuotes](https://zenquotes.io/)
- E-paper hardware: [Waveshare](https://www.waveshare.com/)

## License

[MIT](LICENSE) © 2026 Robert Gehrsitz. Third-party services, fonts, hardware designs, and logos retain their own licenses and terms.
