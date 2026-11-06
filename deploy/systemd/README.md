# Deribit sync on the Dell (systemd)

| unit | what |
|---|---|
| `deribit-sync.timer` / `.service` | 06:00 UTC, user `sam`: `deribit-data catchup` (BTC and ETH trades, then DVOL) |
| `deribit-sync-metrics.timer` / `.service` | hourly and after each sync, root, read-only on the catalog: writes `deribit_catalog.prom` |

`catchup` resumes by itself: trades from the newest stored trade (`sync` semantics, deduplicated by `trade_id`),
DVOL from the day after its newest candle. After an outage the first run therefore backfills the whole gap
(2026-06-30 onward for trades, 2026-02-06 onward for DVOL); progress is in the journal
(`journalctl -u deribit-sync -f`: `sync BTC: batch=… total=… up_to=…`, `catchup BTC dvol: done in …s`).
A failed step is logged, the others still run, the exit code is 1.

## Host variables

Defaults are in the units; override per host in `/etc/default/deribit-sync` (not versioned, no secrets):

| variable | default |
|---|---|
| `DERIBIT_REPO_ROOT` | `/media/sam/1TB/deribit-data-downloader` (needs `.venv`) |
| `DERIBIT_CATALOG_PATH` | `/media/sam/2TB-NVMe/data/deribit_options` |
| `DERIBIT_METRICS_FILE` | `/var/lib/prometheus/node-exporter/deribit_catalog.prom` |

## Install (operator)

```sh
cd "$DERIBIT_REPO_ROOT" && git pull --ff-only && uv sync --frozen --no-dev   # rebuilds .venv (broken since the OS reinstall)
sudo install -m 644 deploy/systemd/deribit-sync*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now deribit-sync-metrics.timer deribit-sync.timer
sudo systemctl start --no-block deribit-sync.service    # first catch-up, ~15 min for 130 days
```

## Metrics and alerts

`deribit_catalog_last_trade_timestamp_seconds{currency}`, `deribit_catalog_last_dvol_timestamp_seconds{currency}`,
`deribit_catalog_scan_timestamp_seconds`. Series without data are omitted. The alert rules
(`time() - last_* > 3d`, `absent(...)`, scan older than 3h) live in monitoring-stack, group `deribit-catalog`.
