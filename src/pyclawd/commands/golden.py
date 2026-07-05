"""Golden command group — ``pyclawd golden`` (the behavior-regression oracle).

The static gate (``pyclawd check``) proves code is *clean*; ``golden`` proves
behavior is *unchanged* by comparing each ``@pytest.mark.golden`` test's **return
value** against a committed snapshot baseline. The engine lives in
:mod:`pyclawd.golden` and the standalone, auto-registered pytest plugin
(:mod:`pyclawd.pytest_plugin`); this module is only the optional CLI wrapper that
drives them and translates :class:`~pyclawd.project.GoldenConfig` into the plugin's
pytest options. The plugin works in bare ``pytest`` with no pyclawd project at all;
these commands are a convenience for projects that *do* use pyclawd.

Subcommands (driven by :class:`~pyclawd.project.GoldenConfig`):

- ``pyclawd golden [-k EXPR]`` (default) — **compare**: run the golden suite as a
  gate, optionally narrowed to matching tests.
- ``pyclawd golden update [-k EXPR]`` — **bless**: re-record baselines (humans
  bless, agents only compare — never wire this into an autonomous self-gate).
- ``pyclawd golden status`` — inventory the committed baselines (+ orphan hint).
- ``pyclawd golden prune`` — drop orphaned baseline entries whose test is gone.
- ``pyclawd golden vendor <file>`` — copy the engine + plugin into a single
  self-contained file so a project runs golden with **zero pyclawd dependency**.

Exit-code contract (agent-native, deterministic):

- ``0`` — success.
- ``2`` — golden not configured for this project.
- otherwise — pytest's own exit code (snapshot drift, collection error, …).
"""

from __future__ import annotations

from pathlib import Path

import typer

from .. import run
from ..project import GoldenConfig, Project
from . import _oracle


def _golden_or_exit(project: Project) -> GoldenConfig:
    """Return ``project.golden`` or exit ``2`` (see :func:`_oracle.config_or_exit`)."""
    return _oracle.config_or_exit(
        project.golden, "golden", "add GoldenConfig to .pyclawd/config.py"
    )


def _golden_opts(project: Project, golden: GoldenConfig) -> list[str]:
    """Translate :class:`GoldenConfig` into the plugin's pytest ``-o`` overrides.

    Feeds the auto-registered plugin the project's baseline dir / marker /
    tolerances, so a pyclawd project drives golden from ``.pyclawd/config.py`` while
    the plugin itself stays config-via-pytest-ini for bare-pytest projects.

    ``golden_dir`` is passed as an **absolute** path resolved against the repo
    root, so the plugin records/reads baselines in exactly the directory the CLI's
    ``status`` / ``prune`` read (``project.path(baseline_dir)``). The plugin
    otherwise resolves a *relative* ``golden_dir`` against pytest's rootdir, which
    diverges from the repo root whenever pytest picks a nested rootdir (e.g. a
    ``tests/pytest.ini``) — the doubled ``tests/tests/golden`` the dogfood exposed.

    Args:
        project: The loaded project (provides the repo root for path resolution).
        golden: The golden configuration.

    Returns:
        A list of ``-o key=value`` argv pairs.
    """
    return [
        "-o",
        f"golden_dir={project.path(golden.baseline_dir)}",
        "-o",
        f"golden_marker={golden.marker}",
        "-o",
        f"golden_precision={golden.precision}",
        "-o",
        f"golden_rtol={golden.rtol}",
        "-o",
        f"golden_atol={golden.atol}",
    ]


def _pytest_cmd(project: Project, golden: GoldenConfig) -> list[str]:
    """Build the base pytest argv selecting the golden suite (see :func:`_oracle.pytest_cmd`)."""
    return _oracle.pytest_cmd(project, _golden_opts(project, golden), golden.marker)


def _golden_ctx(project: Project, golden: GoldenConfig) -> _oracle.OracleCtx:
    """Bundle the golden-specific bits the shared ``status`` / ``prune`` need."""
    return _oracle.OracleCtx(
        project=project,
        label="golden",
        title="Golden",
        noun="snapshot",
        baseline_dir=project.path(golden.baseline_dir),
        opts=_golden_opts(project, golden),
        marker=golden.marker,
        commit_hint=golden.baseline_dir,
    )


# --------------------------------------------------------------------------- #
# Subcommands.
# --------------------------------------------------------------------------- #


def _compare(expr: str | None = None) -> None:
    """Run the golden suite as a gate (the default ``pyclawd golden`` action).

    Args:
        expr: Optional pytest ``-k`` keyword expression to select a subset of
            golden tests to compare.
    """
    project = run.load_project_or_exit()
    golden = _golden_or_exit(project)
    cmd = _pytest_cmd(project, golden)
    if expr:
        cmd += ["-k", expr]
    raise typer.Exit(run.run(cmd, project.root))


def update(
    expr: str = typer.Option(
        None,
        "-k",
        metavar="EXPR",
        help="Only bless tests matching this keyword expression (pytest -k).",
    ),
) -> None:
    """Bless baselines — re-record the golden suite (humans bless; agents compare).

    Passes ``--golden-update`` so the plugin records fresh baselines instead of
    gating. With ``-k EXPR`` only the matched cases are re-blessed, leaving the rest
    untouched. After it runs, **review** ``git diff`` of the baseline dir and commit
    deliberately — never auto-bless in an autonomous loop.
    """
    project = run.load_project_or_exit()
    golden = _golden_or_exit(project)
    cmd = [*_pytest_cmd(project, golden), "--golden-update"]
    if expr:
        cmd += ["-k", expr]
    code = run.run(cmd, project.root)
    typer.secho(
        f"\nReview `git diff {golden.baseline_dir}` and commit the blessed baselines.",
        fg="yellow",
    )
    raise typer.Exit(code)


