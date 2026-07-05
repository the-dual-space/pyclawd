// Client UI state: the active project, the two comparison sides, view controls,
// the selected file, the tmux target, and review comments. Server data is
// React Query's job (hooks.ts); this is everything that is purely local, persisted
// to localStorage so a reload restores where you were — per project.
import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from "react";

import { api } from "@/api";
import type { CommentDraft, CommentStatus, DiffLayout, DiffMode, Comment } from "@/types";
import { WORKING_TREE } from "@/types";

const STORAGE_KEY = "pyclawd.web";

interface PerProject {
  base: string;
  target: string;
  mode: DiffMode;
  layout: DiffLayout;
  all: boolean;
  selected: string | null;
}

interface Persisted {
  project: string | null;
  session: string | null;
  pp: Record<string, PerProject>;
  settings: Settings;
}

/** Global (not per-project) preferences edited in the settings panel. */
export interface Settings {
  tabWidth: number;
  sendSubmit: boolean;
  sendFocus: boolean;
  /** Sticky Source/Rendered choice for renderable files (persists until changed). */
  renderMode: "source" | "rendered";
}

const DEFAULTS: PerProject = {
  base: "HEAD",
  target: WORKING_TREE,
  mode: "diff",
  layout: "inline",
  all: false,
  selected: null,
};

const SETTINGS_DEFAULTS: Settings = {
  tabWidth: 4,
  sendSubmit: false,
  sendFocus: false,
  renderMode: "source",
};

function load(): Persisted {
  const base: Persisted = { project: null, session: null, pp: {}, settings: SETTINGS_DEFAULTS };
  try {
    const saved = JSON.parse(localStorage[STORAGE_KEY] ?? "{}");
    return { ...base, ...saved, settings: { ...SETTINGS_DEFAULTS, ...(saved.settings ?? {}) } };
  } catch {
    return base;
  }
}

interface State extends PerProject {
  project: string | null;
  session: string | null;
  comments: Comment[];
  settings: Settings;
  /** A pending `"side:line"` anchor the diff view should scroll to (transient). */
  scrollTo: string | null;
}

type Action =
  | { type: "selectProject"; name: string }
  | { type: "setBase"; value: string }
  | { type: "setTarget"; value: string }
  | { type: "setMode"; value: DiffMode }
  | { type: "setLayout"; value: DiffLayout }
  | { type: "setAll"; value: boolean }
  | { type: "selectFile"; path: string | null }
  | { type: "scrollTo"; anchor: string | null }
  | { type: "setSession"; target: string | null }
  | { type: "setComments"; comments: Comment[] }
  | { type: "addComment"; comment: Comment }
  | { type: "patchComment"; comment: Comment }
  | { type: "removeComment"; id: string }
  | { type: "setSettings"; value: Partial<Settings> };

function persist(state: State): void {
  const prev = load();
  const next: Persisted = {
    project: state.project,
    session: state.session,
    settings: state.settings,
    pp: state.project
      ? {
          ...prev.pp,
          [state.project]: {
            base: state.base,
            target: state.target,
            mode: state.mode,
            layout: state.layout,
            all: state.all,
            selected: state.selected,
          },
        }
      : prev.pp,
  };
  localStorage[STORAGE_KEY] = JSON.stringify(next);
}

function reducer(state: State, action: Action): State {
  let next: State;
  switch (action.type) {
    case "selectProject": {
      const saved = load();
      const pp = { ...DEFAULTS, ...saved.pp[action.name] };
      // Comments are server-owned now; a project-change effect hydrates them.
      next = { ...state, ...pp, project: action.name, comments: [] };
      break;
    }
    case "setBase":
      next = { ...state, base: action.value };
      break;
    case "setTarget":
      next = { ...state, target: action.value };
      break;
    case "setMode":
      next = { ...state, mode: action.value };
      break;
    case "setLayout":
      next = { ...state, layout: action.value };
      break;
    case "setAll":
      next = { ...state, all: action.value };
      break;
    case "selectFile":
      next = { ...state, selected: action.path };
      break;
    case "scrollTo":
      next = { ...state, scrollTo: action.anchor };
      break;
    case "setSession":
      next = { ...state, session: action.target };
      break;
    case "setComments":
      next = { ...state, comments: action.comments };
      break;
    case "addComment":
      // Ignore a duplicate id (e.g. a reply frame racing a refetch).
      next = state.comments.some((c) => c.id === action.comment.id)
        ? state
        : { ...state, comments: [...state.comments, action.comment] };
      break;
    case "patchComment":
      next = {
        ...state,
        comments: state.comments.map((c) => (c.id === action.comment.id ? action.comment : c)),
      };
      break;
    case "removeComment":
      // Drop the comment and any replies anchored to it.
      next = {
        ...state,
        comments: state.comments.filter((c) => c.id !== action.id && c.parent !== action.id),
      };
      break;
    case "setSettings":
      next = { ...state, settings: { ...state.settings, ...action.value } };
      break;
  }
  persist(next);
  return next;
}

