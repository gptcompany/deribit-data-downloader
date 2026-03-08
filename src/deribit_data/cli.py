"""CLI for Deribit data downloader.

Commands:
- backfill: Full historical download
- sync: Incremental daily sync
- dvol: Download DVOL index
- validate: Run validation
- info: Show catalog info
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from deribit_data.audit import AuditLog
from deribit_data.checkpoint import CheckpointManager
from deribit_data.config import DeribitConfig
from deribit_data.dead_letter import DeadLetterQueue
from deribit_data.fetcher import DeribitFetcher
from deribit_data.manifest import ManifestManager
from deribit_data.reconciliation import DataReconciler
from deribit_data.storage import ParquetStorage
from deribit_data.validator import DataValidator

console = Console()


def setup_logging(verbose: bool) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """Deribit data downloader - High-performance options data fetcher."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command()
@click.option(
    "-c",
    "--currency",
    required=True,
    type=click.Choice(["BTC", "ETH"], case_sensitive=False),
    help="Currency to download",
)
@click.option(
    "--catalog",
    type=click.Path(path_type=Path),
    default=None,
    help="Catalog path (default: from env or ./data/deribit_options)",
)
@click.option(
    "--start",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Start date (default: 2016-01-01)",
)
@click.option(
    "--end",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="End date (default: yesterday)",
)
@click.option("--resume", is_flag=True, help="Resume from checkpoint")
@click.option("--verify", is_flag=True, help="Verify after download")
@click.option("--config", type=click.Path(path_type=Path), help="Config file path")
@click.pass_context
def backfill(
    ctx: click.Context,
    currency: str,
    catalog: Path | None,
    start: datetime | None,
    end: datetime | None,
    resume: bool,
    verify: bool,
    config: Path | None,
) -> None:
    """Full historical backfill from Deribit.

    Downloads all historical options trades for a currency.
    Supports crash recovery with --resume.

    Example:
        deribit-data backfill --currency ETH --catalog ./data
    """
    # Load config
    cfg = DeribitConfig.from_file(config) if config else DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    currency = currency.upper()

    # Date range
    start_date = (
        start.replace(tzinfo=timezone.utc)
        if start
        else datetime(
            cfg.historical_start_date.year,
            cfg.historical_start_date.month,
            cfg.historical_start_date.day,
            tzinfo=timezone.utc,
        )
    )
    end_date = (
        end.replace(tzinfo=timezone.utc)
        if end
        else (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=23, minute=59, second=59)
    )

    console.print(f"[bold]Backfill {currency}[/bold]")
    console.print(f"  Catalog: {cfg.catalog_path}")
    console.print(f"  Range: {start_date.date()} to {end_date.date()}")

    # Initialize components
    checkpoint_mgr = CheckpointManager(cfg.checkpoint_dir)
    storage = ParquetStorage(cfg.catalog_path, cfg.compression, cfg.compression_level)
    manifest = ManifestManager(cfg.catalog_path)
    dlq = DeadLetterQueue(cfg.catalog_path)
    audit = AuditLog(cfg.catalog_path)

    # Track timing
    start_time = time.time()

    # Check for existing checkpoint
    checkpoint = None
    resume_from_ms = None
    if resume and checkpoint_mgr.exists(currency):
        checkpoint = checkpoint_mgr.load(currency)
        if checkpoint:
            resume_from_ms = checkpoint.last_timestamp_ms
            console.print(f"  [yellow]Resuming from page {checkpoint.last_page}[/yellow]")
    elif not resume and checkpoint_mgr.exists(currency):
        console.print("[yellow]Warning: Checkpoint exists. Use --resume to continue.[/yellow]")

    # Create initial checkpoint if not resuming
    if not checkpoint:
        checkpoint = checkpoint_mgr.create_initial(currency)

    # Log start event
    audit.log_backfill_start(currency, start_date, end_date, resume=resume)

    # Fetch and save
    total_trades = checkpoint.trades_fetched
    total_files: list[str] = list(checkpoint.files_written)

    try:
        with (
            DeribitFetcher(cfg) as fetcher,
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress,
        ):
            task = progress.add_task(f"Fetching {currency}...", total=None)

            for batch in fetcher.fetch_trades_streaming(
                currency=currency,
                start_date=start_date,
                end_date=end_date,
                resume_from_ms=resume_from_ms,
                dead_letter_queue=dlq,
            ):
                # Save batch
                written_files = storage.save_trades(batch, currency)

                # Update manifest
                for f in written_files:
                    manifest.update_file(f)
                    if str(f) not in total_files:
                        total_files.append(str(f))

                # Update checkpoint
                last_ts = int(batch[-1].timestamp.timestamp() * 1000)
                checkpoint = checkpoint.update_progress(
                    timestamp_ms=last_ts,
                    page=checkpoint.last_page + cfg.flush_every_pages,
                    trades_count=len(batch),
                    file_written=str(written_files[-1]) if written_files else None,
                )
                checkpoint_mgr.save(checkpoint)

                total_trades += len(batch)
                progress.update(
                    task,
                    description=f"Fetching {currency}... {total_trades:,} trades",
                )

        # Save manifest
        manifest.save()

        # Delete checkpoint on success
        checkpoint_mgr.delete(currency)

        console.print(
            f"[green]Complete: {total_trades:,} trades in {len(total_files)} files[/green]"
        )

        # Report DLQ stats
        dlq_failures = dlq.get_total_failures(currency)
        if dlq_failures > 0:
            console.print(
                f"[yellow]Warning: {dlq_failures:,} trades failed to parse "
                f"(see {cfg.catalog_path}/_dead_letters/)[/yellow]"
            )

        # Log completion
        duration = time.time() - start_time
        audit.log_backfill_complete(
            currency=currency,
            trades_count=total_trades,
            files_count=len(total_files),
            duration_seconds=duration,
            dlq_failures=dlq_failures,
        )

    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. Use --resume to continue.[/yellow]")
        sys.exit(1)
    except Exception as e:
        audit.log_backfill_error(currency, str(e))
        console.print(f"[red]Error: {e}[/red]")
        console.print("[yellow]Use --resume to continue from checkpoint.[/yellow]")
        raise

    # Verify if requested
    if verify:
        ctx.invoke(validate, currency=currency, catalog=cfg.catalog_path)


