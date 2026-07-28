# Frame One — Data Sources and Privacy Contract

## Decision

Frame One is **local-first**. The Raspberry Pi fetches and renders only the small set of values needed for the screen; it does not send dashboard data to a separate cloud service and it never stores email contents, prompts, repositories, or agent transcripts.

The first release has four automated providers (weather, Gmail, Codex, and Claude).

**On undocumented interfaces.** An earlier draft of this document forbade private or undocumented endpoints outright. That rule was written when no working method for reading agent allowances had been found, and it hardened a dead end into policy: it ruled out the only interfaces that actually return this data, and left the Claude tile permanently empty. It is withdrawn.

Frame One may read a subscription meter through whatever interface its vendor actually exposes, documented or not, using credentials the account owner authorizes on their own device. The tradeoff is accepted knowingly: undocumented interfaces carry no compatibility promise and may break without notice, so each such provider must fail closed to `unavailable` rather than fabricate a value. What remains non-negotiable is below.

## Common provider contract

Every provider returns this envelope to the renderer:

```json
{
  "provider": "weather",
  "state": "ok",
  "updated_at": "2026-07-25T10:00:00-04:00",
  "stale_after_seconds": 5400,
  "data": {}
}
```

`state` is one of `ok`, `unavailable`, `needs_setup`, or `stale`. The renderer never invents a value: unavailable data displays an em dash and keeps the rest of the screen useful.

## Provider decisions

| Display block | Source | First-release decision | Refresh |
| --- | --- | --- | --- |
| Weather | Open-Meteo Forecast API | Automated, no account | Hourly |
| Gmail unread | Gmail API label metadata | Automated, OAuth read-only | Every 15 min |
| Claude allowance | Account OAuth (default) or Claude Code status line | Automated; OAuth runs standalone on the Pi | Every refresh round (OAuth) or event-driven (status line) |
| Codex allowance | Codex App Server | Automated after local ChatGPT sign-in | Every 15 min and on change |
| Quote | ZenQuotes daily endpoint | Automated, live-only | Daily |

### 1. Weather

