# Deribit Options Data Downloader

![CI](https://github.com/gptcompany/deribit-data-downloader/actions/workflows/ci.yml/badge.svg?branch=master)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/github/license/gptcompany/deribit-data-downloader?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/gptcompany/deribit-data-downloader?style=flat-square)
![Issues](https://img.shields.io/github/issues/gptcompany/deribit-data-downloader?style=flat-square)

High-performance Deribit options data downloader with crash recovery, streaming writes, and NautilusTrader compatibility.

## Key Features

- **⚡ Streaming Downloads**: No RAM accumulation, writes as it fetches to minimize memory footprint
- **🔄 Crash Recovery**: Intelligent resume from checkpoint after interruption
- **🔐 Atomic Writes**: Pattern-based (tmp + rename) to prevent data corruption on crash
- **📈 DVOL Index**: Specialized support for Deribit Volatility Index (DVOL) data
- **✅ Data Validation**: Configurable quality checks and integrity verification
- **📋 SHA256 Manifest**: Maintains a manifest for all downloaded files to ensure data integrity
- **🛠️ Production Ready**: Extensive testing and error handling with crash-safe architecture

## Project Structure

```
deribit-data-downloader/
├── src/                              # Core source code
│   └── deribit_data/                 # Main package implementation
├── tests/                            # Comprehensive test suite
│   ├── test_fetcher.py               # API interaction tests
│   ├── test_storage.py               # Data persistence tests
│   ├── test_checkpoint.py            # Resume capability tests
│   └── test_manifest.py              # Integrity verification tests
├── scripts/                          # Utility scripts
│   └── run-sync-with-notify.sh       # Docker entrypoint with Discord notifications
├── docs/                             # Documentation and guides
│   └── DATA_DICTIONARY.md            # Data schema and field descriptions
├── examples/                         # Usage examples
│   └── daily_sync.py                 # Daily incremental sync example
├── pyproject.toml                    # Project configuration (uv compatible)
├── uv.lock                           # Locked dependencies
├── Dockerfile                        # Container image for production sync
├── docker-compose.yml                # Container runtime definition
├── README.md                         # This file
└── deploy/systemd/                   # systemd units for Docker runs
```

## Installation

```bash
pip install deribit-data-downloader
```

Or with `uv` (recommended):

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

## Docker (Production)

```bash
# Optional: customize runtime parameters
cp .env.example .env

# Build image
docker compose build deribit-sync

# Run one sync job (BTC)
docker compose run --rm deribit-sync
```

Data persistence is controlled by `DERIBIT_DATA_ROOT` (volume mount in `docker-compose.yml`).
On this host, set `DERIBIT_REPO_ROOT` and `DERIBIT_DATA_ROOT` in `/etc/downloader-sync.env` and use the
`deploy/systemd/deribit-sync-docker.service` unit, which reads those variables via `EnvironmentFile=`.

### Docker-First Execution (CI)
These services are intended to run **inside Docker** (CI actions launch Docker services, not systemd).
The compose service runs `scripts/run-sync-with-notify.sh`, which captures the original run summary and
sends it to Discord when `DISCORD_WEBHOOK_HISTORY` is set.

### Notifications
Healthchecks pings are emitted by `cron-wrapper.sh` (monitoring-stack).
Discord delivery is configured via environment (no hardcoded webhook). On this host, the webhook is read
from `/media/sam/1TB/.env` via `dotenvx` (use `DISCORD_WEBHOOK_HISTORY` for run results), and
`DISCORD_NOTIFY_ON_SUCCESS=1` enables per-run success alerts.
To (re)configure the Healthchecks Discord webhook on this host, run:
```bash
dotenvx run -f /media/sam/1TB/.env -- /media/sam/1TB/monitoring-stack/scripts/configure-healthchecks-discord.sh
```

## CI/CD

This repository uses **GitHub Actions** for continuous integration and automated deployment.

### Testing
- **Triggers**: Workflows run on every push and pull request to `main` and `master`.
- **Testing**: Automated tests on Linux and macOS.
- **Coverage**: Reports uploaded to Codecov (OIDC auth).
- **Docker**: Docker builds verified during CI.

### Auto-Deploy Pipeline
On push to `master` (when `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, `src/**`, `scripts/**` change):

1. **Trigger**: `trigger-progressive-deploy.yml` dispatches `deribit-downloader-build` to `progressive-deploy`
2. **Build**: Progressive-deploy builds Docker image and pushes to `ghcr.io/gptcompany/deribit-downloader`
3. **GitOps**: Image tag updated in `gitops/apps/deribit-downloader/base/kustomization.yaml`
4. **Promotion**: Kargo promotes through dev → staging → prod

**Required secret**: `PROGRESSIVE_DEPLOY_PAT` (GitHub classic PAT with `repo` scope)

### Local Execution
The service runs nightly via systemd timer (`deribit-sync-docker.timer` at 06:00), syncing BTC then ETH sequentially:
```bash
docker compose run --rm deribit-sync      # BTC
docker compose run --rm deribit-sync-eth  # ETH
```

The systemd service uses `dotenvx` to load secrets from `/media/sam/1TB/.env` (SSOT) and `cron-wrapper.sh` from `monitoring-stack` for notifications. Runtime env vars are sourced from `/etc/downloader-sync.env` (contains `DERIBIT_REPO_ROOT`).

Additional compose profiles are available for manual backfill:
```bash
docker compose --profile backfill run --rm backfill-btc   # Full BTC backfill with resume
docker compose --profile backfill run --rm backfill-eth   # Full ETH backfill with resume
```

## Development

```bash
# Clone
git clone https://github.com/gptcompany/deribit-data-downloader
cd deribit-data-downloader

# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest tests/ -v --cov

# Lint
uv run ruff check .
uv run ruff format .
```

## License

MIT
