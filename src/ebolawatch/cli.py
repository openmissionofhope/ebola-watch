"""Command-line interface: ``ebolawatch --help``."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from .config import get_settings

app = typer.Typer(help="Ebola Watch — epidemiological intelligence (not a medical service).", no_args_is_help=True)


def _setup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    get_settings().validate_for_production()


@app.command("init-db")
def init_db(create_tables: bool = typer.Option(False, help="Create tables directly instead of running Alembic migrations")) -> None:
    """Create or migrate the database schema and seed reference data."""
    _setup()
    from .db.session import create_all, session_scope
    from .pipeline.seed import seed_all

    if create_tables:
        create_all()
    else:
        from alembic import command
        from alembic.config import Config

        candidates = [Path(__file__).resolve().parents[2] / "alembic.ini", Path.cwd() / "alembic.ini", Path("/app/alembic.ini")]
        ini = next((c for c in candidates if c.exists()), None)
        if ini is None:
            raise typer.BadParameter("alembic.ini not found; run from the project directory or use --create-tables")
        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(ini.parent / "migrations"))
        cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
        from sqlalchemy import inspect

        from .db.session import get_engine

        tables = set(inspect(get_engine()).get_table_names())
        if "regions" in tables and "alembic_version" not in tables:
            # schema was created directly (development server start-up); record it as current
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")
    with session_scope() as s:
        typer.echo(json.dumps(seed_all(s)))


@app.command()
def ingest(source: list[str] = typer.Option(None, "--source", "-s", help="Only these source keys")) -> None:
    """Run data-source connectors."""
    _setup()
    from .db.session import session_scope
    from .pipeline.ingest import ingest_all
    from .pipeline.seed import seed_sources

    with session_scope() as s:
        seed_sources(s)
        for r in ingest_all(s, only=source or None):
            typer.echo(f"{r.source_key:22} {r.status:26} new={r.items_new:<5} {r.message or ''}")


@app.command()
def analyze(sims: int = typer.Option(2000, help="Simulations per scenario"),
            no_backtest: bool = typer.Option(False, help="Skip backtesting")) -> None:
    """Signals, clustering, models, severity, backtests and reports."""
    _setup()
    from .db.session import session_scope
    from .pipeline.run import analyze as run_analyze

    with session_scope() as s:
        typer.echo(json.dumps(run_analyze(s, n_sims=sims, backtests=not no_backtest)))


@app.command("run")
def run_pipeline(skip_ingest: bool = False,
                 due_only: bool = typer.Option(False, help="Skip sources that are not due (reference data, persistently failing sources)")) -> None:
    """Full pipeline: seed, ingest, analyze, retention."""
    _setup()
    from .pipeline.run import run_all

    typer.echo(json.dumps(run_all(skip_ingest=skip_ingest, due_only=due_only), indent=1, default=str))


@app.command()
def scheduler() -> None:
    """Run the pipeline on the configured schedule (for the worker container)."""
    _setup()
    from .pipeline.run import scheduler as loop

    loop()


@app.command()
def report(kind: str = typer.Argument("daily"), region: list[str] = typer.Option(None, "--region", "-r")) -> None:
    """Generate a situation report and print its Markdown."""
    _setup()
    from .db.session import session_scope
    from .reports.generate import generate

    with session_scope() as s:
        rep = generate(s, kind, scope=region or None)
        typer.echo(rep.content_md)


@app.command("import-observations")
def import_observations(path: Path, citation: str = typer.Option(..., help="Citation of the official source transcribed"),
                        reviewer: str = typer.Option(None, help="Reviewer name: rows are stored as verified")) -> None:
    """Import official figures transcribed from a situation report (CSV)."""
    _setup()
    from sqlalchemy import select

    from .db.models import Source
    from .db.session import session_scope
    from .pipeline.ingest import store_item
    from .review.queue import audit
    from .sources.manual import parse_manual_csv

    item = parse_manual_csv(path.read_text(), document_id=f"manual:{path.name}", citation=citation)
    item.meta["reviewer"] = reviewer
    with session_scope() as s:
        src = s.scalar(select(Source).where(Source.key == "manual"))
        _, _, n = store_item(s, src, item, get_settings())
        audit(s, reviewer or "cli", "manual_import", "source", "manual", {"count": n})
        typer.echo(f"imported {n} observations ({'verified' if reviewer else 'pending review'})")


@app.command("create-api-key")
def create_api_key(name: str, role: str = typer.Option("reviewer", help="analyst | reviewer | admin")) -> None:
    """Create an API key (shown once)."""
    _setup()
    from .api.security import create_key
    from .db.session import session_scope

    with session_scope() as s:
        key = create_key(s, name, role)
    typer.echo(key)


@app.command("load-synthetic-demo")
def load_synthetic_demo(i_understand_this_is_synthetic: bool = typer.Option(False, "--i-understand-this-is-synthetic")) -> None:
    """Load a clearly-labelled synthetic outbreak (fictional region) for demonstrations. Refused in production."""
    _setup()
    s = get_settings()
    if s.is_production or not i_understand_this_is_synthetic:
        raise typer.BadParameter("synthetic data are only loaded outside production and with --i-understand-this-is-synthetic")
    from .db.session import session_scope
    from .demo import load_demo

    with session_scope() as sess:
        typer.echo(json.dumps(load_demo(sess)))


@app.command()
def retention() -> None:
    """Apply data-retention limits."""
    _setup()
    from .db.session import session_scope
    from .pipeline.run import apply_retention

    with session_scope() as s:
        typer.echo(json.dumps(apply_retention(s)))


@app.command("export-static")
def export_static(out: Path = typer.Option(..., help="Output directory (created; replaced if it holds a previous export)"),
                  frontend_dist: Path = typer.Option(None, help="Dashboard built with VITE_STATIC=1; omit to export data only"),
                  cname: str = typer.Option(None, help="Custom domain to write to CNAME (GitHub Pages)")) -> None:
    """Write a static snapshot of the public API and dashboard (hosting without a server)."""
    _setup()
    from .publish.static import export_static as run_export

    typer.echo(json.dumps(run_export(out, frontend_dist, cname)))


github_app = typer.Typer(help="Human review through GitHub issues (deployments without a server).", no_args_is_help=True)
app.add_typer(github_app, name="github")


@github_app.command("apply")
def github_apply(repo: str = typer.Option(..., help="Operations repository (owner/name)")) -> None:
    """Apply decisions and authorised requests recorded on GitHub issues (database only)."""
    _setup()
    from .db.session import session_scope
    from .publish.github_ops import GitHub, apply_from_github

    gh = GitHub.from_env(repo)
    with session_scope() as s:
        typer.echo(json.dumps(apply_from_github(s, gh)))


@github_app.command("sync")
def github_sync(repo: str = typer.Option(..., help="Operations repository (owner/name)"),
                max_new: int = typer.Option(25, help="Maximum new issues per run")) -> None:
    """Acknowledge decisions, open issues for new review items, delete expired excerpts. Run after the state is saved."""
    _setup()
    from .db.session import session_scope
    from .publish.github_ops import GitHub, sync_to_github

    gh = GitHub.from_env(repo)
    with session_scope() as s:
        typer.echo(json.dumps(sync_to_github(s, gh, max_new=max_new)))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the API and dashboard."""
    import uvicorn

    _setup()
    uvicorn.run("ebolawatch.api.app:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    app()
