# deribit-data-downloader

![CI](https://github.com/gptcompany/deribit-data-downloader/actions/workflows/ci.yml/badge.svg?branch=main)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/github/license/gptcompany/deribit-data-downloader?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/gptcompany/deribit-data-downloader?style=flat-square)
![Issues](https://img.shields.io/github/issues/gptcompany/deribit-data-downloader?style=flat-square)

High-performance Deribit options data downloader with crash recovery, streaming writes, and NautilusTrader compatibility.

## Features

- **Streaming downloads** - No RAM accumulation, writes as it fetches
- **Crash recovery** - Resume from checkpoint after interruption
- **Atomic writes** - No data corruption on crash (tmp + rename pattern)
- **DVOL index** - Download Deribit Volatility Index (DVOL) data
- **Data validation** - Configurable quality checks
- **SHA256 manifest** - Verify data integrity

## Installation

```bash
pip install deribit-data-downloader
```

Or with uv:

```bash
uv pip install deribit-data-downloader
```

## Quick Start

```bash
# Full historical backfill (from 2016)
deribit-data backfill --currency ETH --catalog ./data/deribit

# Resume interrupted download
deribit-data backfill --currency ETH --catalog ./data/deribit --resume

# Daily incremental sync
deribit-data sync --currency BTC --catalog ./data/deribit

# Download DVOL index
deribit-data dvol --currency BTC --start 2024-01-01 --catalog ./data/deribit

# Validate data integrity
deribit-data validate --catalog ./data/deribit

# Show catalog info
deribit-data info --catalog ./data/deribit
```

## Configuration

All parameters are configurable via environment variables or CLI flags:

```bash
# Environment variables
export DERIBIT_CATALOG_PATH=/media/sam/2TB-NVMe/data/deribit_options
export DERIBIT_HTTP_TIMEOUT=30
export DERIBIT_MAX_RETRIES=3
export DERIBIT_COMPRESSION=zstd
export DERIBIT_FLUSH_EVERY_PAGES=100

# Run with env config
deribit-data backfill --currency ETH
```

## Output Format

Data is written as Parquet files with daily partitioning:

```
catalog/
├── BTC/
│   ├── trades/
│   │   ├── 2024-01-01.parquet
│   │   ├── 2024-01-02.parquet
│   │   └── ...
│   └── dvol/
│       └── dvol.parquet
├── ETH/
│   ├── trades/
│   └── dvol/
└── manifest.json
```

### Schema (v1)

**Trades:**
| Column | Type | Description |
|--------|------|-------------|
| timestamp | timestamp[us, UTC] | Trade execution time |
| instrument_id | string | Full instrument name |
| underlying | string | BTC or ETH |
| strike | float64 | Strike price |
| expiry | timestamp[us, UTC] | Option expiry |
| option_type | string | call or put |
| price | float64 | Trade price |
| iv | float64 | Implied volatility |
| amount | float64 | Trade size |
| direction | string | buy or sell |

**DVOL:**
| Column | Type | Description |
|--------|------|-------------|
| timestamp | timestamp[us, UTC] | Candle time |
| open | float64 | Opening IV |
| high | float64 | High IV |
| low | float64 | Low IV |
| close | float64 | Closing IV |

## Docker

```bash
# Build
docker build -t deribit-data-downloader .

# Run with volume mount
docker run -v /path/to/data:/data deribit-data-downloader \
    backfill --currency ETH --catalog /data/deribit
```

### Docker-First Execution (CI)
These services are intended to run **inside Docker** (CI actions launch Docker services, not systemd).
For notifications, set `DISCORD_WEBHOOK_HISTORY` and the container will send the run summary.
The compose services use `scripts/run-sync-with-notify.sh` so the summary sent to Discord matches the
original CLI output.

### Systemd + Paths (Host Configuration)
This host uses `/etc/downloader-sync.env` for path configuration:
`DERIBIT_REPO_ROOT` points to the repo location and `DERIBIT_DATA_ROOT` points to the persisted catalog path.
`docker-compose.yml` reads `DERIBIT_DATA_ROOT` for data persistence.

### Notifications
Healthchecks pings are emitted by `cron-wrapper.sh` (monitoring-stack).
Discord delivery is configured via environment (no hardcoded webhook). On this host, the webhook is read
from `/media/sam/1TB/.env` via `dotenvx` (use `DISCORD_WEBHOOK_HISTORY` for run results), and
`DISCORD_NOTIFY_ON_SUCCESS=1` enables per-run success alerts.
To (re)configure the Healthchecks Discord webhook on this host, run:
```bash
dotenvx run -f /media/sam/1TB/.env -- /media/sam/1TB/monitoring-stack/scripts/configure-healthchecks-discord.sh
```

## Development

```bash
# Clone
git clone https://github.com/yourusername/deribit-data-downloader
cd deribit-data-downloader

# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest tests/ -v --cov

# Lint
uv run ruff check .
uv run ruff format .
```


## CI/CD

This repository uses **GitHub Actions** for continuous integration.

- **Triggers**: Workflows run on every push and pull request to `main` and `master`.
- **Testing**: Automated tests are executed on both Linux and macOS.
- **Coverage**: Coverage reports are uploaded to **Codecov** using secure **OIDC** authentication.
- **Docker**: Docker builds are automatically verified during CI.

## License

MIT
