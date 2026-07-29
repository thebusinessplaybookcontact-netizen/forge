import type { Entry } from "../useChat";

interface Props {
  entry: Extract<Entry, { kind: "action" }>;
  onUndo: (undoId: number) => void;
}

/** The inline "✓ Added …" line, with an Undo affordance when the change is reversible. */
export default function ActionNote({ entry, onUndo }: Props) {
  const { action, undone } = entry;
  const undoable = action.ok && action.undo_id != null && !undone;

  return (
    <p className={`action${action.ok ? "" : " action--failed"}`} title={action.name}>
      {action.ok ? "✓" : "✕"} {action.summary}
      {undone && <span className="action__undone"> · undone</span>}
      {undoable && (
        <button className="action__undo" onClick={() => onUndo(action.undo_id!)} type="button">
          Undo
        </button>
      )}
    </p>
  );
}
