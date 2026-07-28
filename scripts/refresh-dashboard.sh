#!/bin/sh
# Refresh the complete live dashboard once.  systemd supplies the explicit
# weather coordinates through dashboard.env; this script deliberately never
# geocodes or stores a street address.

set -eu

: "${WEATHER_LATITUDE:?dashboard.env must set WEATHER_LATITUDE}"
: "${WEATHER_LONGITUDE:?dashboard.env must set WEATHER_LONGITUDE}"
: "${WEATHER_TIMEZONE:?dashboard.env must set WEATHER_TIMEZONE}"

frame_one_root=${FRAME_ONE_ROOT:-/home/rgehrsitz/frame-one}
frame_one_config=${FRAME_ONE_CONFIG_DIR:-/home/rgehrsitz/.config/frame-one}

exec "$frame_one_root/.venv/bin/frame-one" \
  --input "$frame_one_root/samples/dashboard-state.json" \
  --output "$frame_one_root/output/live-dashboard.png" \
  --state-cache "$frame_one_root/output/live-dashboard-state.json" \
  --live-weather \
  --weather-latitude "$WEATHER_LATITUDE" \
  --weather-longitude "$WEATHER_LONGITUDE" \
  --weather-timezone "$WEATHER_TIMEZONE" \
  --claude-oauth-credentials "$frame_one_config/claude-oauth.json" \
  --live-codex \
  --gmail-token "$frame_one_config/gmail.token.json" \
  "$@" \
  --display waveshare-7in5-v2