**Provider:** [Open-Meteo Forecast API](https://open-meteo.com/en/docs).

**Cost:** no paid subscription, account, API key, or credit card is needed for this personal non-commercial dashboard. The free tier permits up to 10,000 calls per day; Frame One will make roughly 24 hourly forecast calls per day. The forecast data is CC BY 4.0, so Frame One will include “Weather: Open-Meteo” with the required attribution in its local setup/about screen.

**Configuration:** the setup screen stores a user-chosen latitude, longitude, timezone, and temperature unit locally on the Pi. It must never infer or transmit the user's location to any service other than the weather provider.

**Request shape:** request current conditions plus daily `temperature_2m_max`, `temperature_2m_min`, `weather_code`, and `precipitation_probability_max`; request hourly `temperature_2m`, `weather_code`, `precipitation_probability`, and `is_day`. Open-Meteo documents these variables and its coordinate-based forecast endpoint.

**Screen mapping:**

- Header: current temperature and condition icon.
- Forecast strip: Today high/low; Tonight temperature and rain probability; Tomorrow high/low and rain probability.
- Rain probability appears only at 20% or higher. Otherwise use the space for the condition name or leave it quiet.

### 2. Gmail unread count

**Provider:** [Gmail API label resource](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels).

**OAuth scope:** `https://www.googleapis.com/auth/gmail.readonly`.

**Request:** `GET /gmail/v1/users/me/labels/INBOX`, then display `threadsUnread`. This reads label metadata only; it does not fetch subjects, senders, message bodies, attachments, or message IDs. Gmail documents both `messagesUnread` and `threadsUnread`; Frame One uses unread threads because that is the conversation count shown by Gmail's Inbox badge, while a thread can contain multiple unread messages.

**Authorization:** the account owner creates a Google Desktop OAuth client, enables the Gmail API, then approves the `gmail.readonly` scope once through `frame-one-gmail-login`. The Pi receives the callback over an SSH loopback tunnel, so the browser login and the token exchange remain between the account owner and the local device.

**Storage:** the refresh token is stored in an owner-readable (`0600`) local file restricted to the dashboard service account. The token and any raw Gmail response must never be written to logs or sent to another device.

**Fallback:** show `—` with a small “Gmail setup required” message until OAuth setup is complete. No email-derived content is ever shown on the panel.

### 3. Claude allowance

Claude's paid plans expose five-hour and weekly limits. There are two ways to read them, and Frame One supports both.

**Primary — account OAuth (standalone).** The Pi holds its own OAuth credential, authorized once by the account owner in a browser, and reads the five-hour and seven-day windows directly. This is the only method that works with no second machine, so it is the default for a standalone panel. The endpoint is not part of Anthropic's published API surface and may change without notice; the provider therefore validates every field and reports `unavailable` rather than guessing when the shape is not what it expects.

**Alternative — Claude Code status line (no extra credential).** Claude Code's documented status-line contract includes `rate_limits.five_hour` and `rate_limits.seven_day` for Claude.ai Pro/Max subscribers after the first response in a session. Each window supplies `used_percentage` and a Unix `resets_at` timestamp. Two limits are worth knowing before choosing it: it fires only in **rendered interactive terminal sessions** — the Claude Code desktop app and `claude -p` never invoke it — and it therefore reports nothing while you are not actively working, and nothing at all about usage from claude.ai.

**Automatic collector:** a small status-line command receives the local JSON event and reduces it to only the following state:

```json
{
  "source": "claude-code-statusline",
  "rate_limits": {
    "five_hour": {
      "percent_remaining": 63,
      "resets_at": "2026-07-25T14:15:00-04:00"
    },
    "seven_day": {
      "percent_remaining": 81,
      "resets_at": "2026-07-28T00:00:00-04:00"
    }
  }
}
```

The collector performs no Claude request and stores no prompt, transcript, workspace, account identifier, or credential. The UI supports `—` for any unavailable meter.

**The SSH snapshot transport is the fallback path, not the default.** It applies only when the status-line collector is used instead of account OAuth. In that configuration a dedicated SSH key copies the snapshot to the Pi at most once every 15 minutes — so panel freshness is capped at 15 minutes unless `--sync-interval-seconds` is lowered. The key authenticates only to the Pi and is unrelated to Claude. With account OAuth configured, no SSH key, no second machine, and no transport are involved at all.

**Either way, only the meter is read.** Whichever method is configured, Frame One requests allowance percentages and reset timestamps and nothing else. It never reads conversations, prompts, transcripts, or project data, and never displays an account identifier on the panel.

References: [Claude Code status-line contract](https://code.claude.com/docs/en/statusline) and [Use Claude Code with a Pro or Max plan](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan).

### 4. Codex allowance

Codex usage is plan-dependent and can be shared with other agentic features. For this dashboard, use OpenAI's **Codex App Server**, which runs locally on the Pi and answers `account/rateLimits/read` without a second machine. It is preferred over any web interface because it is a supported local protocol that needs no extra credential, not because other interfaces are off-limits.

**Provider:** launch the local app server on the Pi and call `account/rateLimits/read`; subscribe to `account/rateLimits/updated` to invalidate the cached value. The official App Server documentation lists both methods.

**Authentication:** the user completes the ChatGPT/device-code sign-in once on the Pi with `codex login`. Frame One talks to the App Server over its local stdio protocol and leaves Codex's own credential store alone — not as a restriction, but because the App Server already handles auth, so there is nothing to gain by touching it. Codex tokens are never logged or transmitted.

**Screen mapping:** map the returned rate-limit windows to the two Codex lines in the UI. Preserve the server-provided labels and reset times rather than assuming a fixed five-hour or weekly model. The secondary reset must include its calendar date as well as its time. If the account does not expose a secondary window, show `WEEK —`.

**Fallback:** if a plan does not return a dashboard-suitable window, show `—`. Never calculate a remaining allowance from task counts or token estimates.

References: [Codex App Server API overview](https://learn.chatgpt.com/docs/app-server#api-overview-1), [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), and [Codex rate card](https://help.openai.com/en/articles/20001106-codex-rate-card).

### 5. Daily quote

**Provider:** [ZenQuotes' daily endpoint](https://docs.zenquotes.io/zenquotes-documentation/). It needs no API key at this scale and provides one daily quote.

Frame One fetches the quote during the 2:00 AM dashboard refresh. The adapter
accepts only a short quote with an author; an unsuitable or unreachable response
is `unavailable`. A successful daily quote is kept in the existing local
last-known-good state cache for up to two days, so normal five-minute renders do
not restore the sample placeholder. There is no bundled collection, recent-quote
list, or separate quote file. Include the required `Quotes: ZenQuotes.io`
attribution in the local setup/about screen.

## Refresh and failure policy

- The renderer checks sources on their schedules but redraws only when visible data changed. The panel write is skipped when the rendered pixels are identical, so an idle screen does not flash every five minutes.
- A refresh round runs every 5 minutes, collapsing to hourly between midnight and 6AM.
- Gmail is polled every 15 minutes; weather hourly; the live quote is fetched daily.
- A manual refresh button is available for a deliberate update.
- **Retry before giving up.** Every provider in a round shares one wall-clock deadline. Network sources retry three times with exponential backoff, the Codex App Server twice, and purely local file reads once — retrying a file read cannot change its answer, it only consumes the round's budget.
- **No provider aborts the round.** An unavailable provider never blocks the rest of the display.
- **Last-known-good.** A successful fetch is stamped with `updated_at` and `stale_after_seconds` and cached locally. If a later refresh fails, the tile keeps showing that value with `state: "stale"` until it ages past its window; then it becomes `—`. The renderer treats `ok` and `stale` alike, so a brief network blip does not blank a tile.
- Do not expose error messages, OAuth tokens, location coordinates, account email addresses, or stack traces on the e-paper panel.

## Implementation status

- Open-Meteo, ZenQuotes, the Claude Code status-line collector, the Codex App Server reader,
  and the Gmail INBOX-label reader are implemented.
- The retry, last-known-good, and refresh-cadence layer is implemented: every provider
  retries under one shared deadline, falls back to its last good value while that value is
  still inside `stale_after_seconds`, and then shows `—`. No provider can abort a round.
- The Gmail reader includes a local authorization command, but still requires a
  user-created Google Desktop OAuth client and one browser approval before its
  first live use.
- The Codex reader requires Codex CLI plus a local `codex login` on the Pi; it invokes only
  `account/rateLimits/read` over stdio JSON-RPC. The Pi runs 64-bit Raspberry Pi OS, which
  the `linux-arm64` build supports.
- **Not yet implemented:** the account-OAuth Claude provider. Until it lands, the Claude tile
  depends on the status-line collector, which only fires in interactive terminal sessions.

## Standalone status

Weather, the quote, Gmail, and Codex all run on the Pi with no second machine. Claude is the
one tile that cannot: the status-line collector only produces data on whichever machine runs
interactive terminal `claude`. The account-OAuth provider above is what closes that gap and
makes the panel fully standalone.

## Build order

1. Implement the shared state assembler and renderer using fixed sample data.
2. Add Open-Meteo, then Gmail OAuth / unread metadata.
3. Add the Codex App Server adapter, then the Claude Code status-line collector.
4. Add retry, last-known-good, and the refresh cadence.
5. Complete the Gmail authorization ceremony on the Pi.
6. Add the account-OAuth Claude provider so the panel needs no second machine.
7. Install the systemd timer that drives the refresh cadence.
