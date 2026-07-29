import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getDashboard, updateTask } from "../api";
import Composer from "../components/Composer";
import type { Dashboard } from "../types";

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getDashboard().then(setData).catch((e) => setError(String(e)));
  }, []);

  async function complete(id: number) {
    await updateTask(id, { status: "done" });
    setData((prev) =>
      prev ? { ...prev, open_tasks: prev.open_tasks.filter((t) => t.id !== id) } : prev,
    );
  }

  return (
    <div className="home">
      <header className="home__header">
        <h1 className="home__title">Today</h1>
      </header>

      {error && <p className="chat__error">{error}</p>}

      <section className="panel">
        <h2 className="panel__title">Quests</h2>
        {!data && <p className="muted">Loading…</p>}
        {data && data.open_tasks.length === 0 && (
          <p className="muted">Nothing open. Either you're ahead, or you're avoiding something.</p>
        )}
        <ul className="tasks">
          {data?.open_tasks.map((task) => (
            <li key={task.id} className="tasks__item">
              <button
                className="tasks__check"
                onClick={() => complete(task.id)}
                aria-label={`Mark "${task.text}" done`}
              />
              <span className="tasks__text">{task.text}</span>
              {task.due && <span className="tasks__due">{task.due}</span>}
            </li>
          ))}
        </ul>
      </section>

      {data && data.recent_summaries.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Last time</h2>
          <p className="muted">{data.recent_summaries[0].recap}</p>
        </section>
      )}

      <section className="home__composer">
        {/* Hand the first message to the Chat screen so the conversation lives in one place. */}
        <Composer
          onSend={(message) => navigate("/chat", { state: { message } })}
          placeholder="Talk to your coach…"
        />
      </section>
    </div>
  );
}