@main.command()
@click.option(
    "-c",
    "--currency",
    required=True,
    type=click.Choice(["BTC", "ETH"], case_sensitive=False),
    help="Currency to sync",
)
@click.option("--catalog", type=click.Path(path_type=Path), default=None, help="Catalog path")
@click.pass_context
def sync(ctx: click.Context, currency: str, catalog: Path | None) -> None:
    """Incremental daily sync.

    Fetches new trades since last download.
    """
    cfg = DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    currency = currency.upper()
    storage = ParquetStorage(cfg.catalog_path, cfg.compression, cfg.compression_level)
    manifest = ManifestManager(cfg.catalog_path)
    dlq = DeadLetterQueue(cfg.catalog_path)

    # Get last timestamp
    last_ts = storage.get_last_trade_timestamp(currency)
    if not last_ts:
        console.print("[yellow]No existing data. Run backfill first.[/yellow]")
        return

    start_date = last_ts + timedelta(seconds=1)
    end_date = datetime.now(timezone.utc)

    console.print(f"[bold]Sync {currency}[/bold]")
    console.print(f"  From: {start_date.isoformat()}")

    total_trades = 0
    with DeribitFetcher(cfg) as fetcher:
        for batch in fetcher.fetch_trades_streaming(
            currency=currency,
            start_date=start_date,
            end_date=end_date,
            dead_letter_queue=dlq,
        ):
            written_files = storage.save_trades(batch, currency)
            for f in written_files:
                manifest.update_file(f)
            total_trades += len(batch)

    manifest.save()
    console.print(f"[green]Synced {total_trades:,} new trades[/green]")

    # Report DLQ stats
    dlq_failures = dlq.get_total_failures(currency)
    if dlq_failures > 0:
        console.print(f"[yellow]Warning: {dlq_failures:,} trades failed to parse[/yellow]")


