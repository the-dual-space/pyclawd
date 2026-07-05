"""Build commands: ``compile``, ``dist``, ``clean``.

Each is driven by a field on the loaded
:class:`~pyclawd.project.BuildConfig` (reached via ``project.build``). When
``project.build`` is unset, or the relevant field is empty, the project simply has
no such step, so the command says so and exits 2 rather than running an empty
command.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from .. import run


def _under_root(path: Path, root: Path) -> bool:
    """True if *path* resolves to a location inside *root* (containment guard).

    Stops ``pyclawd clean`` from ever ``rmtree``-ing outside the repo: a target
    like ``../victim`` or an absolute path resolves outside *root* and is refused.
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


#: Exit code for a command invoked on a project that has not configured that step
#: (the 0/2 contract: 2 = "command exists but the feature is not configured").
_UNCONFIGURED = 2


def _build_step(cmd_attr: str, label: str) -> None:
    """Run a configured build command (``project.build.<cmd_attr>``), or exit 2 if unset.

    Args:
        cmd_attr: The :class:`~pyclawd.project.BuildConfig` field holding the argv
            (``"compile_cmd"`` / ``"dist_cmd"``).
        label: The command name used in the "not configured" message.
    """
    project = run.load_project_or_exit()
    cmd = getattr(project.build, cmd_attr, None) if project.build is not None else None
    if not cmd:
        typer.secho(
            f"{label}: not configured for this project (project.build.{cmd_attr} is empty).",
            fg="yellow",
        )
        raise typer.Exit(_UNCONFIGURED)
    raise typer.Exit(run.python(cmd))


def compile() -> None:
    """Build the project's extensions in place (``project.build.compile_cmd``)."""
    _build_step("compile_cmd", "compile")


def dist() -> None:
    """Build a source distribution (``project.build.dist_cmd``)."""
    _build_step("dist_cmd", "dist")


def clean(
    ext: bool = typer.Option(False, "--ext", help="Also remove compiled extension artifacts."),
) -> None:
    """Remove the project's build artifacts (and with --ext, compiled extensions)."""
    project = run.load_project_or_exit()
    assert project.root is not None  # load_project_or_exit always sets root
    build = project.build
    removed: list[str] = []

    clean_targets = build.clean_targets if build is not None else []
    for name in clean_targets:
        p = project.path(name)
        if not _under_root(p, project.root):
            typer.secho(
                f"skip: clean target {name!r} resolves outside the repo root — not removing.",
                fg="yellow",
                err=True,
            )
            continue
        if p.exists():
            shutil.rmtree(p)
            removed.append(name)

    if ext:
        if build is None or not build.clean_ext_dir:
            typer.secho(
                "clean --ext: not configured (project.build.clean_ext_dir is empty).",
                fg="yellow",
            )
        else:
            compiled = project.path(build.clean_ext_dir)
            if not _under_root(compiled, project.root):
                typer.secho(
                    f"skip: clean --ext dir {build.clean_ext_dir!r} resolves outside the "
                    "repo root — not removing.",
                    fg="yellow",
                    err=True,
                )
            else:
                for pattern in build.clean_ext_globs:
                    for f in compiled.glob(pattern):
                        if not _under_root(f, project.root):
                            continue
                        f.unlink()
                        removed.append(str(f.relative_to(project.root)))

    typer.echo("removed: " + (", ".join(removed) if removed else "nothing to clean"))


def register(app: typer.Typer) -> None:
    """Attach the build commands to *app*."""
    app.command(name="compile")(compile)
    app.command()(dist)
    app.command()(clean)