function initialState(): State {
  const saved = load();
  return {
    ...DEFAULTS,
    project: null,
    selected: null,
    session: saved.session,
    comments: [],
    settings: saved.settings,
    scrollTo: null,
  };
}

interface Store extends State {
  selectProject: (name: string) => void;
  setBase: (value: string) => void;
  setTarget: (value: string) => void;
  setMode: (value: DiffMode) => void;
  setLayout: (value: DiffLayout) => void;
  setAll: (value: boolean) => void;
  selectFile: (path: string | null) => void;
  setScrollTo: (anchor: string | null) => void;
  setSession: (target: string | null) => void;
  /** Create a comment (or a reply, via `draft.parent`); the server assigns id/author. */
  stage: (draft: CommentDraft) => Promise<void>;
  editComment: (id: string, body: string) => Promise<void>;
  /** Toggle a thread's open/resolved status. */
  setStatus: (id: string, status: CommentStatus) => Promise<void>;
  unstage: (id: string) => Promise<void>;
  clearStaged: () => Promise<void>;
  /** Insert a comment the client already has (e.g. a streamed agent reply). */
  pushComment: (comment: Comment) => void;
  setSettings: (value: Partial<Settings>) => void;
}

const StoreContext = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  // Hydrate the active project's comments from the server (they live server-side now).
  useEffect(() => {
    if (!state.project) return;
    let cancelled = false;
    api
      .comments(state.project)
      .then((r) => !cancelled && dispatch({ type: "setComments", comments: r.comments }))
      .catch(() => !cancelled && dispatch({ type: "setComments", comments: [] }));
    return () => {
      cancelled = true;
    };
  }, [state.project]);

  const store = useMemo<Store>(
    () => ({
      ...state,
      selectProject: (name) => dispatch({ type: "selectProject", name }),
      setBase: (value) => dispatch({ type: "setBase", value }),
      setTarget: (value) => dispatch({ type: "setTarget", value }),
      setMode: (value) => dispatch({ type: "setMode", value }),
      setLayout: (value) => dispatch({ type: "setLayout", value }),
      setAll: (value) => dispatch({ type: "setAll", value }),
      selectFile: (path) => dispatch({ type: "selectFile", path }),
      setScrollTo: (anchor) => dispatch({ type: "scrollTo", anchor }),
      setSession: (target) => dispatch({ type: "setSession", target }),
      stage: async (draft) => {
        if (!state.project) return;
        const created = await api.addComment(state.project, draft);
        dispatch({ type: "addComment", comment: created });
      },
      editComment: async (id, body) => {
        if (!state.project) return;
        const updated = await api.editComment(state.project, id, { body });
        dispatch({ type: "patchComment", comment: updated });
      },
      setStatus: async (id, status) => {
        if (!state.project) return;
        const updated = await api.editComment(state.project, id, { status });
        dispatch({ type: "patchComment", comment: updated });
      },
      unstage: async (id) => {
        if (!state.project) return;
        await api.deleteComment(state.project, id);
        dispatch({ type: "removeComment", id });
      },
      clearStaged: async () => {
        const project = state.project;
        if (!project) return;
        // Deleting a root cascades its replies server-side.
        await Promise.all(
          state.comments.filter((c) => !c.parent).map((c) => api.deleteComment(project, c.id)),
        );
        dispatch({ type: "setComments", comments: [] });
      },
      pushComment: (comment) => dispatch({ type: "addComment", comment }),
      setSettings: (value) => dispatch({ type: "setSettings", value }),
    }),
    [state],
  );
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>;
}

/** Access the app store; must be used under a StoreProvider. */
export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useStore must be used within StoreProvider");
  return store;
}

/** The default initial per-project prefs (for the initial selection bootstrap). */
export { DEFAULTS };