@main.command()
@click.option(
    "-c",
    "--currency",
    required=True,
    type=click.Choice(["BTC", "ETH"], case_sensitive=False),
    help="Currency",
)
@click.option(
    "--start",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="Start date",
)
@click.option(
    "--end",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="End date (default: today)",
)
@click.option("--catalog", type=click.Path(path_type=Path), default=None, help="Catalog path")
def dvol(
    currency: str,
    start: datetime,
    end: datetime | None,
    catalog: Path | None,
) -> None:
    """Download DVOL (Deribit Volatility Index) data.

    Example:
        deribit-data dvol --currency BTC --start 2024-01-01
    """
    cfg = DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    currency = currency.upper()
    start_date = start.replace(tzinfo=timezone.utc)
    end_date = (end or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)

    console.print(f"[bold]DVOL {currency}[/bold]")
    console.print(f"  Range: {start_date.date()} to {end_date.date()}")

    storage = ParquetStorage(cfg.catalog_path, cfg.compression, cfg.compression_level)
    manifest = ManifestManager(cfg.catalog_path)

    with DeribitFetcher(cfg) as fetcher:
        candles = fetcher.fetch_dvol(currency, start_date, end_date)

    if candles:
        file_path = storage.save_dvol(candles, currency)
        manifest.update_file(file_path)
        manifest.save()
        console.print(f"[green]Saved {len(candles)} DVOL candles[/green]")
    else:
        console.print("[yellow]No DVOL data found[/yellow]")


@main.command()
@click.option(
    "-c",
    "--currency",
    type=click.Choice(["BTC", "ETH"], case_sensitive=False),
    default=None,
    help="Currency to validate (default: all)",
)
@click.option("--catalog", type=click.Path(path_type=Path), default=None, help="Catalog path")
@click.option("--verify-checksums", is_flag=True, help="Verify SHA256 checksums")
def validate(
    currency: str | None,
    catalog: Path | None,
    verify_checksums: bool,
) -> None:
    """Validate data integrity.

    Checks data quality and optionally verifies checksums.
    """
    cfg = DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    currencies = [currency.upper()] if currency else cfg.currencies
    validator = DataValidator(cfg.validation)

    all_passed = True
    for curr in currencies:
        console.print(f"\n[bold]Validating {curr}[/bold]")

        result = validator.validate_trades(cfg.catalog_path, curr)

        # Show stats
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="dim")
        table.add_column("Value")
        table.add_row("Total rows", f"{result.stats.get('total_rows', 0):,}")
        table.add_row("Total files", str(result.stats.get("total_files", 0)))
        if result.stats.get("date_range"):
            table.add_row(
                "Date range", f"{result.stats['date_range'][0]} to {result.stats['date_range'][1]}"
            )
        console.print(table)

        # Show issues
        if result.issues:
            console.print(f"\n[yellow]Issues ({len(result.issues)}):[/yellow]")
            for issue in result.issues[:10]:  # Show first 10
                color = {
                    "critical": "red",
                    "high": "red",
                    "medium": "yellow",
                    "low": "dim",
                    "info": "dim",
                }.get(issue.severity.value, "white")
                console.print(
                    f"  [{color}]{issue.severity.value.upper()}[/{color}]: {issue.message}"
                )
            if len(result.issues) > 10:
                console.print(f"  ... and {len(result.issues) - 10} more")

        if result.passed:
            console.print("[green]PASSED[/green]")
        else:
            console.print("[red]FAILED[/red]")
            all_passed = False

    # Verify checksums
    if verify_checksums:
        console.print("\n[bold]Verifying checksums[/bold]")
        manifest = ManifestManager(cfg.catalog_path)
        passed, failed, failed_files = manifest.verify_all()
        console.print(f"  Passed: {passed}, Failed: {failed}")
        if failed_files:
            for f in failed_files[:5]:
                console.print(f"  [red]FAILED: {f}[/red]")

    if not all_passed:
        sys.exit(1)


