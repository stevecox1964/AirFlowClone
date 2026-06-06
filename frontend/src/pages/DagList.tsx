import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import type { DagSummary } from "../types";
import { formatRelative } from "../utils";

export default function DagList() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const dagsQ = useQuery({
    queryKey: ["dags"],
    queryFn: api.listDags,
    refetchInterval: 5000,
  });

  const triggerM = useMutation({
    mutationFn: (dagId: string) => api.triggerDag(dagId),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  // Param DAGs need values at trigger time — send them to the DAG page (trigger
  // form) instead of firing a request that would 400 on a missing required param.
  const handleTrigger = (dag: DagSummary) => {
    if (dag.params.length > 0) navigate(`/dags/${dag.dag_id}`);
    else triggerM.mutate(dag.dag_id);
  };

  const reloadM = useMutation({
    mutationFn: api.reload,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dags"] }),
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">DAGs</h1>
        <div className="flex gap-2">
          <button
            onClick={() => reloadM.mutate()}
            disabled={reloadM.isPending}
            className="text-sm px-3 py-1.5 rounded border border-neutral-700 hover:bg-neutral-800 disabled:opacity-50"
          >
            {reloadM.isPending ? "scanning…" : "rescan dags/"}
          </button>
          <Link
            to="/dags/new"
            className="text-sm px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500"
          >
            + new DAG
          </Link>
        </div>
      </div>

      {dagsQ.isLoading && <div className="text-neutral-500">loading…</div>}
      {dagsQ.error && (
        <div className="text-rose-400">error: {String(dagsQ.error)}</div>
      )}

      {dagsQ.data && dagsQ.data.length === 0 && (
        <div className="text-neutral-500 p-6 border border-dashed border-neutral-800 rounded">
          No DAGs found. Drop a Python file into <code>dags/</code> and click rescan.
        </div>
      )}

      <ul className="space-y-3">
        {dagsQ.data?.map((dag) => (
          <li
            key={dag.dag_id}
            className="border border-neutral-800 rounded bg-neutral-900/40 p-4 hover:border-neutral-700 transition"
          >
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/dags/${dag.dag_id}`}
                    className="font-mono text-base text-emerald-400 hover:underline"
                  >
                    {dag.dag_id}
                  </Link>
                  {dag.is_paused && (
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-800">
                      paused
                    </span>
                  )}
                </div>
                {dag.description && (
                  <p className="text-sm text-neutral-400 mt-1">{dag.description}</p>
                )}
                {dag.schedule && (
                  <div className="text-xs text-neutral-500 mt-2 flex gap-4">
                    <span className="font-mono">schedule: <span className="text-neutral-300">{dag.schedule}</span></span>
                    {!dag.is_paused && dag.next_run_at && (
                      <span>next run: <span className="text-neutral-300">{formatRelative(dag.next_run_at)}</span></span>
                    )}
                  </div>
                )}
                <div className="text-xs text-neutral-500 mt-2 font-mono">
                  {dag.tasks.length} tasks: {dag.tasks.map((t) => t.task_id).join(" → ")}
                </div>
                {dag.parse_error && (
                  <pre className="mt-2 p-2 text-xs text-rose-300 bg-rose-950/30 border border-rose-900 rounded overflow-x-auto">
                    {dag.parse_error}
                  </pre>
                )}
              </div>
              <div className="shrink-0 flex gap-2">
                <Link
                  to={`/dags/${dag.dag_id}`}
                  className="px-3 py-1.5 text-sm rounded border border-neutral-700 hover:bg-neutral-800"
                >
                  runs
                </Link>
                <button
                  disabled={!!dag.parse_error || triggerM.isPending}
                  onClick={() => handleTrigger(dag)}
                  className="px-3 py-1.5 text-sm rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  trigger run
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
