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

## Deploying to the home server (Freebox VM)

One-time, from the home LAN (the VM is not reachable from outside):

```bash
# 1. On the VM
ssh co@192.168.1.81
git clone https://github.com/BelCorentin/wind-notify && cd wind-notify
docker compose up -d

# 2. From the laptop: copy the already-linked Signal keys
#    (avoids re-scanning a QR code; the VM becomes the "windbot" device)
scp -r ~/tmp/claude/wind-notify/signal-cli-config co@192.168.1.81:wind-notify/
ssh co@192.168.1.81 "cd wind-notify && docker compose restart"

# 3. Sanity check on the VM
curl -s http://localhost:8080/v1/accounts        # expect ["+33695209684"]
SIGNAL_NUMBER=+33695209684 WIND_THRESHOLD_KN=5 \
  WIND_STATE_FILE=/tmp/wind_test.json python3 wind_notify.py   # forces a notif

# 4. Cron on the VM
crontab -e
# */15 * * * * SIGNAL_NUMBER=+33695209684 /usr/bin/python3 /home/co/wind-notify/wind_notify.py >> /home/co/wind_notify.log 2>&1
```

Then remove the interim cron entry on the laptop (`crontab -e`).

Important: only one machine should run the container with a given
`signal-cli-config` — don't leave both the laptop and the VM sending
from the same linked device.

Optional: enable the Freebox WireGuard VPN server (Freebox OS → VPN
serveur) to reach the VM from outside home.

## Concepts (what you'd need to know to build this)

- **Embedded widgets hide clean APIs.** The port's webpage doesn't
  contain wind data — it embeds a WeatherLink iframe. Opening the
  browser dev tools (Network tab) on such a widget shows the JSON
  endpoint the widget itself calls. Consuming that endpoint directly is
  far more robust than scraping HTML: you get typed values (`13.9`,
  `"knots"`) instead of parsing markup that changes with every redesign.
- **Polling + cron.** Nothing here runs continuously: cron starts the
  script every 15 minutes, the script does one fetch, maybe one send,
  and exits. For infrequent checks this beats a daemon — no process to
  babysit, survives reboots for free.
- **State + hysteresis for alerts.** A naive "if wind > 15 notify"
  would message every 15 minutes all afternoon. The script persists a
  tiny JSON state file between runs and only notifies on the
  below→above *crossing*, plus one hourly reminder while it stays
  windy. Any alerting system (monitoring, CI, etc.) needs this pattern.
- **Signal has no simple bot API.** Unlike Telegram, Signal is
  end-to-end encrypted with keys held by devices, so you can't just
  POST to a web API with a token. `signal-cli` implements a full Signal
  client; it gets *linked* to your account as a secondary device (like
  Signal Desktop) and holds its own keys — that's the QR-code ceremony,
  and why `signal-cli-config/` is secret material, not config.
- **Docker as an installation shortcut.** signal-cli needs a Java/native
  runtime and versioned upkeep; `bbernhard/signal-cli-rest-api` wraps it
  in a container exposing plain HTTP (`POST /v2/send`). The compose file
  maps a host port (`127.0.0.1:8080` — localhost-only, so nothing else
  on the network can send as you) and mounts `./signal-cli-config` as a
  volume so keys survive container recreation.
- **Configuration via environment variables.** The script has no config
  file; number, threshold, URL come from env vars with defaults. That
  keeps secrets out of git and lets the same code run in test
  (`WIND_THRESHOLD_KN=5`) and production without edits.
- **Fail loudly, skip stale.** The script trusts cron+log for
  visibility: any unexpected error raises and lands in the log, and
  station data older than 1 h is skipped rather than alerting on
  yesterday's wind.

## Troubleshooting

- **Phone says "incorrect QR code"**: you must scan from Signal →
  Settings → Linked devices → *Link new device* — not the regular
  in-chat QR scanner. Also, each QR is single-use and expires after
  ~1 minute; regenerate if in doubt.
- **`User +336... is not registered` on send**: the API process loads
  accounts at startup — restart the container after linking
  (`docker compose restart`). If you linked with `docker exec ...
  signal-cli link` instead of the `/v1/qrcodelink` endpoint, the account
  data was written to `/root/.local/share/signal-cli` (exec runs as
  root); move it into the mounted config dir:
  `docker exec signal-api sh -c 'cp -r /root/.local/share/signal-cli/data /home/.local/share/signal-cli/ && chown -R 1000:1000 /home/.local/share/signal-cli'`
  then restart.
- **Port 8080 already taken**: `SIGNAL_API_PORT=8081 docker compose up -d`
  and set `SIGNAL_API_URL=http://localhost:8081` for the script.

## Caveats

- The `summaryData` endpoint is unofficial (it's what the embed widget
  itself calls). If WeatherLink changes it, the script fails loudly in the
  log; the fix is to grab the new embed URL from the port's webpage.
- Wind direction is where the wind comes *from*, in degrees, converted to
  a 16-point compass rose.
