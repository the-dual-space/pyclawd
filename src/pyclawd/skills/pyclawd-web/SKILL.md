---
name: pyclawd-web
description: The `pyclawd web` dashboard — a local, multi-project diff & code-review UI (the optional `pip install pyclawd[web]` extra). Browse the working diff across registered repos; view any file as syntax-highlighted **Source** or a rendered **preview** (Markdown renders GFM + GitHub alerts `> [!NOTE]` + emoji; HTML renders in a sandboxed, script-free iframe); leave **line-anchored review comments** on diff lines, on rendered-Markdown blocks, and on rendered-HTML elements; assemble them into one review and either send it to a running `claude` tmux pane or hand it to a headless agent to resolve. Also runs pyclawd verbs (check/test/golden/…) from the UI and edits/deletes files in the browser. Use when a human wants to review a diff or an agent's work in a browser, or when an agent needs to know what the dashboard renders and how comments flow.
when_to_use: Reviewing a working diff or an agent's changes in a browser; collecting inline review comments and handing them to a tmux pane or a headless fix-agent; previewing how a Markdown doc (alerts / emoji / tables / task lists) or an HTML file will actually render; running `pyclawd check`/`test`/`golden` from a UI. Also relevant when an agent authors Markdown in the repo — it can use GitHub alerts and emoji knowing the dashboard renders them.
---

# pyclawd-web

`pyclawd web` is an **optional** local dashboard for reviewing diffs and driving
review workflows in a browser. It is not part of the core install — a project (or
you) must `pip install 'pyclawd[web]'` (FastAPI + uvicorn + watchfiles). The core
`pyclawd` CLI never depends on it; when the extra is absent the `web` commands
self-report.

It is the **human side of the agent loop**: an agent makes changes on a branch /
working tree, a human browses the diff, leaves inline comments, and then either
sends those comments to the `claude` pane that is doing the work, or dispatches a
fresh headless agent to resolve them.

## Run it

```bash
pip install 'pyclawd[web]'          # one-time, the optional extra
pyclawd web serve                   # dashboard on http://127.0.0.1:8801
pyclawd web serve --host 0.0.0.0 --port 8830 --repo /path/to/repo
pyclawd web add <path> [--name N]   # register a repo
pyclawd web list                    # list registered + auto-discovered repos
pyclawd web remove <name>
```

It auto-discovers git repos under configured roots (default `~/workspace`) and
tracks a working diff live (a filesystem watcher pushes updates over SSE — no
polling). It is **multi-project**: switch repos and comparison refs (any branch /
tag / SHA / the working tree) from the top bar.

## Viewing a file — Source ⟷ Rendered

Every file opens in **Source**: the syntax-highlighted diff (inline or split) or
full-file view, with a comment gutter. For **`.md` / `.html`** files a
**Source | Rendered** toggle appears in the file header (the choice is **sticky** —
it persists until you switch back):

- **Markdown → Rendered** renders the doc richly: GitHub-Flavored Markdown (tables,
  task lists, strikethrough), **GitHub alerts** (`> [!NOTE]` / `[!TIP]` /
  `[!IMPORTANT]` / `[!WARNING]` / `[!CAUTION]` → colored callout boxes with icons),
  and **emoji shortcodes** (`:rocket:` → 🚀). Code fences render as plain preformatted
  text.
- **HTML → Rendered** renders the page in an iframe sandboxed to `allow-same-origin`
  only — **repo scripts never run** (safe) and styles stay isolated.

**Authoring implication for agents:** a Markdown doc you write in the repo will
render with those features in the dashboard — so use `> [!NOTE]`/`[!WARNING]`
callouts and emoji to make a hand-off / summary doc read well when a human previews
it.

## Commenting — one line-anchored model across every view

Comments are always **anchored to a source line** and share **one store**, so the
same comment shows up everywhere and feeds the review:

- **Source / diff view** — click the 💬 gutter on a line (old or new side).
- **Rendered Markdown** — hover a block, click 💬; the comment anchors to that
  block's source line and shows as a **persistent inline thread** right below it
  (commented blocks get an amber highlight). Edit/delete inline.
- **Rendered HTML** — click any element; the comment anchors to that element's
  source line (the element gets a gold outline) and shows in a list below the page.

Flip between Source and Rendered freely — it's the same comment either way.

## Turning comments into action (the Review tray)

The **Review (N)** tray lists every staged comment grouped by file. From there:

- **Send → tmux** — assemble the comments into one structured message and paste it
  into the selected running `claude` tmux pane (pick the pane in the session picker).
- **Copy** — copy the assembled review to the clipboard.
- **🤖 Run (edits only / full access)** — dispatch a **headless `claude -p` agent**
  that resolves every comment (edits auto-accepted); progress streams live in the UI.

So the loop is: agent works → human reviews the diff and leaves inline comments →
one click sends them back to the same agent, or spins up a new one to fix them.

## Also in the dashboard

- **Verb runner** — run `pyclawd check` / `test` / `golden` / `lint` / `typecheck` /
  `format` / `doctor` from the UI; output streams with a pass/fail verdict.
- **File edit / delete** — edit a file's working-tree content or delete it in the
  browser (the diff refreshes live).
- **Sessions** — list running `claude` tmux panes to target with a review.

## Boundaries

- The `[web]` deps are an **optional extra** — never assume they're installed; the
  core CLI (`check`/`test`/`golden`/…) is the contract, the dashboard is a
  convenience over it.
- Rendered views are for **preview + commenting**; the authoritative diff/lint/type
  signal is still `pyclawd check`. The dashboard runs those verbs, it doesn't replace
  them.
