import { useEffect, useState } from "react";

import { createGoal, createTask, getGoals, getTasks, updateTask } from "../api";
import type { Goal, Horizon, Task } from "../types";

const HORIZONS: Horizon[] = ["daily", "weekly", "lifetime"];

export default function Goals() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goalText, setGoalText] = useState("");
  const [goalWhy, setGoalWhy] = useState("");
  const [horizon, setHorizon] = useState<Horizon>("weekly");
  const [taskText, setTaskText] = useState("");
  const [taskGoal, setTaskGoal] = useState<number | "">("");

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    const [g, t] = await Promise.all([getGoals(), getTasks()]);
    setGoals(g);
    setTasks(t);
  }

  async function addGoal(e: React.FormEvent) {
    e.preventDefault();
    if (!goalText.trim()) return;
    await createGoal({ text: goalText.trim(), horizon, why: goalWhy.trim() || null });
    setGoalText("");
    setGoalWhy("");
    await refresh();
  }

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    if (!taskText.trim()) return;
    await createTask({
      text: taskText.trim(),
      linked_goal_id: taskGoal === "" ? null : taskGoal,
    });
    setTaskText("");
    await refresh();
  }

  async function toggle(task: Task) {
    await updateTask(task.id, { status: task.status === "open" ? "done" : "open" });
    await refresh();
  }

  return (
    <div className="goals">
      <header className="home__header">
        <h1 className="home__title">Goals &amp; Tasks</h1>
      </header>

      {HORIZONS.map((h) => {
        const inHorizon = goals.filter((g) => g.horizon === h);
        if (inHorizon.length === 0) return null;
        return (
          <section key={h} className="panel">
            <h2 className="panel__title">{h}</h2>
            {inHorizon.map((goal) => (
              <article key={goal.id} className="goal">
                <p className="goal__text">{goal.text}</p>
                {goal.why && <p className="goal__why">{goal.why}</p>}
              </article>
            ))}
          </section>
        );
      })}

      <section className="panel">
        <h2 className="panel__title">Add a goal</h2>
        <form className="form" onSubmit={addGoal}>
          <input
            className="input"
            value={goalText}
            placeholder="What's the goal?"
            onChange={(e) => setGoalText(e.target.value)}
          />
          <input
            className="input"
            value={goalWhy}
            placeholder="Why does it matter?"
            onChange={(e) => setGoalWhy(e.target.value)}
          />
          <select
            className="input"
            value={horizon}
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
          {tasks.map((task) => (
            <li key={task.id} className="tasks__item">
              <button
                className={`tasks__check${task.status === "done" ? " tasks__check--done" : ""}`}
                onClick={() => toggle(task)}
                aria-label={`Toggle "${task.text}"`}
              />
              <span className={`tasks__text${task.status === "done" ? " tasks__text--done" : ""}`}>
                {task.text}
              </span>
            </li>
          ))}
        </ul>

        <form className="form" onSubmit={addTask}>
          <input
            className="input"
            value={taskText}
            placeholder="Add a task"
            onChange={(e) => setTaskText(e.target.value)}
          />
          <select
            className="input"
            value={taskGoal}
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
    </div>
  );
}
