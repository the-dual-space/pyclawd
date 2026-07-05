"""Benchmark command group — ``pyclawd benchmark`` (the performance-regression oracle).

golden proves an observable *value* is unchanged; ``benchmark`` proves the code did not get
*slower*. It times each ``@pytest.mark.benchmark`` test (best-of-N) and gates it against a
baseline. The engine lives in :mod:`pyclawd.benchmark` and the standalone,
auto-registered plugin :mod:`pyclawd.benchmark_plugin`; this module is the CLI wrapper that
translates :class:`~pyclawd.project.BenchmarkConfig` into the plugin's pytest options.

Baselines are **never committed** — a time is hardware-specific, so they live under the
project's gitignored ``work_dir`` (see :func:`_baseline_dir`) and ``benchmark`` compares
against *your* last blessed run on *this* machine.

Subcommands (driven by :class:`~pyclawd.project.BenchmarkConfig`):

- ``pyclawd benchmark [-k EXPR]`` (default) — **compare**: run the benchmark suite as a gate.
- ``pyclawd benchmark update [-k EXPR]`` — **bless**: re-record local baselines (agents compare).
- ``pyclawd benchmark status`` — inventory the local baselines (+ orphan hint).
- ``pyclawd benchmark prune`` — drop orphaned baseline entries whose test is gone.

Exit-code contract (agent-native, deterministic):

- ``0`` — success.
- ``2`` — benchmark not configured for this project.
- otherwise — pytest's own exit code (timing regression, collection error, …).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import typer

from .. import run
from ..logs import work_root
from ..project import BenchmarkConfig, Project
from . import _oracle


def _baseline_dir(project: Project) -> Path:
    """The gitignored, per-machine directory holding this project's benchmark baselines.

    A benchmark baseline is a *time*, which is hardware-specific, so it is **never
    committed**: it lives under the project's ``work_dir`` (the same transient scratch
    root as the test logs), namespaced by a hash of the repo root so baselines from
    different checkouts never collide.

    Args:
        project: The loaded project (resolves ``work_dir`` and the repo root).

    Returns:
        ``<work_root>/benchmark/<roothash>``.
    """
    root = project.root or Path.cwd()
    digest = hashlib.sha1(str(root).encode()).hexdigest()[:10]
    return work_root(project) / "benchmark" / digest


def _bench_or_exit(project: Project) -> BenchmarkConfig:
    """Return ``project.benchmark`` or exit ``2`` (see :func:`_oracle.config_or_exit`)."""
    return _oracle.config_or_exit(
        project.benchmark, "benchmark", "add BenchmarkConfig to .pyclawd/config.py"
    )


def _bench_opts(project: Project, benchmark: BenchmarkConfig) -> list[str]:
    """Translate :class:`BenchmarkConfig` into the plugin's pytest ``-o`` overrides.

    ``benchmark_dir`` is the **absolute**, gitignored work-dir location (see
    :func:`_baseline_dir`), so the plugin records/reads baselines in exactly the
    directory ``status`` / ``prune`` read — and never inside the committed tree.

    Args:
        project: The loaded project (provides the work dir + repo root).
        benchmark: The benchmark configuration.

    Returns:
        A list of ``-o key=value`` argv pairs.
    """
    return [
        "-o",
        f"benchmark_dir={_baseline_dir(project)}",
        "-o",
        f"benchmark_marker={benchmark.marker}",
        "-o",
        f"benchmark_warmup={benchmark.warmup}",
        "-o",
        f"benchmark_repeat={benchmark.repeat}",
        "-o",
        f"benchmark_rtol={benchmark.rtol}",
    ]


def _pytest_cmd(project: Project, benchmark: BenchmarkConfig) -> list[str]:
    """Build the base pytest argv selecting the benchmark suite (see :func:`_oracle.pytest_cmd`)."""
    return _oracle.pytest_cmd(project, _bench_opts(project, benchmark), benchmark.marker)


def _bench_ctx(project: Project, benchmark: BenchmarkConfig) -> _oracle.OracleCtx:
    """Bundle the benchmark-specific bits the shared ``status`` / ``prune`` need."""
    return _oracle.OracleCtx(
        project=project,
        label="benchmark",
        title="Benchmark",
        noun="benchmark",
        baseline_dir=_baseline_dir(project),
        opts=_bench_opts(project, benchmark),
        marker=benchmark.marker,
        empty_suffix=" on this machine to record them",
        commit_hint=None,
    )


def _compare(expr: str | None = None) -> None:
    """Run the benchmark suite as a gate (the default ``pyclawd benchmark`` action)."""
    project = run.load_project_or_exit()
    benchmark = _bench_or_exit(project)
    cmd = _pytest_cmd(project, benchmark)
    if expr:
        cmd += ["-k", expr]
    code = run.run(cmd, project.root)
    # pytest exit 5 = "no tests collected" — a project can configure benchmark before
    # writing any @pytest.mark.benchmark tests. That is not a gate failure; report it
    # cleanly instead of surfacing pytest's bare exit 5.
    no_tests_collected = 5
    if code == no_tests_collected:
        typer.secho("no benchmark tests collected — nothing to gate.", fg="yellow")
        raise typer.Exit(0)
    raise typer.Exit(code)


def update(
    expr: str = typer.Option(
        None,
        "-k",
        metavar="EXPR",
        help="Only bless benchmark tests matching this keyword expression (pytest -k).",
    ),
) -> None:
    """Bless baselines — re-record measured timings on THIS machine (agents only compare).

    Passes ``--benchmark-update`` so the plugin records fresh timings instead of gating.
    Baselines are hardware-specific and **gitignored** — bless them on a quiet machine;
    there is nothing to commit. Never wire this into an autonomous loop.
    """
    project = run.load_project_or_exit()
    benchmark = _bench_or_exit(project)
    cmd = [*_pytest_cmd(project, benchmark), "--benchmark-update"]
    if expr:
        cmd += ["-k", expr]
    code = run.run(cmd, project.root)
    typer.secho(
        f"\nRecorded local benchmark baselines under {_baseline_dir(project)} "
        "(gitignored, machine-specific — nothing to commit).",
        fg="yellow",
    )
    raise typer.Exit(code)


def status() -> None:
    """Show the local-baseline inventory (per file + grand total) and orphans."""
    project = run.load_project_or_exit()
    benchmark = _bench_or_exit(project)
    _oracle.status(_bench_ctx(project, benchmark))


def prune() -> None:
    """Remove orphaned baseline entries (test gone) and delete emptied files."""
    project = run.load_project_or_exit()
    benchmark = _bench_or_exit(project)
    _oracle.prune(_bench_ctx(project, benchmark))


def register(app: typer.Typer) -> None:
    """Attach the ``benchmark`` command group to *app*.

    The default invocation (``pyclawd benchmark``) compares; ``update`` / ``status`` /
    ``prune`` are subcommands. Always registered — each self-reports and exits ``2``
    when the loaded project does not configure benchmark.
    """
    bench_app = typer.Typer(
        help="Performance-regression oracle: prove the code did not get slower.",
    )

    @bench_app.callback(invoke_without_command=True)
    def _default(
        ctx: typer.Context,
        expr: str = typer.Option(
            None,
            "-k",
            metavar="EXPR",
            help="Only compare benchmark tests matching this keyword expression (pytest -k).",
        ),
    ) -> None:
        """Compare the benchmark suite against the local baselines (the default action)."""
        if ctx.invoked_subcommand is not None:
            return
        _compare(expr)

    bench_app.command()(update)
    bench_app.command()(status)
    bench_app.command()(prune)
    app.add_typer(bench_app, name="benchmark")
