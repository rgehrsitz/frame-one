# Frame One — Data Sources and Privacy Contract

## Decision

Frame One is **local-first**. The Raspberry Pi fetches and renders only the small set of values needed for the screen; it does not send dashboard data to a separate cloud service and it never stores email contents, prompts, repositories, or agent transcripts.

The first release has three automated providers (weather, Gmail, and Codex) and one deliberately optional usage provider (Claude). Claude's consumer-subscription meter is not a public developer API, so the project must not scrape private web endpoints or rely on undocumented application storage.

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
| Claude allowance | Claude Settings > Usage | Opt-in bridge; no scraping | Manual or 15 min when a supported source exists |
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

**Request:** `GET /gmail/v1/users/me/labels/INBOX`, then display `messagesUnread`. This reads label metadata only; it does not fetch subjects, senders, message bodies, attachments, or message IDs. Gmail documents both `messagesUnread` and `threadsUnread`; Frame One uses messages by default because its label is “UNREAD.”

**Storage:** the refresh token is encrypted at rest on the Pi and restricted to the dashboard service account. The token and any raw Gmail response must never be written to logs or sent to another device.

**Fallback:** show `—` with a small “Gmail setup required” message until OAuth setup is complete. No email-derived content is ever shown on the panel.

### 3. Claude allowance

Claude's paid plans have a five-hour session limit and a weekly limit, with the reset information exposed in **Settings > Usage**. Anthropic documents those consumer-plan concepts, but not a public API that a personal dashboard can use to retrieve the remaining percentages and resets automatically.

**Decision:** do not scrape Claude's web UI, browser session, cookies, or private endpoints.

**First-release bridge:** a tiny local `frame-one set claude` command accepts only:

```json
{
  "five_hour_percent_remaining": 63,
  "five_hour_resets_at": "2026-07-25T14:15:00-04:00",
  "week_percent_remaining": 81,
  "week_resets_at": "2026-07-28T00:00:00-04:00"
}
```

This is intentionally manual at first. A future automatic adapter is acceptable only if Anthropic publishes a supported API or a stable, user-authorized local interface. The UI supports `—` for any unavailable meter.

References: [Claude Pro plan limits](https://support.claude.com/en/articles/8325606-what-is-the-pro-plan) and [Claude usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

### 4. Codex allowance

Codex usage is plan-dependent and can be shared with other agentic features. For this dashboard, use OpenAI's documented **Codex App Server** rather than screen-scraping the desktop app or ChatGPT website.

**Provider:** launch the local app server on the Pi and call `account/rateLimits/read`; subscribe to `account/rateLimits/updated` to invalidate the cached value. The official App Server documentation lists both methods.

**Authentication:** the user completes the supported local ChatGPT/device-code sign-in once on the Pi. The dashboard process must communicate with the App Server only through its documented local protocol; it must not extract, copy, log, or transmit Codex authentication tokens.

**Screen mapping:** map the returned rate-limit windows to the two Codex lines in the UI. Preserve the server-provided labels and reset times rather than assuming a fixed five-hour or weekly model. The secondary reset must include its calendar date as well as its time. If the account does not expose a secondary window, show `WEEK —`.

**Fallback:** if a plan does not return a dashboard-suitable window, show `—` and retain the optional manual bridge. Never calculate a remaining allowance from task counts or token estimates.

References: [Codex App Server API overview](https://learn.chatgpt.com/docs/app-server#api-overview-1), [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), and [Codex rate card](https://help.openai.com/en/articles/20001106-codex-rate-card).

### 5. Daily quote

**Provider:** [ZenQuotes' daily endpoint](https://docs.zenquotes.io/zenquotes-documentation/). It needs no API key at this scale and provides one daily quote.

Frame One fetches the quote when the daily dashboard refresh runs. It provides **no bundled collection, local cache, recent-quote list, or fallback quote**. The adapter accepts only a short quote with an author; an unsuitable or unreachable response is `unavailable`. In that case, the updater must retain the existing e-paper image rather than render a blank or substituted quote. Include the required `Quotes: ZenQuotes.io` attribution in the local setup/about screen.

## Refresh and failure policy

- The renderer checks sources on their schedules but redraws only when visible data changed.
- Gmail is polled every 15 minutes; weather hourly; the live quote is fetched daily.
- A manual refresh button is available for a deliberate update.
- An unavailable provider does not block the rest of the display.
- The screen's last-successful value may remain visible until its `stale_after_seconds` passes; then replace it with `—`.
- Do not expose error messages, OAuth tokens, location coordinates, account email addresses, or stack traces on the e-paper panel.

## Implementation status

- Open-Meteo, ZenQuotes, the Claude manual bridge, the Codex App Server reader,
  and the Gmail INBOX-label reader are implemented.
- The Gmail reader requires a user-created, read-only OAuth token. Its initial
  authorization ceremony and the Pi refresh scheduler are the next setup work.
- The Codex reader requires Codex CLI plus its supported local ChatGPT sign-in
  on the Pi; it invokes only `account/rateLimits/read` over stdio JSON-RPC.

## Build order

1. Implement the shared state assembler and renderer using fixed sample data.
2. Add Open-Meteo, then Gmail OAuth / unread metadata.
3. Add the documented Codex App Server adapter, then the manual Claude bridge command.
4. Complete the Gmail authorization ceremony and scheduled local updater.
5. Revisit an automatic Claude adapter only when Anthropic publishes a supported source or the user explicitly chooses a supported integration.
