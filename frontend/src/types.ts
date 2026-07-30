export type Horizon = "daily" | "weekly" | "lifetime";
export type GoalStatus = "active" | "paused" | "done";
export type TaskStatus = "open" | "done";

export interface Goal {
  id: number;
  text: string;
  horizon: Horizon;
  why: string | null;
  status: GoalStatus;
  created_at: string;
}

export interface Task {
  id: number;
  text: string;
  linked_goal_id: number | null;
  status: TaskStatus;
  due: string | null;
  created_at: string;
}

export interface Summary {
  id: number;
  session_id: number;
  recap: string;
  commitments: string;
  created_at: string;
}

export type Cadence = "daily" | "weekly";

export interface Habit {
  id: number;
  text: string;
  cadence: Cadence;
  target_per_week: number;
  why: string | null;
  linked_goal_id: number | null;

  done_today: boolean;
  this_week: number;
  current_streak: number;
  longest_streak: number;
  completion_rate_30d: number;
  /** Oldest-first, one boolean per day, starting at grid_start. */
  grid_start: string;
  grid: boolean[];
}

export interface Dashboard {
  goals: Goal[];
  open_tasks: Task[];
  habits: Habit[];
  recent_summaries: Summary[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export type VoiceMode = "human" | "browser";

export type ThemePref = "system" | "light" | "dark";

export interface AppSettings {
  voiceMode: VoiceMode;
  /** Whether the coach reads its replies aloud automatically. */
  speakReplies: boolean;
  theme: ThemePref;
}