@main.command()
@click.option(
    "-c",
    "--currency",
    required=True,
    type=click.Choice(["BTC", "ETH"], case_sensitive=False),
    help="Currency to reconcile",
)
@click.option("--catalog", type=click.Path(path_type=Path), default=None, help="Catalog path")
@click.option("--sample", type=int, default=None, help="Sample N random days (faster)")
@click.option("--full", is_flag=True, help="Full reconciliation (slow)")
def reconcile(
    currency: str,
    catalog: Path | None,
    sample: int | None,
    full: bool,
) -> None:
    """Reconcile local data against Deribit API.

    Verifies data completeness by comparing trade counts.

    Example:
        deribit-data reconcile --currency BTC --sample 10
    """
    cfg = DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    currency = currency.upper()

    console.print(f"[bold]Reconciling {currency}[/bold]")
    console.print(f"  Catalog: {cfg.catalog_path}")

    with DataReconciler(cfg, cfg.catalog_path) as reconciler:
        if full:
            console.print("  Mode: Full (this may take a while)")
            report = reconciler.quick_reconcile(currency, sample_days=1000)
        elif sample:
            console.print(f"  Mode: Sample ({sample} random days)")
            report = reconciler.quick_reconcile(currency, sample_days=sample)
        else:
            console.print("  Mode: Quick (10 random days)")
            report = reconciler.quick_reconcile(currency)

    # Show results
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("Days checked", str(report.total_days))
    table.add_row("Matched days", f"[green]{report.matched_days}[/green]")
    table.add_row(
        "Incomplete days",
        f"[yellow]{report.incomplete_days}[/yellow]" if report.incomplete_days else "0",
    )
    table.add_row(
        "Missing days", f"[red]{report.missing_days}[/red]" if report.missing_days else "0"
    )
    table.add_row("Local trades", f"{report.total_local_trades:,}")
    table.add_row("API trades", f"{report.total_api_trades:,}")
    table.add_row("Completeness", f"{report.completeness_pct:.1f}%")
    console.print(table)

    # Show incomplete dates
    incomplete = report.get_incomplete_dates()
    if incomplete:
        console.print(f"\n[yellow]Incomplete dates ({len(incomplete)}):[/yellow]")
        for date in incomplete[:10]:
            result = next(r for r in report.results if r.date == date)
            console.print(
                f"  {date.date()}: local={result.local_count:,}, "
                f"api={result.api_count or 'N/A'}, diff={result.difference:+,}"
            )
        if len(incomplete) > 10:
            console.print(f"  ... and {len(incomplete) - 10} more")

    # Show errors
    if report.errors:
        console.print(f"\n[red]Errors ({len(report.errors)}):[/red]")
        for err in report.errors[:5]:
            console.print(f"  {err}")

    # Final verdict
    if report.is_complete:
        console.print("\n[green]DATA COMPLETE[/green]")
    else:
        console.print("\n[yellow]DATA INCOMPLETE[/yellow]")
        sys.exit(1)


@main.command()
@click.option("--catalog", type=click.Path(path_type=Path), default=None, help="Catalog path")
def info(catalog: Path | None) -> None:
    """Show catalog information."""
    cfg = DeribitConfig.from_env()
    if catalog:
        cfg = cfg.model_copy(update={"catalog_path": catalog})

    console.print(f"[bold]Catalog: {cfg.catalog_path}[/bold]")

    if not cfg.catalog_path.exists():
        console.print("[yellow]Catalog not found[/yellow]")
        return

    storage = ParquetStorage(cfg.catalog_path, cfg.compression, cfg.compression_level)
    manifest = ManifestManager(cfg.catalog_path)

    table = Table(title="Data Summary")
    table.add_column("Currency")
    table.add_column("Files")
    table.add_column("Rows")
    table.add_column("Size")
    table.add_column("Date Range")

    for curr in cfg.currencies:
        stats = storage.get_stats(curr)
        if stats["file_count"] > 0:
            size_mb = stats["size_bytes"] / (1024 * 1024)
            date_range = ""
            if stats["date_range"]:
                date_range = f"{stats['date_range'][0].date()} to {stats['date_range'][1].date()}"
            table.add_row(
                curr,
                str(stats["file_count"]),
                f"{stats['row_count']:,}",
                f"{size_mb:.1f} MB",
                date_range,
            )

    console.print(table)

    # Manifest info
    console.print(f"\nManifest: {manifest.file_count} files, {manifest.total_rows:,} rows")


if __name__ == "__main__":
    main()