def status() -> None:
    """Show the committed-baseline inventory (per file + grand total) and orphans."""
    project = run.load_project_or_exit()
    golden = _golden_or_exit(project)
    _oracle.status(_golden_ctx(project, golden))


def prune() -> None:
    """Remove orphaned baseline entries (test gone) and delete emptied files."""
    project = run.load_project_or_exit()
    golden = _golden_or_exit(project)
    _oracle.prune(_golden_ctx(project, golden))


def _strip_preamble(src: str, *, drop_future: bool = False, drop_module: str | None = None) -> str:
    """Return *src* with its module docstring (and optionally ``__future__`` / one import) removed.

    Used to splice the engine and plugin into one module: only the merged file's
    leading docstring and single ``from __future__`` survive, and the plugin's
    ``from pyclawd.golden import …`` is dropped because the engine is now inline.

    Args:
        src: Python source.
        drop_future: Also remove the ``from __future__ import annotations`` line.
        drop_module: Also remove a ``from <drop_module> import …`` line.

    Returns:
        The source with those leading lines removed.
    """
    import ast

    tree = ast.parse(src)
    drop: set[int] = set()
    body = tree.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        drop.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    for node in body:
        if not isinstance(node, ast.ImportFrom):
            continue
        is_future = drop_future and node.module == "__future__"
        is_drop_mod = drop_module is not None and node.module == drop_module
        if is_future or is_drop_mod:
            drop.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return "".join(line for i, line in enumerate(src.splitlines(keepends=True), 1) if i not in drop)


def vendor(
    target: str = typer.Argument(
        ...,
        help="File to vendor the self-contained golden plugin into, e.g. tests/golden_plugin.py.",
    ),
) -> None:
    """Vendor golden as a single self-contained file — zero pyclawd dependency.

    golden's engine (``pyclawd.golden``) is stdlib-only (numpy lazy/optional) and the
    plugin imports only the engine, so the two splice into **one module**. After
    vendoring, a framework runs ``@pytest.mark.golden`` return-capture tests with
    **its own pytest** — pyclawd is never imported, installed, or a dependency.
    Commit the file + your baselines; re-run this to update it.

    Writes one ``<target>.py`` (engine + plugin spliced together) and prints the one
    ``conftest.py`` line to register it.
    """
    import pyclawd

    pkg_root = Path(__file__).resolve().parent.parent  # the installed src/pyclawd/
    version = pyclawd.__version__

    dest = Path(target)
    if dest.suffix != ".py":
        dest = dest.with_suffix(".py")
    dest.parent.mkdir(parents=True, exist_ok=True)
    modpath = ".".join(dest.with_suffix("").parts)

    engine = (pkg_root / "golden.py").read_text()
    plugin = (pkg_root / "pytest_plugin.py").read_text()
    docstring = (
        f'"""Vendored golden (engine + pytest plugin) from pyclawd {version} — do not edit.\n\n'
        f"Self-contained, dependency-free. Register it in your top-level conftest.py with\n"
        f'``pytest_plugins = ["{modpath}"]``, then write ``@pytest.mark.golden`` tests that\n'
        f"``return`` a value. Regenerate with ``pyclawd golden vendor {target}``.\n"
        f'"""\n'
    )
    merged = (
        docstring
        + _strip_preamble(engine)
        + "\n\n# === pytest plugin (spliced from pyclawd.pytest_plugin) ===\n\n"
        + _strip_preamble(plugin, drop_future=True, drop_module="pyclawd.golden")
    )
    dest.write_text(merged)

    typer.secho(
        f"✓ vendored golden into {dest} (one file — dependency-free, no pyclawd)", fg="green"
    )
    typer.echo("\nRegister it in your top-level conftest.py:")
    typer.secho(f'    pytest_plugins = ["{modpath}"]', fg="cyan")
    typer.echo("\nWrite @pytest.mark.golden tests that `return` a value, then bless with:")
    typer.secho("    pytest -m golden --golden-update", fg="cyan")
    typer.secho(
        "\nNote: only vendor in projects that do NOT install pyclawd — running both the "
        "vendored plugin and pyclawd's entry-point plugin double-registers and errors.",
        fg="yellow",
    )
    raise typer.Exit(0)


def register(app: typer.Typer) -> None:
    """Attach the ``golden`` command group to *app*.

    The default invocation (``pyclawd golden``) compares; ``update`` / ``status`` /
    ``prune`` / ``vendor`` are subcommands. Always registered — each self-reports and
    exits ``2`` when the loaded project does not configure golden (``vendor`` needs no
    project).
    """
    golden_app = typer.Typer(
        help="Behavior-regression oracle: compare observable outputs to committed baselines.",
    )

    @golden_app.callback(invoke_without_command=True)
    def _default(
        ctx: typer.Context,
        expr: str = typer.Option(
            None,
            "-k",
            metavar="EXPR",
            help="Only compare golden tests matching this keyword expression (pytest -k).",
        ),
    ) -> None:
        """Compare the golden suite against committed baselines (the default action).

        ``pyclawd golden -k <expr>`` narrows the gate to matching golden tests.
        """
        if ctx.invoked_subcommand is not None:
            return
        _compare(expr)

    golden_app.command()(update)
    golden_app.command()(status)
    golden_app.command()(prune)
    golden_app.command()(vendor)
    app.add_typer(golden_app, name="golden")
