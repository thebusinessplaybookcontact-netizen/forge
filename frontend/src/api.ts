import type { Dashboard, Goal, Task } from "./types";

// Same-origin in production (the API serves the built PWA); the Vite dev server
// proxies /api to the backend. Either way the Claude key stays server-side.
const BASE = "/api";

/**
 * A session can expire mid-use, and every request is a place that can discover it.
 * AuthGate registers here so any 401 anywhere puts the lock screen back up, rather
 * than each caller inventing its own handling.
 */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (res.status === 401) {
    onUnauthorized?.();
    throw new Error("Locked");
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// --- auth ---

export interface AuthStatus {
  required: boolean;
  authenticated: boolean;
}

export const getAuthStatus = () => request<AuthStatus>("/auth/status");
export const logout = () => request<unknown>("/auth/logout", { method: "POST" });

/** Returns null on success, or a message to show the user. */
export async function login(passcode: string): Promise<string | null> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passcode }),
  });
  if (res.ok) return null;
  const detail = await res.json().catch(() => null);
  return detail?.detail ?? `Sign in failed (${res.status})`;
}

export const getDashboard = () => request<Dashboard>("/dashboard");

/** Soft deletes return the handle needed to offer an undo. */
export interface DeleteResult {
  undo_id: number;
}

export const getGoals = () => request<Goal[]>("/goals");
export const createGoal = (body: Partial<Goal>) =>
  request<Goal>("/goals", { method: "POST", body: JSON.stringify(body) });
export const updateGoal = (id: number, body: Partial<Goal>) =>
  request<Goal>(`/goals/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteGoal = (id: number) =>
  request<DeleteResult>(`/goals/${id}`, { method: "DELETE" });

export const getTasks = () => request<Task[]>("/tasks");
export const createTask = (body: Partial<Task>) =>
  request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) });
export const updateTask = (id: number, body: Partial<Task>) =>
  request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteTask = (id: number) =>
  request<DeleteResult>(`/tasks/${id}`, { method: "DELETE" });

export const closeSession = (id: number) =>
  request<{ session_id: number; recap: string; commitments: string[] }>(`/sessions/${id}/close`, {
    method: "POST",
  });

export interface ToolActionEvent {
  name: string;
  ok: boolean;
  summary: string;
  entity: Record<string, unknown> | null;
  /** Present when the change can be taken back. */
  undo_id: number | null;
}

export interface UndoResult {
  undo_id: number;
  restored: { type: string; id: number; label: string };
}

/** Reverse a change. Omit the id to undo the most recent one. */
export const undoChange = (undoId?: number) =>
  request<UndoResult>(undoId == null ? "/undo" : `/undo/${undoId}`, { method: "POST" });

export interface StreamHandlers {
  onSession?: (sessionId: number) => void;
  onDelta: (text: string) => void;
  /** Fired when the coach changes a goal or task mid-reply. */
  onAction?: (action: ToolActionEvent) => void;
  onDone?: (sessionId: number) => void;
  onError?: (message: string) => void;
}

/**
 * POSTs a turn and reads the SSE response. Uses fetch rather than EventSource
 * because EventSource can't send a request body.
 */
export async function streamChat(
  body: { message: string; session_id: number | null; history: { role: string; content: string }[] },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (res.status === 401) {
    onUnauthorized?.();
    return;
  }
  if (!res.ok || !res.body) {
    handlers.onError?.(`${res.status} ${res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;

      const payload = JSON.parse(data);
      if (event === "session") handlers.onSession?.(payload.session_id);
      else if (event === "delta") handlers.onDelta(payload.text);
      else if (event === "action") handlers.onAction?.(payload as ToolActionEvent);
      else if (event === "done") handlers.onDone?.(payload.session_id);
      else if (event === "error") handlers.onError?.(payload.message);
    }
  }
}
