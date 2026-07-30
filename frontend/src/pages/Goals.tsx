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
import { useChatContext } from "../ChatContext";
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
  const [showDone, setShowDone] = useState(false);
  const [composing, setComposing] = useState(false);
  const { changed } = useChatContext();

  const [goalText, setGoalText] = useState("");
  const [goalWhy, setGoalWhy] = useState("");
  const [horizon, setHorizon] = useState<Horizon>("weekly");
  const [taskText, setTaskText] = useState("");

  const refresh = useCallback(async () => {
    const [g, t] = await Promise.all([getGoals(), getTasks()]);
    setGoals(g);
    setTasks(t);
  }, []);

  // Also resyncs when the coach changes something mid-conversation.
  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh, changed]);

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
    setComposing(false);
  }

  async function addLooseTask(e: React.FormEvent) {
    e.preventDefault();
    if (!taskText.trim()) return;
    await run(() => createTask({ text: taskText.trim(), linked_goal_id: null }));
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
  const achieved = goals.filter((g) => g.status === "done");
  const openTasks = tasks.filter((t) => t.status === "open");
  const doneTasks = tasks.filter((t) => t.status === "done");
  const loose = openTasks.filter((t) => t.linked_goal_id == null);

  /** The open tasks serving one goal — the link the model already reasons about, made
      visible. A goal with none is a goal nothing is happening on. */
  const stepsFor = (goal: Goal) => openTasks.filter((t) => t.linked_goal_id === goal.id);

  const taskRow = (task: Task) => (
    <TaskRow
      key={task.id}
      task={task}
      goals={goals}
      onToggle={() => run(() => updateTask(task.id, { status: task.status === "done" ? "open" : "done" }))}
      onSave={(patch) => run(() => updateTask(task.id, patch))}
      onDelete={() => removeTask(task)}
    />
  );

  const goalRow = (goal: Goal) => {
    const steps = stepsFor(goal);
    return (
      <GoalRow
        key={goal.id}
        goal={goal}
        hasSteps={steps.length > 0}
        onSave={(patch) => run(() => updateGoal(goal.id, patch))}
        onDelete={() => removeGoal(goal)}
        // A paused goal is paused on purpose; it shouldn't be asking for next steps.
        onAddStep={
          goal.status === "active"
            ? (text) => run(() => createTask({ text, linked_goal_id: goal.id }))
            : undefined
        }
      >
        {steps.length > 0 ? steps.map(taskRow) : null}
      </GoalRow>
    );
  };

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
            {inHorizon.map(goalRow)}
          </section>
        );
      })}

      <section className="panel">
        {composing ? (
          <form className="form" onSubmit={addGoal}>
            <h2 className="panel__title">Add a goal</h2>
            <input
              className="input"
              value={goalText}
              autoFocus
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
            <div className="form__actions">
              <button className="button" type="submit" disabled={!goalText.trim()}>
                Add goal
              </button>
              <button
                className="button button--quiet"
                type="button"
                onClick={() => setComposing(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button className="button button--quiet" type="button" onClick={() => setComposing(true)}>
            + New goal
          </button>
        )}
      </section>

      <section className="panel">
        <h2 className="panel__title">Not tied to a goal</h2>
        {loose.length === 0 && <p className="muted">Everything open is attached to something.</p>}
        <ul className="tasks">{loose.map(taskRow)}</ul>
        <form className="form" onSubmit={addLooseTask}>
          <input
            className="input"
            value={taskText}
            placeholder="Add a task"
            aria-label="New task"
            onChange={(e) => setTaskText(e.target.value)}
          />
        </form>
      </section>

      {achieved.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Achieved</h2>
          {achieved.map((goal) => (
            <GoalRow
              key={goal.id}
              goal={goal}
              onSave={(patch) => run(() => updateGoal(goal.id, patch))}
              onDelete={() => removeGoal(goal)}
            />
          ))}
        </section>
      )}

      {doneTasks.length > 0 && (
        <section className="panel">
          {/* Finished work is worth being able to see and worth staying out of the way.
              Collapsed by default; the count is the part you actually want. */}
          <button className="panel__toggle" type="button" onClick={() => setShowDone(!showDone)}>
            <span className="panel__title">Done</span>
            <span className="panel__count">{showDone ? "hide" : doneTasks.length}</span>
          </button>
          {showDone && <ul className="tasks">{doneTasks.map(taskRow)}</ul>}
        </section>
      )}
    </div>
  );
}
