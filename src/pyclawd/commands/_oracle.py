"""Shared machinery for the baseline oracles (``golden`` and ``benchmark``).

Both oracle CLIs do the same job over a different quantity: drive an auto-registered
pytest plugin across a marked suite, and manage a directory of JSON baseline stores.
Built one after the other, they had drifted into near-identical copies of the config
gate, node-id collection, the pytest argv, orphan detection, and the ``status`` /
``prune`` inventory. That common core lives here; each oracle module now supplies only
its config-specific parts — the pytest ``-o`` options, the baseline directory, and the
display nouns — via an :class:`OracleCtx`.

This is an **internal** helper module (``__all__ = []``): it adds nothing to the public
API surface, it is imported only by :mod:`pyclawd.commands.golden` and
:mod:`pyclawd.commands.benchmark` (and :func:`config_or_exit` by
:mod:`pyclawd.commands.api`).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import typer

from ..golden import GoldenStore, iter_baseline_files
from ..project import Project
from ..run import python_prefix, repo_env

#: Nothing here is public API — these are shared command-layer internals.
__all__: list[str] = []

#: pytest's "no tests collected" exit code — a valid empty result, not a failure.
NO_TESTS_COLLECTED = 5

_T = TypeVar("_T")


def config_or_exit(config: _T | None, name: str, hint: str) -> _T:
    """Return *config* if set, else exit ``2`` with a clear, actionable message.

    The shared gate behind ``pyclawd golden`` / ``benchmark`` / ``api`` for the
    exit-2 = not-configured contract, so the three oracles report an unconfigured
    feature identically instead of each hand-rolling the check.

    Args:
        config: The optional oracle config off the loaded project (e.g. ``project.golden``).
        name: The oracle's name, used in the message (e.g. ``"golden"``).
        hint: The remediation hint (e.g. ``"add GoldenConfig to .pyclawd/config.py"``).

    Returns:
        The config, guaranteed non-``None``.
    """
    if config is None:
        typer.secho(f"{name} not configured — {hint}", fg="red", err=True)
        raise typer.Exit(2)
    return config


def orphan_keys(store_keys: list[str], collected_nodeids: set[str]) -> list[str]:
    """Return baseline keys whose test case no longer exists among collected node ids.

    A snapshot key is the test node id's last ``::``-segment (e.g.
    ``test_minimize[sphere]``) with an optional ``::label`` suffix (e.g.
    ``test_minimize[sphere]::F``). A key is an **orphan** when its part *before* the
    ``::label`` is not among the last ``::``-segments of the collected node ids — i.e.
    the test that would record it is gone.

    Args:
        store_keys: All recorded baseline keys (across the relevant stores).
        collected_nodeids: Test node ids pytest currently collects for the marker.

    Returns:
        The orphaned keys, in input order.
    """
    live = {nodeid.rsplit("::", 1)[-1] for nodeid in collected_nodeids}
    return [key for key in store_keys if key.split("::", 1)[0] not in live]


def parse_nodeids(text: str) -> set[str]:
    """Parse test node ids from ``pytest --collect-only -q`` output (best-effort).

    Args:
        text: The captured stdout of a collect-only run.

    Returns:
        The set of node-id lines (those containing ``::``).
    """
    nodeids: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if "::" in line and not line.startswith(("<", "=", "no tests")):
            nodeids.add(line)
    return nodeids


def pytest_cmd(project: Project, opts: list[str], marker: str) -> list[str]:
    """Build the base pytest argv that selects a marked suite.

    The oracle plugins are auto-registered via their ``pytest11`` entry points, so
    they are **not** passed with ``-p`` (that would double-register and crash).

    Args:
        project: The loaded project (provides the env prefix + tests dir).
        opts: The oracle's ``-o key=value`` plugin overrides.
        marker: The marker selecting the oracle's tests.

    Returns:
        The argv ``<python> -m pytest <tests_dir> -o …=… -m <marker>``.
    """
    return [*python_prefix(project), "-m", "pytest", project.test.tests_dir, *opts, "-m", marker]


def collect_nodeids(project: Project, opts: list[str], marker: str) -> set[str] | None:
    """Collect a marked suite's node ids, or ``None`` if collection fails.

    Runs ``pytest --collect-only -q -m <marker>`` (the plugin is auto-registered) and
    parses the node-id lines. Returns ``None`` (so callers skip orphan detection
    gracefully) when pytest cannot be launched or exits with a real failure. pytest
    exit 5 ("no tests collected") is a valid empty result — e.g. every oracle test was
    removed — so it maps to an empty set, letting ``prune`` drop the now-orphaned
    baselines rather than refusing.

    Args:
        project: The loaded project (provides the env + root).
        opts: The oracle's ``-o key=value`` plugin overrides.
        marker: The marker selecting the oracle's tests.

    Returns:
        The collected node ids, or ``None`` on any collection failure.
    """
    cmd = [
        *python_prefix(project),
        "-m",
        "pytest",
        project.test.tests_dir,
        *opts,
        "--collect-only",
        "-q",
        "-m",
        marker,
    ]
    assert project.root is not None
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project.root),
            env=repo_env(project.root),
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode not in (0, NO_TESTS_COLLECTED):
        return None
    return parse_nodeids(proc.stdout)


@dataclass(frozen=True)
class OracleCtx:
    """Everything the shared ``status`` / ``prune`` need for one oracle.

    Attributes:
        project: The loaded project.
        label: The oracle's lowercase name (``"golden"`` / ``"benchmark"``) — used in
            command hints and the "the <label> suite" phrasing.
        title: The capitalised name for the inventory header (``"Golden"``).
        noun: The pluralisable item noun (``"snapshot"`` / ``"benchmark"``).
        baseline_dir: The absolute directory holding this oracle's baseline stores.
        opts: The oracle's ``-o key=value`` plugin overrides (for collection).
        marker: The marker selecting the oracle's tests.
        empty_suffix: Extra text appended inside the "no baselines" hint (e.g. the
            benchmark note that baselines are recorded per-machine).
        commit_hint: When set, ``prune`` tells the user to review ``git diff <hint>``
            (committed baselines); when ``None``, it names the local baseline dir
            instead (gitignored baselines that are never committed).
    """

    project: Project
    label: str
    title: str
    noun: str
    baseline_dir: Path
    opts: list[str]
    marker: str
    empty_suffix: str = ""
    commit_hint: str | None = None


def _plural(n: int, noun: str) -> str:
    """Render ``n`` copies of *noun* with a naive plural ``s``."""
    return f"{noun}{'s' if n != 1 else ''}"


def status(ctx: OracleCtx) -> None:
    """Show *ctx*'s baseline inventory (per file + grand total) and any orphans.

    Reads every baseline file under ``ctx.baseline_dir`` and prints its entry count,
    then a grand total. Best-effort: it also collects the live node ids and flags
    orphaned entries (a test that no longer exists); if collection fails it still
    prints the inventory. Exits ``0`` either way.
    """
    files = iter_baseline_files(ctx.baseline_dir)
    if not files:
        typer.secho(
            f"no baselines under {ctx.baseline_dir} (run `pyclawd {ctx.label} update`"
            f"{ctx.empty_suffix}).",
            fg="yellow",
        )
        raise typer.Exit(0)

    typer.secho(f"{ctx.title} baselines under {ctx.baseline_dir}:", bold=True)
    total = 0
    all_keys: list[str] = []
    for path in files:
        keys = GoldenStore(path).keys()
        total += len(keys)
        all_keys += keys
        typer.echo(f"  {path.name}  ({len(keys)} {_plural(len(keys), ctx.noun)})")
    typer.secho(f"  total: {total} {_plural(total, ctx.noun)}", fg="green")

    collected = collect_nodeids(ctx.project, ctx.opts, ctx.marker)
    if collected is None:
        typer.secho(
            f"  (orphan check skipped — could not collect the {ctx.label} suite)",
            fg="bright_black",
        )
        raise typer.Exit(0)

    orphans = orphan_keys(all_keys, collected)
    if orphans:
        typer.secho(
            f"\n  {len(orphans)} orphaned entr{'ies' if len(orphans) != 1 else 'y'}:", fg="yellow"
        )
        for key in orphans:
            typer.secho(f"    ⚠ {key}", fg="yellow")
        typer.secho(f"  run `pyclawd {ctx.label} prune` to remove them.", fg="bright_black")
    else:
        typer.secho("  no orphaned entries.", fg="bright_black")
    raise typer.Exit(0)


def prune(ctx: OracleCtx) -> None:
    """Remove *ctx*'s orphaned baseline entries (test gone) and delete emptied files.

    Collects the live node ids, drops every orphaned entry from its store, saves
    modified stores, and deletes any file that becomes empty. Every removal is printed
    — nothing is removed silently. If the suite cannot be collected, pruning is refused
    (exit ``1``) rather than guessing what is orphaned.
    """
    files = iter_baseline_files(ctx.baseline_dir)
    if not files:
        typer.secho(f"no baselines under {ctx.baseline_dir} — nothing to prune.", fg="yellow")
        raise typer.Exit(0)

    collected = collect_nodeids(ctx.project, ctx.opts, ctx.marker)
    if collected is None:
        typer.secho(
            f"prune refused — could not collect the {ctx.label} suite to determine orphans.",
            fg="red",
            err=True,
        )
        raise typer.Exit(1)

    removed = 0
    for path in files:
        store = GoldenStore(path)
        orphans = orphan_keys(store.keys(), collected)
        if not orphans:
            continue
        for key in orphans:
            store.remove(key)
            removed += 1
            typer.secho(f"  ✗ removed {path.name} :: {key}", fg="red")
        if store.is_empty():
            path.unlink()
            typer.secho(f"  ✗ deleted empty {path.name}", fg="red")
        else:
            store.save()

    if removed == 0:
        typer.secho("no orphaned entries — nothing pruned.", fg="green")
    elif ctx.commit_hint is not None:
        typer.secho(
            f"\npruned {removed} orphaned entr{'ies' if removed != 1 else 'y'} "
            f"— review `git diff {ctx.commit_hint}` and commit.",
            fg="yellow",
        )
    else:
        typer.secho(
            f"\npruned {removed} orphaned entr{'ies' if removed != 1 else 'y'} "
            f"from the local baselines under {ctx.baseline_dir}.",
            fg="yellow",
        )
    raise typer.Exit(0)
