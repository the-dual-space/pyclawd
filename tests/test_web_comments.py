"""Unit tests for the persistent review-comment store (:mod:`pyclawd.web.comments`).

Pure-logic tests: the store is bound to a base directory, so these point it at
``tmp_path``. No network, no FastAPI — just create/reply/edit/delete round-trips and
the JSON persistence + author/thread invariants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyclawd.web.comments import CommentStore


@pytest.fixture
def store(tmp_path: Path) -> CommentStore:
    """A comment store backed by a scratch directory under *tmp_path*."""
    return CommentStore(base_dir=tmp_path / "comments")


def _root(store: CommentStore, project: str = "demo", body: str = "why?"):
    """Add and return a root human comment on ``a.py`` line 3 (new side)."""
    return store.add(project, file="a.py", line=3, side="new", code="x = 1", body=body)


def test_add_assigns_id_author_and_persists(store: CommentStore, tmp_path: Path) -> None:
    c = _root(store)
    assert c.id and c.author == "human" and c.parent is None and c.status == "open"
    assert c.created_at  # stamped
    # A fresh store over the same dir sees it (persisted to disk).
    reloaded = CommentStore(base_dir=tmp_path / "comments").list("demo")
    assert [x.id for x in reloaded] == [c.id]


def test_reply_inherits_anchor_and_links_parent(store: CommentStore) -> None:
    root = _root(store)
    reply = store.add(
        "demo", file="", line=0, side="new", code="", body="because", author="agent", parent=root.id
    )
    assert reply.author == "agent" and reply.parent == root.id
    # Anchor copied from the parent even though the caller passed blanks.
    assert (reply.file, reply.line, reply.side, reply.code) == ("a.py", 3, "new", "x = 1")


def test_edit_body_and_status(store: CommentStore) -> None:
    c = _root(store)
    assert store.edit("demo", c.id, body="clearer").body == "clearer"
    assert store.edit("demo", c.id, status="resolved").status == "resolved"
    assert store.edit("demo", "nope", body="x") is None


def test_delete_removes_comment_and_its_replies(store: CommentStore) -> None:
    root = _root(store)
    store.add("demo", file="a.py", line=3, side="new", code="x = 1", body="r", parent=root.id)
    other = store.add("demo", file="b.py", line=1, side="new", code="y", body="keep")
    assert store.delete("demo", root.id) is True
    remaining = store.list("demo")
    assert [c.id for c in remaining] == [other.id]  # reply went with the root
    assert store.delete("demo", root.id) is False  # already gone


def test_projects_are_isolated(store: CommentStore) -> None:
    a = _root(store, project="alpha")
    _root(store, project="beta")
    assert [c.id for c in store.list("alpha")] == [a.id]
    assert len(store.list("beta")) == 1


def test_corrupt_file_is_treated_as_empty(store: CommentStore, tmp_path: Path) -> None:
    _root(store)
    (tmp_path / "comments" / "demo.json").write_text("{ not json")
    assert store.list("demo") == []


def test_unsafe_project_name_is_sanitised(store: CommentStore, tmp_path: Path) -> None:
    store.add("weird/../name", file="a", line=1, side="new", code="", body="hi")
    files = list((tmp_path / "comments").glob("*.json"))
    assert len(files) == 1 and "/" not in files[0].name
