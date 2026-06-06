import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import StatusBadge from "../components/StatusBadge";
import type { TaskInstance } from "../types";

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const qc = useQueryClient();
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  const runQ = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "pending" || status === "running" ? 1500 : false;
    },
  });

  const retryM = useMutation({
    mutationFn: (taskId: string) => api.retryTask(runId!, taskId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", runId] }),
  });

  if (!runId) return null;
  const run = runQ.data;

  const sortedTasks = run?.tasks ? sortByExecution(run.tasks) : [];

  return (
    <div>
      <Link
        to={run ? `/dags/${run.dag_id}` : "/"}
        className="text-sm text-neutral-500 hover:text-neutral-300"
      >
        ← back
      </Link>

      {run && (
        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h1 className="font-mono text-lg text-emerald-400 truncate">{run.id}</h1>
              <StatusBadge status={run.status} />
            </div>
            <div className="text-xs text-neutral-500 mt-1 font-mono">
              dag={run.dag_id} · trigger={run.trigger_type}
              {run.started_at && ` · started ${new Date(run.started_at).toLocaleString()}`}
              {run.finished_at && ` · finished ${new Date(run.finished_at).toLocaleString()}`}
            </div>
            {run.params && Object.keys(run.params).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.entries(run.params).map(([k, v]) => (
                  <span
                    key={k}
                    className="text-xs font-mono px-2 py-0.5 rounded border border-neutral-700 bg-neutral-900/50 text-neutral-300"
                    title="run param this run executed with"
                  >
                    {k}={JSON.stringify(v)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 md:grid-cols-[280px_1fr] gap-6">
        <aside>
          <h2 className="text-sm uppercase tracking-wide text-neutral-500 mb-2">tasks</h2>
          <ul className="space-y-1">
            {sortedTasks.map((t) => (
              <li key={t.task_id}>
                <button
                  onClick={() => setSelectedTask(t.task_id)}
                  className={`w-full text-left p-2 rounded border font-mono text-sm transition ${
                    selectedTask === t.task_id
                      ? "border-emerald-700 bg-emerald-950/30"
                      : "border-neutral-800 bg-neutral-900/30 hover:border-neutral-700"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-emerald-300">{t.task_id}</span>
                    <StatusBadge status={t.status} />
                  </div>
                  {t.attempt > 0 && (
                    <div className="text-xs text-neutral-500 mt-1">
                      attempt {t.attempt}
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section>
          {selectedTask ? (
            <TaskPanel
              runId={runId}
              task={sortedTasks.find((t) => t.task_id === selectedTask)!}
              onRetry={() => retryM.mutate(selectedTask)}
              retryPending={retryM.isPending}
            />
          ) : (
            <div className="text-neutral-500 text-sm p-6 border border-dashed border-neutral-800 rounded">
              Select a task on the left to view logs, output, and retry it.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function sortByExecution(tasks: TaskInstance[]): TaskInstance[] {
  // Best-effort: tasks with started_at sort first; pending/upstream_failed go after by name
  return [...tasks].sort((a, b) => {
    if (a.started_at && b.started_at) {
      return a.started_at.localeCompare(b.started_at);
    }
    if (a.started_at) return -1;
    if (b.started_at) return 1;
    return a.task_id.localeCompare(b.task_id);
  });
}

function TaskPanel({
  runId,
  task,
  onRetry,
  retryPending,
}: {
  runId: string;
  task: TaskInstance;
  onRetry: () => void;
  retryPending: boolean;
}) {
  const isLive = task.status === "running" || task.status === "pending";

  const logQ = useQuery({
    queryKey: ["log", runId, task.task_id, task.attempt],
    queryFn: () => api.getLog(runId, task.task_id),
    enabled: task.attempt > 0,
    refetchInterval: isLive ? 1000 : false,
  });

  const outputQ = useQuery({
    queryKey: ["output", runId, task.task_id, task.status],
    queryFn: () => api.getOutput(runId, task.task_id),
    enabled: task.status === "success" || task.status === "failed",
  });

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <h2 className="font-mono text-base text-emerald-400">{task.task_id}</h2>
          <StatusBadge status={task.status} />
          {task.attempt > 0 && (
            <span className="text-xs text-neutral-500 font-mono">
              attempt {task.attempt}
            </span>
          )}
        </div>
        <button
          onClick={onRetry}
          disabled={retryPending || isLive}
          className="px-3 py-1.5 text-sm rounded border border-amber-700 bg-amber-950/40 text-amber-200 hover:bg-amber-900/40 disabled:opacity-40 disabled:cursor-not-allowed"
          title="re-run this task and any downstream that was blocked"
        >
          {retryPending ? "retrying…" : "retry this task"}
        </button>
      </div>

      {task.error && (
        <details open className="mb-3 border border-rose-900 bg-rose-950/30 rounded">
          <summary className="px-3 py-2 cursor-pointer text-rose-300 text-sm">
            error preview
          </summary>
          <pre className="px-3 pb-3 text-xs text-rose-200 overflow-x-auto whitespace-pre-wrap">
            {task.error}
          </pre>
        </details>
      )}

      <section className="mb-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500">log</h3>
          {isLive && <span className="text-xs text-sky-400 font-mono">live</span>}
        </div>
        <pre className="bg-black border border-neutral-800 rounded p-3 text-xs font-mono leading-relaxed overflow-x-auto max-h-96 overflow-y-auto whitespace-pre-wrap text-neutral-300">
          {logQ.data?.content ?? (task.attempt === 0 ? "(not run yet)" : "(loading…)")}
        </pre>
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
          output (json)
        </h3>
        <pre className="bg-black border border-neutral-800 rounded p-3 text-xs font-mono leading-relaxed overflow-x-auto max-h-96 overflow-y-auto whitespace-pre-wrap text-emerald-300">
          {outputQ.data?.present
            ? JSON.stringify(outputQ.data.value, null, 2)
            : "(no output)"}
        </pre>
      </section>
    </div>
  );
}
