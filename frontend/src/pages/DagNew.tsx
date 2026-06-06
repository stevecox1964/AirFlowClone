import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import DagForm from "../components/DagForm";
import type { DagSpec } from "../types";

const EMPTY_SPEC: DagSpec = {
  dag_id: "",
  description: "",
  schedule: "",
  params: [],
  tasks: [{ task_id: "first_task", depends_on: [], body: "return 'hello'" }],
};

export default function DagNew() {
  const navigate = useNavigate();
  const createM = useMutation({
    mutationFn: (spec: DagSpec) => api.createDag(spec),
    onSuccess: (dag) => navigate(`/dags/${dag.dag_id}`),
  });

  return (
    <div>
      <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-300">
        ← all DAGs
      </Link>
      <h1 className="text-2xl font-semibold mt-3 mb-6">new DAG</h1>
      <DagForm
        initialSpec={EMPTY_SPEC}
        mode="create"
        onSubmit={(spec) => createM.mutate(spec)}
        submitting={createM.isPending}
        submitError={createM.error}
      />
    </div>
  );
}
