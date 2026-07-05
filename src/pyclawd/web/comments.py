"""Persistent, authored, threaded review comments behind the dashboard.

Review comments used to live only in the browser's ``localStorage`` — ephemeral,
single-author, and invisible to any agent. This module gives them a durable home so
they can become a *conversation*: every comment carries an :attr:`Comment.author`
(``human`` or ``agent``) and an optional :attr:`Comment.parent` linking a reply to
the comment it answers. That is the substrate the AI-reply loop needs — an agent can
read a human's comment and write its answer back into the same thread.

Like :mod:`pyclawd.web.registry`, state is plain JSON via the standard library (no
new dependency on pyclawd's core) — one file per project under a base directory,
which the app derives from the registry's config location so tests inherit the same
``tmp_path`` isolation. Comments are anchored to ``file``/``line``/``side`` so they
survive independently of whichever base↔target comparison was on screen when they
were written.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from .storage import read_json, write_json

#: Allowed comment authors — a human reviewer, or an AI agent replying in-thread.
Author = str  # one of {"human", "agent"}

#: Allowed thread states; ``open`` needs attention, ``resolved`` is done.
Status = str  # one of {"open", "resolved"}


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string (stored on each comment)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Comment:
    """One review comment — a root note on a line, or a reply in its thread.

    Attributes:
        id: Stable unique id (assigned on creation).
        file: Repo-relative path the comment is anchored to.
        line: 1-based line number on the anchored ``side``.
        side: Which diff side the line is on (``old`` or ``new``).
        code: The line's text at authoring time (context that survives later edits).
        body: The comment's Markdown text.
        author: Who wrote it — ``human`` or ``agent``.
        parent: Id of the comment this replies to, or ``None`` for a root comment.
        status: ``open`` or ``resolved`` (only meaningful on a root comment).
        created_at: ISO-8601 UTC timestamp of creation.
    """

    id: str
    file: str
    line: int
    side: str
    code: str
    body: str
    author: Author = "human"
    parent: str | None = None
    status: Status = "open"
    created_at: str = field(default_factory=_now)


def _safe_name(project: str) -> str:
    """Turn a project name into a filesystem-safe JSON filename stem."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", project) or "_"


@dataclass(frozen=True)
class CommentStore:
    """Durable per-project comment store, one JSON file per project under *base_dir*."""

    base_dir: Path

    def _path(self, project: str) -> Path:
        """Return the JSON file backing *project*'s comments."""
        return self.base_dir / f"{_safe_name(project)}.json"

    def _load(self, project: str) -> list[Comment]:
        """Return *project*'s stored comments (empty if the file is absent/corrupt)."""
        raw: list = read_json(self._path(project), [])
        out: list[Comment] = []
        for item in raw:
            if isinstance(item, dict) and "id" in item:
                fields = {k: v for k, v in item.items() if k in Comment.__dataclass_fields__}
                out.append(Comment(**fields))
        return out

    def _save(self, project: str, comments: list[Comment]) -> None:
        """Persist *comments* for *project*, creating the base directory as needed."""
        write_json(self._path(project), [asdict(c) for c in comments])

    # -- reads ------------------------------------------------------------- #

    def list(self, project: str) -> list[Comment]:
        """Return every comment for *project*, oldest first."""
        return self._load(project)

    def get(self, project: str, comment_id: str) -> Comment | None:
        """Return one comment by id, or ``None`` if it does not exist."""
        return next((c for c in self._load(project) if c.id == comment_id), None)

    # -- writes ------------------------------------------------------------ #

    def add(
        self,
        project: str,
        *,
        file: str,
        line: int,
        side: str,
        code: str,
        body: str,
        author: Author = "human",
        parent: str | None = None,
    ) -> Comment:
        """Create and persist a new comment, returning it with its assigned id.

        A reply (``parent`` set) inherits its anchor (file/line/side/code) from the
        parent so the thread stays pinned to one line even if the caller omits it.
        """
        comments = self._load(project)
        if parent:
            root = next((c for c in comments if c.id == parent), None)
            if root is not None:
                file, line, side, code = root.file, root.line, root.side, root.code
        comment = Comment(
            id=uuid.uuid4().hex[:12],
            file=file,
            line=line,
            side=side,
            code=code,
            body=body,
            author=author,
            parent=parent,
        )
        comments.append(comment)
        self._save(project, comments)
        return comment

    def edit(
        self,
        project: str,
        comment_id: str,
        *,
        body: str | None = None,
        status: Status | None = None,
    ) -> Comment | None:
        """Update a comment's *body* and/or *status*; return it, or ``None`` if absent."""
        comments = self._load(project)
        updated: Comment | None = None
        for i, c in enumerate(comments):
            if c.id == comment_id:
                updated = replace(
                    c,
                    body=body if body is not None else c.body,
                    status=status if status is not None else c.status,
                )
                comments[i] = updated
                break
        if updated is not None:
            self._save(project, comments)
        return updated

    def delete(self, project: str, comment_id: str) -> bool:
        """Delete a comment *and* its replies; return ``True`` if anything was removed."""
        comments = self._load(project)
        kept = [c for c in comments if c.id != comment_id and c.parent != comment_id]
        if len(kept) == len(comments):
            return False
        self._save(project, kept)
        return True

    def clear(self, project: str) -> None:
        """Remove all comments for *project* (drops the backing file)."""
        self._path(project).unlink(missing_ok=True)
