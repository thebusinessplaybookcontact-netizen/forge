import type { Dashboard, Goal, Task } from "./types";

// Same-origin in production (the API serves the built PWA); the Vite dev server
// proxies /api to the backend. Either way the Claude key stays server-side.
const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const getDashboard = () => request<Dashboard>("/dashboard");

export const getGoals = () => request<Goal[]>("/goals");
export const createGoal = (body: Partial<Goal>) =>
  request<Goal>("/goals", { method: "POST", body: JSON.stringify(body) });
export const updateGoal = (id: number, body: Partial<Goal>) =>
  request<Goal>(`/goals/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteGoal = (id: number) => request<void>(`/goals/${id}`, { method: "DELETE" });

export const getTasks = () => request<Task[]>("/tasks");
export const createTask = (body: Partial<Task>) =>
  request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) });
export const updateTask = (id: number, body: Partial<Task>) =>
  request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteTask = (id: number) => request<void>(`/tasks/${id}`, { method: "DELETE" });

export const closeSession = (id: number) =>
  request<{ session_id: number; recap: string; commitments: string[] }>(`/sessions/${id}/close`, {
    method: "POST",
  });

export interface StreamHandlers {
  onSession?: (sessionId: number) => void;
  onDelta: (text: string) => void;
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
      else if (event === "done") handlers.onDone?.(payload.session_id);
      else if (event === "error") handlers.onError?.(payload.message);
    }
  }
}
