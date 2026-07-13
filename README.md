# wind-notify

Signal notifications when the wind picks up in the bay of Saint-Raphaël.

Every 15 minutes (cron), the script polls the [Davis WeatherLink station
"Le Lion de Mer"](https://www.weatherlink.com/embeddablePage/show/d8f389c51427467eb5c4f266caaf78a9/summary)
— the station embedded on the
[Régie des ports Raphaëlois page](https://www.ville-saintraphael.fr/utile/la-regie-des-ports-raphaelois) —
and sends a Signal *note to self* when the 10-minute average wind speed
crosses the threshold (default 15 kn):

> 💨 Wind 16.2 kn from ESE (105°), gust 18.4 kn — Le Lion de Mer

## How it works

```
cron (*/15) ──> wind_notify.py ──HTTP──> weatherlink.com JSON
                     │
                     └──POST /v2/send──> signal-cli-rest-api (docker) ──> Signal
```

- **Data source**: the WeatherLink embeddable-page JSON endpoint
  (`https://www.weatherlink.com/embeddablePage/summaryData/<embed-id>`).
  No HTML scraping — this is the same endpoint the official widget calls.
  It returns current wind speed/direction, 2-min and 10-min averages and
  highs, in knots.
- **Signal**: [`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api)
  runs as a container, linked to your Signal account as a secondary device
  ("windbot"). The script sends one HTTP POST to it.
- **Anti-spam**: a small state file tracks whether the wind was already
  above the threshold. You get one message on the below→above crossing,
  then at most one reminder per hour while it stays windy. Data older than
  1 h (station down) is ignored.
- **No dependencies**: Python 3 stdlib only.

## Setup

Needs: docker + docker compose, python3. Works on any always-on Linux box
(Freebox VM, home server, ...). Only *outbound* internet access is
required.

### 1. Start the Signal API container

```bash
docker compose up -d
```

### 2. Link it to your Signal account (once)

```bash
curl -s "http://localhost:8080/v1/qrcodelink?device_name=windbot" -o qr.png
xdg-open qr.png   # or open it any other way
```

Scan the QR code with your phone: Signal app → Settings → Linked devices
→ Link new device. The link expires after ~1 minute; re-run the curl if
needed.

The device state lives in `./signal-cli-config/` (git-ignored — it
contains your Signal keys, treat it like a private key). Moving to
another machine: either copy that directory, or just link again there.

### 3. Test a send

```bash
export SIGNAL_NUMBER="+33612345678"   # your number
curl -s -X POST http://localhost:8080/v2/send \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"windbot test\", \"number\": \"$SIGNAL_NUMBER\", \"recipients\": [\"$SIGNAL_NUMBER\"]}"
```

You should receive a *note to self*.

### 4. Cron

```cron
*/15 * * * * SIGNAL_NUMBER=+33612345678 /usr/bin/python3 /path/to/wind_notify.py >> $HOME/wind_notify.log 2>&1
```

## Configuration

All via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SIGNAL_NUMBER` | — (required) | Signal account, also the recipient (note to self) |
| `SIGNAL_API_URL` | `http://localhost:8080` | signal-cli-rest-api base URL |
| `WIND_THRESHOLD_KN` | `15` | notify when 10-min avg wind ≥ this (knots) |
| `WIND_REMIND_EVERY_S` | `3600` | reminder period while it stays windy |
| `WIND_STATE_FILE` | `~/.local/state/wind_notify.json` | anti-spam state |

Quick mock test (current wind is usually > 5 kn):

```bash
WIND_THRESHOLD_KN=5 WIND_STATE_FILE=/tmp/wind_test.json SIGNAL_NUMBER=+33612345678 python3 wind_notify.py
```

## Caveats

- The `summaryData` endpoint is unofficial (it's what the embed widget
  itself calls). If WeatherLink changes it, the script fails loudly in the
  log; the fix is to grab the new embed URL from the port's webpage.
- Wind direction is where the wind comes *from*, in degrees, converted to
  a 16-point compass rose.
