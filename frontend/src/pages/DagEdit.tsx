import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import DagForm from "../components/DagForm";
import type { DagSpec } from "../types";

export default function DagEdit() {
  const { dagId } = useParams<{ dagId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const specQ = useQuery({
    queryKey: ["dag-spec", dagId],
    queryFn: () => api.getDagSpec(dagId!),
    enabled: !!dagId,
  });

  const updateM = useMutation({
    mutationFn: (spec: DagSpec) => api.updateDag(dagId!, spec),
    onSuccess: (dag) => {
      qc.invalidateQueries({ queryKey: ["dag", dagId] });
      qc.invalidateQueries({ queryKey: ["dags"] });
      qc.invalidateQueries({ queryKey: ["dag-spec", dagId] });
      navigate(`/dags/${dag.dag_id}`);
    },
  });

  if (!dagId) return null;

  return (
    <div>
      <Link
        to={`/dags/${dagId}`}
        className="text-sm text-neutral-500 hover:text-neutral-300"
      >
        ← back to {dagId}
      </Link>
      <h1 className="text-2xl font-semibold mt-3 mb-6 font-mono">
        edit <span className="text-emerald-400">{dagId}</span>
      </h1>

      {specQ.isLoading && <div className="text-neutral-500">loading spec…</div>}
      {specQ.error && (
        <div className="border border-rose-900 bg-rose-950/30 rounded p-3 text-sm text-rose-200">
          {String(specQ.error)}
        </div>
      )}
      {specQ.data && (
        <DagForm
          initialSpec={specQ.data}
          mode="edit"
          onSubmit={(spec) => updateM.mutate(spec)}
          submitting={updateM.isPending}
          submitError={updateM.error}
        />
      )}
    </div>
  );
}
