#!/usr/bin/env python3
"""Wind notifier for Saint-Raphaël (Le Lion de Mer WeatherLink station).

Polls the WeatherLink summary JSON and sends a Signal note-to-self when the
wind exceeds WIND_THRESHOLD_KN. Designed to run from cron every 15 minutes.

Signal messages are sent through a signal-cli-rest-api container
(https://github.com/bbernhard/signal-cli-rest-api), see docker-compose.yml.

State is kept in a small JSON file so we only notify on the below->above
crossing, then at most once per WIND_REMIND_EVERY_S while it stays windy.

Configuration is read from environment variables (defaults in parentheses):
  SIGNAL_NUMBER        Signal account number, e.g. +33612345678 (required)
  SIGNAL_API_URL       signal-cli-rest-api base URL (http://localhost:8080)
  WIND_THRESHOLD_KN    notification threshold in knots (15)
  WIND_REMIND_EVERY_S  reminder period while above threshold (3600)
  WIND_STATE_FILE      state file path (~/.local/state/wind_notify.json)
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

EMBED_ID = "d8f389c51427467eb5c4f266caaf78a9"
URL = f"https://www.weatherlink.com/embeddablePage/summaryData/{EMBED_ID}"

SIGNAL_NUMBER = os.environ.get("SIGNAL_NUMBER", "")
SIGNAL_API_URL = os.environ.get("SIGNAL_API_URL", "http://localhost:8080")
THRESHOLD_KN = float(os.environ.get("WIND_THRESHOLD_KN", "15"))
REMIND_EVERY_S = int(os.environ.get("WIND_REMIND_EVERY_S", "3600"))
STATE_FILE = Path(
    os.environ.get("WIND_STATE_FILE", Path.home() / ".local/state/wind_notify.json")
)
STALE_AFTER_S = 3600  # ignore station data older than this

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    return COMPASS[int((deg / 22.5) + 0.5) % 16]


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "wind-notify/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def extract(data):
    vals = {v["sensorDataName"]: v["value"] for v in data["currConditionValues"]}
    return {
        "last_received": data["lastReceived"] / 1000,  # ms -> s
        "speed": vals.get("Wind Speed"),
        "avg10": vals.get("10 Min Avg Wind Speed"),
        "high10": vals.get("10 Min High Wind Speed"),
        "direction": vals.get("Wind Direction"),
    }


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"above": False, "last_notified": 0}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def send_signal(message):
    payload = json.dumps({
        "message": message,
        "number": SIGNAL_NUMBER,
        "recipients": [SIGNAL_NUMBER],  # note to self
    }).encode()
    req = urllib.request.Request(
        f"{SIGNAL_API_URL}/v2/send",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    if not SIGNAL_NUMBER:
        sys.exit("SIGNAL_NUMBER environment variable is required")

    now = time.time()
    w = extract(fetch())

    if now - w["last_received"] > STALE_AFTER_S:
        print(f"stale data ({(now - w['last_received']) / 60:.0f} min old), skipping")
        return

    speed = w["avg10"] if w["avg10"] is not None else w["speed"]
    if speed is None:
        print("no wind speed in response, skipping")
        return

    state = load_state()
    above = speed >= THRESHOLD_KN
    crossing = above and not state["above"]
    reminder = above and state["above"] and now - state["last_notified"] >= REMIND_EVERY_S

    if crossing or reminder:
        direction = w["direction"]
        dir_txt = f"{compass(direction)} ({direction:.0f}°)" if direction is not None else "?"
        gust = f", gust {w['high10']:.1f} kn" if w["high10"] is not None else ""
        message = f"💨 Wind {speed:.1f} kn from {dir_txt}{gust} — Le Lion de Mer"
        send_signal(message)
        state["last_notified"] = now
        print(f"notified: {message}")
    else:
        print(f"{speed:.1f} kn, above={above}, no notification")

    state["above"] = above
    save_state(state)


if __name__ == "__main__":
    main()
