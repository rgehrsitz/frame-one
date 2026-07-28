# Frame One — Display Design

## Intent

Frame One is a **slow, calm developer weather station**: in two seconds, it answers how the day looks, how much AI capacity remains, and whether email needs attention. It is deliberately an e-paper status plate, not a constantly changing dashboard.

The memorable impression is *a beautifully printed instrument panel for a developer's day*.

## Screen system

The Waveshare panel is 800 × 480 pixels, black and white. The product design therefore uses only solid black ink and white paper; no grayscale, color coding, progress rings, shadows, or charts. Information hierarchy comes from scale, alignment, and rules.

| Region | Pixels | Purpose |
| --- | --- | --- |
| Header | `y: 0–92` | Date, last-updated stamp, current weather |
| Forecast strip | `y: 92–140` | Today, tonight, tomorrow |
| Status grid | `y: 140–410` | Claude, Codex, Gmail |
| Quote footer | `y: 410–480` | One short, attributed live quote per day |

The status grid has three equal columns: `x: 0–267`, `267–534`, and `534–800`. Use one-pixel rules only at region and column boundaries. Leave a clear gap between the large allowance figure and its lower reset information; the figure must never compete with the operational details.

## Typography

- **Display numbers and headings:** Barlow Condensed SemiBold. Its tall, narrow shapes make percentages and time readable from across a desk without wasting horizontal space.
- **Supporting labels:** IBM Plex Mono Medium. Its mechanical, measured character supports the instrument-panel feeling and keeps reset times easy to scan.
- **Quote:** IBM Plex Serif Italic. This is the sole human, editorial note in an otherwise utilitarian screen.

### Weather marks

The header uses four bespoke monochrome instrument marks: clear, partly cloudy,
cloudy, and rain. They are drawn from simple circles, arcs, and 2-pixel lines
inside the renderer rather than supplied by emoji, an icon font, or an external
asset. This keeps them crisp and dependable on a 1-bit panel. The partly-cloudy
mark uses a rayless sun behind one clean cloud silhouette: the symbol must be
legible at a glance, not illustrate the whole sky.

The production renderer bundles these open-source font files with the app rather than relying on a network request. Their license files live beside the font assets.

| Role | Font / size |
| --- | --- |
| Updated stamp | IBM Plex Mono Medium, 18 px |
| Header date / weather | Barlow Condensed SemiBold, 28 px |
| Forecast item | IBM Plex Mono Medium, 18 px |
| Column heading | Barlow Condensed SemiBold, 38 px |
| Usage value / unread count | Barlow Condensed SemiBold, 90–104 px |
| Usage label / reset time | IBM Plex Mono Medium, 17–19 px |
| Quote / attribution | IBM Plex Serif Italic 20 px / IBM Plex Mono Medium 16 px |

## Color

```css
:root {
  --paper: #ffffff;  /* panel white */
  --ink: #000000;    /* panel black */
}
```

The desktop preview may use `#f7f5ef` as its page background to evoke paper, but production output must remain strict 1-bit black and white.

## Content rules

- The header always stays stable: date left, last-updated stamp centered, current condition right. It is not a live clock; it changes only when an intentional screen refresh occurs.
- The forecast strip shows **Today**, **Tonight**, and **Tomorrow**. Every label uses the same 20 px condensed face; every value uses the same 14 px mono face. Use tight temperature pairs (`78°/65°`), not padded ones, and preserve the type scale rather than shrinking a long third item.
- Claude and Codex window labels use Barlow Condensed SemiBold so their short words remain compact and naturally spaced. IBM Plex Mono is reserved for the changing, exact time or percentage in Claude's aligned detail rows.
- Claude shows its two distinct allowances as `5-HOUR LEFT` and `WEEK LEFT`, each paired directly with a plainly labelled reset. The weekly reset always includes both date and time. Its two short detail rows align labels left and values right; never run label and time together as one long monospaced sentence.
- Codex is a weekly-budget display: it shows `WEEK LEFT` and one full date-and-time reset. When Codex App Server returns both a shorter primary window and a weekly secondary window, use the actual weekly secondary window. Missing data renders as an em dash—never guessed or sample-looking values.
- Gmail shows only unread count. It must not expose subject lines or personal message content.
- Quotes are short, attributed, and fetched once at the daily refresh. There is no quote cache or fallback.

## Refresh rules

- Render only when data has changed or on the scheduled cadence.
- Working hours: check data every 15 minutes; refresh the panel at most once per 15 minutes.
- Overnight: check hourly; refresh only for meaningful changes.
- Weather: update hourly. Quote: update daily. Manual refresh remains available.
- Periodically force a full panel refresh to clear ghosting; the exact interval will be tuned on the physical display.

## Do / don't

**Do** use large numerals, fixed layout positions, and whitespace because the display should remain legible from beside a monitor.

**Do** let a single forecast strip and a single daily quote add personality without competing with operational information.

**Don't** add live spinners, animations, tiny charts, or second-by-second agent states; they fight the e-paper medium.

**Don't** use red/yellow/green status semantics. On this screen, changing numbers and clear labels are more trustworthy than decorative alarms.
