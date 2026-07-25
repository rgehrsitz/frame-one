# Frame One

**A calm, local-first e-paper status plate for a developer's desk.**

Frame One turns a Raspberry Pi Zero 2 W and a 7.5-inch Waveshare e-paper panel into a long, low dashboard for weather, AI allowance, Gmail unread count, and one daily quote. It is designed for slow, deliberate updates—not a constantly moving screen.

> **Early prototype:** the deterministic 800 × 480 renderer and Quote of the Day adapter work today. Hardware enclosure, display driving, and the weather/Gmail/Codex/Claude adapters are in active development.

## What it will show

- Current conditions and a Today / Tonight / Tomorrow forecast
- Claude five-hour and weekly allowance (manual bridge until a supported API exists)
- Codex rate-limit windows through the documented local App Server
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
| Enclosure | A custom, A1-mini-printable desk enclosure (in development) |

The case will be designed as smaller printable modules that assemble into the low, horizontal desktop form.

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

### Live Quote of the Day

Add `--live-quote` to fetch a fresh daily quote from ZenQuotes into memory for that render:

```sh
PYTHONPATH=src python3 -m frame_one.cli \
  --input samples/dashboard-state.json \
  --output output/dashboard.png \
  --live-quote
```

There is deliberately no quote cache, bundled quote list, fallback, or sidecar JSON. A failed or unsuitable quote stops the render before the existing output image is replaced. ZenQuotes attribution belongs in the eventual local setup/about page.

## Verify

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Privacy principles

- The Pi fetches only values necessary for the screen.
- Gmail uses read-only label metadata; no messages, senders, subjects, or bodies are displayed or logged.
- Claude and Codex are never scraped. Each uses only a supported integration or a deliberate manual bridge.
- Credentials stay on the Pi and are never committed. `.gitignore` excludes local secrets and generated dashboard output.

## Attribution

- Weather data: [Open-Meteo](https://open-meteo.com/)
- Daily quote provider: [ZenQuotes](https://zenquotes.io/)
- E-paper hardware: [Waveshare](https://www.waveshare.com/)

## License

[MIT](LICENSE) © 2026 Robert Gehrsitz. Third-party services, fonts, hardware designs, and logos retain their own licenses and terms.
