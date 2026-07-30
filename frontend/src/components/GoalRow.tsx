import { useState } from "react";

import type { Goal, GoalStatus, Horizon } from "../types";

const HORIZONS: Horizon[] = ["daily", "weekly", "lifetime"];
const STATUSES: GoalStatus[] = ["active", "paused", "done"];

interface Props {
  goal: Goal;
  onSave: (patch: Partial<Goal>) => Promise<void>;
  onDelete: () => Promise<void>;
  /** Add a task already linked to this goal. */
  onAddStep?: (text: string) => Promise<void>;
  /** The open tasks serving this goal, rendered beneath it. */
  children?: React.ReactNode;
  /** False when `children` is empty, so the row can ask for a next step. */
  hasSteps?: boolean;
}

/** A goal: reads as prose, opens into a form, and carries the work under it. */
export default function GoalRow({
  goal,
  onSave,
  onDelete,
  onAddStep,
  children,
  hasSteps,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(goal.text);
  const [why, setWhy] = useState(goal.why ?? "");
  const [horizon, setHorizon] = useState<Horizon>(goal.horizon);
  const [status, setStatus] = useState<GoalStatus>(goal.status);
  const [busy, setBusy] = useState(false);

  const [adding, setAdding] = useState(false);
  const [step, setStep] = useState("");

  function open() {
    // Reset from the goal each time, so cancelling really discards.
    setText(goal.text);
    setWhy(goal.why ?? "");
    setHorizon(goal.horizon);
    setStatus(goal.status);
    setEditing(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    await onSave({ text: text.trim(), why: why.trim() || null, horizon, status });
    setBusy(false);
    setEditing(false);
  }

  async function addStep(e: React.FormEvent) {
    e.preventDefault();
    if (!step.trim() || busy || !onAddStep) return;
    setBusy(true);
    await onAddStep(step.trim());
    setBusy(false);
    setStep("");
    setAdding(false);
  }

  if (!editing) {
    const live = goal.status === "active";
    return (
      <article className="goal">
        <div className="row">
          <div className="row__body">
            <p className={`goal__text${live ? "" : " goal__text--muted"}`}>{goal.text}</p>
            {goal.why && <p className="goal__why">{goal.why}</p>}
          </div>
          {!live && <span className="chip">{goal.status}</span>}
          <button className="row__edit" type="button" onClick={open}>
            Edit
          </button>
        </div>

        {children && <ul className="tasks goal__steps">{children}</ul>}

        {onAddStep &&
          (adding ? (
            <form className="goal__add" onSubmit={addStep}>
              <input
                className="input"
                value={step}
                autoFocus
                placeholder="What's the next step?"
                aria-label={`Next step for ${goal.text}`}
                onChange={(e) => setStep(e.target.value)}
                onBlur={() => !step.trim() && setAdding(false)}
              />
              <button className="button" type="submit" disabled={busy || !step.trim()}>
                Add
              </button>
            </form>
          ) : (
            /* One affordance doing two jobs: on a goal with work under it this is just
               "add another", and on a goal with none it's the diagnostic this screen
               exists to give — nothing is happening on this — said as an invitation
               rather than a warning, and carried by colour instead of a second chip. */
            <button
              className={`goal__prompt${hasSteps ? "" : " goal__prompt--empty"}`}
              type="button"
              onClick={() => setAdding(true)}
            >
              {hasSteps ? "+ Add a step" : "+ Plan a first step"}
            </button>
          ))}
      </article>
    );
  }

  return (
    <form className="goal form" onSubmit={save}>
      <input
        className="input"
        value={text}
        aria-label="Goal"
        onChange={(e) => setText(e.target.value)}
      />
      <textarea
        className="input"
        value={why}
        rows={2}
        aria-label="Why it matters"
        placeholder="Why does it matter?"
        onChange={(e) => setWhy(e.target.value)}
      />
      <div className="form__pair">
        <label className="field">
          <span className="field__label">Horizon</span>
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
        </label>
        <label className="field">
          <span className="field__label">Status</span>
          <select
            className="input"
            value={status}
            onChange={(e) => setStatus(e.target.value as GoalStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
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
  );
}
