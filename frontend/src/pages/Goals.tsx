import { useCallback, useEffect, useState } from "react";

import {
  createGoal,
  createTask,
  deleteGoal,
  deleteTask,
  getGoals,
  getTasks,
  undoChange,
  updateGoal,
  updateTask,
} from "../api";
import GoalRow from "../components/GoalRow";
import TaskRow from "../components/TaskRow";
import type { Goal, Horizon, Task } from "../types";

const HORIZONS: Horizon[] = ["daily", "weekly", "lifetime"];

/** What was just deleted, so it can be put back. */
interface Undoable {
  undoId: number;
  label: string;
}

export default function Goals() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [undoable, setUndoable] = useState<Undoable | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [goalText, setGoalText] = useState("");
  const [goalWhy, setGoalWhy] = useState("");
  const [horizon, setHorizon] = useState<Horizon>("weekly");
  const [taskText, setTaskText] = useState("");
  const [taskGoal, setTaskGoal] = useState<number | "">("");

  const refresh = useCallback(async () => {
    const [g, t] = await Promise.all([getGoals(), getTasks()]);
    setGoals(g);
    setTasks(t);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh]);

  /** Run a mutation, then resync. Keeps every handler down to one line. */
  const run = useCallback(
    async (work: () => Promise<unknown>) => {
      setError(null);
      try {
        await work();
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh],
  );

  async function addGoal(e: React.FormEvent) {
    e.preventDefault();
    if (!goalText.trim()) return;
    await run(() => createGoal({ text: goalText.trim(), horizon, why: goalWhy.trim() || null }));
    setGoalText("");
    setGoalWhy("");
  }

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    if (!taskText.trim()) return;
    await run(() =>
      createTask({ text: taskText.trim(), linked_goal_id: taskGoal === "" ? null : taskGoal }),
    );
    setTaskText("");
  }

  const removeGoal = (goal: Goal) =>
    run(async () => {
      const { undo_id } = await deleteGoal(goal.id);
      setUndoable({ undoId: undo_id, label: goal.text });
    });

  const removeTask = (task: Task) =>
    run(async () => {
      const { undo_id } = await deleteTask(task.id);
      setUndoable({ undoId: undo_id, label: task.text });
    });

  const active = goals.filter((g) => g.status !== "done");
  const done = goals.filter((g) => g.status === "done");
  const openTasks = tasks.filter((t) => t.status === "open");
  const doneTasks = tasks.filter((t) => t.status === "done");

  return (
    <div className="goals">
      <header className="home__header">
        <h1 className="home__title">Goals &amp; Tasks</h1>
      </header>

      {error && <p className="chat__error">{error}</p>}

      {undoable && (
        <div className="undo-bar" role="status">
          <span>Deleted “{undoable.label}”</span>
          <button
            className="action__undo"
            type="button"
            onClick={() =>
              run(async () => {
                await undoChange(undoable.undoId);
                setUndoable(null);
              })
            }
          >
            Undo
          </button>
          <button className="undo-bar__dismiss" type="button" onClick={() => setUndoable(null)}>
            Dismiss
          </button>
        </div>
      )}

      {HORIZONS.map((h) => {
        const inHorizon = active.filter((g) => g.horizon === h);
        if (inHorizon.length === 0) return null;
        return (
          <section key={h} className="panel">
            <h2 className="panel__title">{h}</h2>
            {inHorizon.map((goal) => (
              <GoalRow
                key={goal.id}
                goal={goal}
                onSave={(patch) => run(() => updateGoal(goal.id, patch))}
                onDelete={() => removeGoal(goal)}
              />
            ))}
          </section>
        );
      })}

      {done.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Achieved</h2>
          {done.map((goal) => (
            <GoalRow
              key={goal.id}
              goal={goal}
              onSave={(patch) => run(() => updateGoal(goal.id, patch))}
              onDelete={() => removeGoal(goal)}
            />
          ))}
        </section>
      )}

      <section className="panel">
        <h2 className="panel__title">Add a goal</h2>
        <form className="form" onSubmit={addGoal}>
          <input
            className="input"
            value={goalText}
            placeholder="What's the goal?"
            aria-label="Goal"
            onChange={(e) => setGoalText(e.target.value)}
          />
          <input
            className="input"
            value={goalWhy}
            placeholder="Why does it matter?"
            aria-label="Why it matters"
            onChange={(e) => setGoalWhy(e.target.value)}
          />
          <select
            className="input"
            value={horizon}
            aria-label="Horizon"
            onChange={(e) => setHorizon(e.target.value as Horizon)}
          >
            {HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
          <button className="button" type="submit">
            Add goal
          </button>
        </form>
      </section>

      <section className="panel">
        <h2 className="panel__title">To-do</h2>
        <ul className="tasks">
          {openTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              goals={goals}
              onToggle={() => run(() => updateTask(task.id, { status: "done" }))}
              onSave={(patch) => run(() => updateTask(task.id, patch))}
              onDelete={() => removeTask(task)}
            />
          ))}
        </ul>
        {openTasks.length === 0 && <p className="muted">Nothing open.</p>}

        <form className="form" onSubmit={addTask}>
          <input
            className="input"
            value={taskText}
            placeholder="Add a task"
            aria-label="New task"
            onChange={(e) => setTaskText(e.target.value)}
          />
          <select
            className="input"
            value={taskGoal}
            aria-label="Link to goal"
            onChange={(e) => setTaskGoal(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">No goal</option>
            {goals.map((g) => (
              <option key={g.id} value={g.id}>
                {g.text}
              </option>
            ))}
          </select>
          <button className="button" type="submit">
            Add task
          </button>
        </form>
      </section>

      {doneTasks.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Done</h2>
          <ul className="tasks">
            {doneTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                goals={goals}
                onToggle={() => run(() => updateTask(task.id, { status: "open" }))}
                onSave={(patch) => run(() => updateTask(task.id, patch))}
                onDelete={() => removeTask(task)}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
