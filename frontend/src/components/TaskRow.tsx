import { useState } from "react";

import type { Goal, Task } from "../types";
import DueChip from "./DueChip";

interface Props {
  task: Task;
  goals: Goal[];
  onToggle: () => Promise<void>;
  onSave: (patch: Partial<Task>) => Promise<void>;
  onDelete: () => Promise<void>;
}

export default function TaskRow({ task, goals, onToggle, onSave, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(task.text);
  const [due, setDue] = useState(task.due ?? "");
  const [goalId, setGoalId] = useState<number | "">(task.linked_goal_id ?? "");
  const [busy, setBusy] = useState(false);

  function open() {
    setText(task.text);
    setDue(task.due ?? "");
    setGoalId(task.linked_goal_id ?? "");
    setEditing(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    await onSave({
      text: text.trim(),
      // Empty means "no deadline" — null clears it server-side, "" would not.
      due: due || null,
      linked_goal_id: goalId === "" ? null : goalId,
    });
    setBusy(false);
    setEditing(false);
  }

  if (!editing) {
    const done = task.status === "done";
    return (
      <li className="tasks__item">
        <button
          className={`tasks__check${done ? " tasks__check--done" : ""}`}
          onClick={onToggle}
          aria-label={`Mark "${task.text}" ${done ? "not done" : "done"}`}
        />
        <span className={`tasks__text${done ? " tasks__text--done" : ""}`}>{task.text}</span>
        {task.due && !done && <DueChip due={task.due} />}
        <button className="row__edit" type="button" onClick={open}>
          Edit
        </button>
      </li>
    );
  }

  return (
    <li className="tasks__item tasks__item--editing">
      <form className="form" onSubmit={save}>
        <input
          className="input"
          value={text}
          aria-label="Task"
          onChange={(e) => setText(e.target.value)}
        />
        <div className="form__pair">
          <label className="field">
            <span className="field__label">Due</span>
            <input
              className="input"
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Goal</span>
            <select
              className="input"
              value={goalId}
              onChange={(e) => setGoalId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">None</option>
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.text}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form__actions">
          <button className="button" type="submit" disabled={busy || !text.trim()}>
            Save
          </button>
          <button className="button button--quiet" type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            className="button button--danger"
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await onDelete();
              setBusy(false);
            }}
          >
            Delete
          </button>
        </div>
      </form>
    </li>
  );
}
