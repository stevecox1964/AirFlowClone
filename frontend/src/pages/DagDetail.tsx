import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import StatusBadge from "../components/StatusBadge";
import type { DagTaskMeta, ParamSpec, RunSummary } from "../types";
import { formatRelative } from "../utils";

export default function DagDetail() {
  const { dagId } = useParams<{ dagId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showTrigger, setShowTrigger] = useState(false);

  const dagQ = useQuery({
    queryKey: ["dag", dagId],
    queryFn: () => api.getDag(dagId!),
    enabled: !!dagId,
    refetchInterval: 5000,
  });
  const runsQ = useQuery({
    queryKey: ["dag-runs", dagId],
    queryFn: () => api.listDagRuns(dagId!),
    enabled: !!dagId,
    refetchInterval: 2000,
  });
  const triggerM = useMutation({
    mutationFn: (params: Record<string, unknown>) => api.triggerDag(dagId!, params),
    onSuccess: (run) => {
      setShowTrigger(false);
      navigate(`/runs/${run.id}`);
    },
  });
  const handleTrigger = () => {
    if ((dag?.params?.length ?? 0) > 0) setShowTrigger(true);
    else triggerM.mutate({});
  };
  const pauseM = useMutation({
    mutationFn: () =>
      dagQ.data?.is_paused ? api.unpauseDag(dagId!) : api.pauseDag(dagId!),
    onSuccess: (next) => {
      qc.setQueryData(["dag", dagId], next);
      qc.invalidateQueries({ queryKey: ["dags"] });
    },
  });
  const deleteM = useMutation({
    mutationFn: () => api.deleteDag(dagId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dags"] });
      qc.removeQueries({ queryKey: ["dag", dagId] });
      navigate("/");
    },
  });
  const clearRunsM = useMutation({
    mutationFn: () => api.clearDagRuns(dagId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dag-runs", dagId] });
    },
  });
  const handleClearRuns = () => {
    const n = runsQ.data?.length ?? 0;
    const ok = window.confirm(
      `Clear all ${n} run(s) of "${dagId}"?\n\n` +
        `DB history will be removed; runs/ folder artifacts on disk are kept.`,
    );
    if (ok) clearRunsM.mutate();
  };
  const handleDelete = () => {
    const ok = window.confirm(
      `Delete DAG "${dagId}"?\n\nThe .py file and DB history will be removed. ` +
        `Existing runs/ folders on disk will be kept for forensics.`,
    );
    if (ok) deleteM.mutate();
  };

  if (!dagId) return null;
  const dag = dagQ.data;

  return (
    <div>
      <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-300">
        ← all DAGs
      </Link>

      <div className="mt-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-mono font-semibold text-emerald-400">{dagId}</h1>
            {dag?.is_paused && (
              <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-800">
                paused
              </span>
            )}
          </div>
          {dag?.description && (
            <p className="text-neutral-400 mt-1">{dag.description}</p>
          )}
          {dag?.schedule && (
            <div className="text-sm text-neutral-500 mt-2 flex gap-4">
              <span className="font-mono">schedule: <span className="text-neutral-300">{dag.schedule}</span></span>
              {!dag.is_paused && dag.next_run_at && (
                <span>next run: <span className="text-neutral-300">{formatRelative(dag.next_run_at)}</span></span>
              )}
            </div>
          )}
        </div>
        <div className="shrink-0 flex gap-2">
          <button
            onClick={handleDelete}
            disabled={deleteM.isPending}
            className="px-4 py-2 rounded border border-rose-900/60 text-rose-300 hover:bg-rose-950/40 disabled:opacity-40"
          >
            {deleteM.isPending ? "deleting…" : "delete"}
          </button>
          {dag?.is_ui_editable && (
            <Link
              to={`/dags/${dagId}/edit`}
              className="px-4 py-2 rounded border border-neutral-700 hover:bg-neutral-800"
            >
              edit
            </Link>
          )}
          {dag?.schedule && (
            <button
              onClick={() => pauseM.mutate()}
              disabled={pauseM.isPending}
              className="px-4 py-2 rounded border border-neutral-700 hover:bg-neutral-800 disabled:opacity-40"
            >
              {dag.is_paused ? "unpause" : "pause"}
            </button>
          )}
          <button
            onClick={handleTrigger}
            disabled={!!dag?.parse_error || triggerM.isPending}
            className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40"
          >
            trigger run
          </button>
        </div>
      </div>

      {showTrigger && dag && (
        <TriggerModal
          params={dag.params}
          submitting={triggerM.isPending}
          error={triggerM.error as Error | null}
          onCancel={() => setShowTrigger(false)}
          onSubmit={(vals) => triggerM.mutate(vals)}
        />
      )}

      <section className="mt-8">
        <h2 className="text-sm uppercase tracking-wide text-neutral-500 mb-2">
          tasks
        </h2>
        <ol className="border border-neutral-800 rounded divide-y divide-neutral-800 bg-neutral-900/30">
          {dagQ.data?.tasks.map((t) => (
            <li key={t.task_id} className="p-3 flex items-center gap-4 font-mono text-sm">
              <span className="text-emerald-400">{t.task_id}</span>
              {t.depends_on.length > 0 && (
                <span className="text-neutral-500">
                  ← {t.depends_on.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-8">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm uppercase tracking-wide text-neutral-500">runs</h2>
          <button
            onClick={handleClearRuns}
            disabled={!runsQ.data?.length || clearRunsM.isPending}
            className="text-xs px-2 py-1 rounded border border-rose-900/60 text-rose-300 hover:bg-rose-950/40 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {clearRunsM.isPending ? "clearing…" : "clear history"}
          </button>
        </div>
        {runsQ.data?.length === 0 && (
          <div className="text-neutral-500 text-sm p-4 border border-dashed border-neutral-800 rounded">
            No runs yet. Click "trigger run" to start one.
          </div>
        )}
        <ul className="space-y-1">
          {runsQ.data?.map((r) => (
            <RunRow
              key={r.id}
              run={r}
              terminalTask={terminalTaskId(dag?.tasks ?? [])}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}

// The 'final' task whose output represents the run's result: a leaf nothing depends on
// (last declared if several), else the last task.
function terminalTaskId(tasks: DagTaskMeta[]): string | null {
  if (tasks.length === 0) return null;
  const depended = new Set<string>();
  tasks.forEach((t) => t.depends_on.forEach((d) => depended.add(d)));
  const leaves = tasks.filter((t) => !depended.has(t.task_id));
  return (leaves.length ? leaves[leaves.length - 1] : tasks[tasks.length - 1]).task_id;
}

function RunRow({
  run,
  terminalTask,
}: {
  run: RunSummary;
  terminalTask: string | null;
}) {
  const [open, setOpen] = useState(false);
  const outQ = useQuery({
    queryKey: ["output", run.id, terminalTask],
    queryFn: () => api.getOutput(run.id, terminalTask!),
    enabled: open && !!terminalTask,
  });
  const hasParams = Object.keys(run.params ?? {}).length > 0;

  return (
    <li className="border border-neutral-800 rounded bg-neutral-900/30">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 p-4 hover:bg-neutral-900/60 transition text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-neutral-400 text-lg w-4">{open ? "▾" : "▸"}</span>
          <StatusBadge status={run.status} />
          <span className="font-mono text-sm text-neutral-300 truncate">{run.id}</span>
        </div>
        <div className="text-sm text-neutral-500 shrink-0">
          {run.started_at && new Date(run.started_at).toLocaleString()}
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-neutral-800 pt-4 space-y-3">
          {hasParams && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(run.params).map(([k, v]) => (
                <span
                  key={k}
                  className="text-sm font-mono px-2 py-1 rounded border border-neutral-700 bg-neutral-900/50 text-neutral-300"
                >
                  {k}={JSON.stringify(v)}
                </span>
              ))}
            </div>
          )}
          <div>
            <div className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
              output{terminalTask ? ` · ${terminalTask}` : ""}
            </div>
            <pre className="bg-black border border-neutral-800 rounded p-3 text-sm font-mono text-emerald-300 overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap">
              {!terminalTask
                ? "(no tasks)"
                : outQ.isLoading
                  ? "(loading…)"
                  : outQ.data?.present
                    ? JSON.stringify(outQ.data.value, null, 2)
                    : "(no output)"}
            </pre>
          </div>
          <Link
            to={`/runs/${run.id}`}
            className="inline-block text-sm text-neutral-400 hover:text-neutral-200"
          >
            open full run (logs, per-task output, retry) →
          </Link>
        </div>
      )}
    </li>
  );
}

function TriggerModal({
  params,
  submitting,
  error,
  onCancel,
  onSubmit,
}: {
  params: ParamSpec[];
  submitting: boolean;
  error: Error | null;
  onCancel: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  // Per-param text input (bool uses a select). Empty optional values are omitted so the
  // DAG's declared default applies; backend does the typed coercion + validation.
  const [vals, setVals] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      params.map((p) => [p.name, p.default == null ? "" : String(p.default)]),
    ),
  );

  const missingRequired = params.some(
    (p) => p.required && vals[p.name].trim() === "",
  );

  const submit = () => {
    const payload: Record<string, unknown> = {};
    for (const p of params) {
      const raw = vals[p.name];
      if (raw.trim() === "") continue; // omit -> use default
      payload[p.name] = p.type === "bool" ? raw === "true" : raw;
    }
    onSubmit(payload);
  };

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-lg border border-neutral-700 bg-neutral-900 p-5">
        <h2 className="text-lg font-semibold mb-1">trigger run</h2>
        <p className="text-xs text-neutral-500 mb-4">
          provide values for this DAG's run params
        </p>
        <div className="space-y-3">
          {params.map((p) => (
            <div key={p.name}>
              <label className="block text-xs uppercase tracking-wide text-neutral-500 mb-1">
                {p.name}
                <span className="ml-1 lowercase text-neutral-600">({p.type})</span>
                {p.required && <span className="ml-1 text-rose-400">*</span>}
              </label>
              {p.type === "bool" ? (
                <select
                  value={vals[p.name] || "false"}
                  onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })}
                  className="input font-mono w-full"
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  value={vals[p.name]}
                  onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })}
                  placeholder={p.required ? "(required)" : "(default)"}
                  className="input font-mono w-full"
                />
              )}
            </div>
          ))}
        </div>

        {error && (
          <div className="mt-3 border border-rose-900 bg-rose-950/30 rounded p-2 text-xs text-rose-200">
            {String(error)}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded border border-neutral-700 hover:bg-neutral-800"
          >
            cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || missingRequired}
            className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? "triggering…" : "trigger"}
          </button>
        </div>
      </div>
    </div>
  );
}
