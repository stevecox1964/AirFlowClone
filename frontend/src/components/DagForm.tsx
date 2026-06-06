import { useEffect, useState } from "react";

import { api } from "../api";
import type { DagSpec, ParamSpec, ParamType, PreviewResponse, TaskSpec } from "../types";

const PARAM_TYPES: ParamType[] = ["str", "int", "float", "bool"];

type Mode = "create" | "edit";

interface DagFormProps {
  initialSpec: DagSpec;
  mode: Mode;
  onSubmit: (spec: DagSpec) => void;
  submitting: boolean;
  submitError: Error | null;
}

export default function DagForm({
  initialSpec,
  mode,
  onSubmit,
  submitting,
  submitError,
}: DagFormProps) {
  const [spec, setSpec] = useState<DagSpec>({
    ...initialSpec,
    params: initialSpec.params ?? [],
  });
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);

  // Debounced live preview — backend is single source of truth for templating.
  useEffect(() => {
    let cancelled = false;
    setPreviewing(true);
    const t = setTimeout(async () => {
      try {
        const p = await api.previewDag(toApiSpec(spec));
        if (!cancelled) setPreview(p);
      } catch (e) {
        if (!cancelled) {
          setPreview({
            source: "",
            errors: [{ field: "_", message: String(e) }],
          });
        }
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [spec]);

  const updateTask = (i: number, patch: Partial<TaskSpec>) => {
    setSpec((s) => ({
      ...s,
      tasks: s.tasks.map((t, idx) => (idx === i ? { ...t, ...patch } : t)),
    }));
  };
  const addTask = () => {
    setSpec((s) => ({
      ...s,
      tasks: [
        ...s.tasks,
        { task_id: `task_${s.tasks.length + 1}`, depends_on: [], body: "" },
      ],
    }));
  };
  const removeTask = (i: number) => {
    setSpec((s) => {
      const removed = s.tasks[i].task_id;
      return {
        ...s,
        tasks: s.tasks
          .filter((_, idx) => idx !== i)
          .map((t) => ({ ...t, depends_on: t.depends_on.filter((d) => d !== removed) })),
      };
    });
  };
  const addParam = () => {
    setSpec((s) => ({
      ...s,
      params: [
        ...s.params,
        { name: `param_${s.params.length + 1}`, type: "str", default: "", required: false },
      ],
    }));
  };
  const updateParam = (i: number, patch: Partial<ParamSpec>) => {
    setSpec((s) => ({
      ...s,
      params: s.params.map((p, idx) => (idx === i ? { ...p, ...patch } : p)),
    }));
  };
  const removeParam = (i: number) => {
    setSpec((s) => ({ ...s, params: s.params.filter((_, idx) => idx !== i) }));
  };

  const toggleDep = (i: number, depId: string) => {
    const task = spec.tasks[i];
    const next = task.depends_on.includes(depId)
      ? task.depends_on.filter((d) => d !== depId)
      : [...task.depends_on, depId];
    updateTask(i, { depends_on: next });
  };

  const hasErrors = (preview?.errors.length ?? 0) > 0;
  const canSubmit = !hasErrors && spec.dag_id.trim().length > 0 && !submitting;
  const submitLabel = mode === "create" ? "create DAG" : "save changes";
  const pendingLabel = mode === "create" ? "creating…" : "saving…";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* LEFT: form */}
      <div className="space-y-4">
        <Field label="dag_id" hint={
          mode === "edit"
            ? "renames not supported — delete the file and recreate if you need a new id"
            : "valid Python identifier; becomes the filename"
        }>
          <input
            value={spec.dag_id}
            onChange={(e) => setSpec({ ...spec, dag_id: e.target.value })}
            placeholder="my_dag"
            readOnly={mode === "edit"}
            className={`input font-mono ${mode === "edit" ? "opacity-60 cursor-not-allowed" : ""}`}
          />
        </Field>
        <Field label="description" hint="optional one-liner">
          <input
            value={spec.description ?? ""}
            onChange={(e) => setSpec({ ...spec, description: e.target.value })}
            placeholder="What this DAG does"
            className="input"
          />
        </Field>
        <Field label="schedule" hint="cron string, e.g. '0 9 * * *' — leave empty for manual-only">
          <input
            value={spec.schedule ?? ""}
            onChange={(e) => setSpec({ ...spec, schedule: e.target.value })}
            placeholder="*/5 * * * *"
            className="input font-mono"
          />
        </Field>

        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm uppercase tracking-wide text-neutral-500">
              run params
            </h2>
            <button
              onClick={addParam}
              className="text-xs px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800"
            >
              + add param
            </button>
          </div>
          {spec.params.length === 0 ? (
            <p className="text-xs text-neutral-600">
              none — this DAG takes no inputs at trigger time. Tasks can still read{" "}
              <span className="font-mono">Variable.get(...)</span> and{" "}
              <span className="font-mono">Connection.get(...)</span>.
            </p>
          ) : (
            <ol className="space-y-2">
              {spec.params.map((p, i) => (
                <li
                  key={i}
                  className="border border-neutral-800 bg-neutral-900/40 rounded p-3 flex flex-wrap items-end gap-2"
                >
                  <div className="flex-1 min-w-[120px]">
                    <div className="text-xs text-neutral-500 mb-1">name</div>
                    <input
                      value={p.name}
                      onChange={(e) => updateParam(i, { name: e.target.value })}
                      placeholder="param_name"
                      className="input font-mono w-full"
                    />
                  </div>
                  <div className="w-24">
                    <div className="text-xs text-neutral-500 mb-1">type</div>
                    <select
                      value={p.type}
                      onChange={(e) => updateParam(i, { type: e.target.value as ParamType })}
                      className="input font-mono w-full"
                    >
                      {PARAM_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex-1 min-w-[120px]">
                    <div className="text-xs text-neutral-500 mb-1">default</div>
                    <input
                      value={p.default == null ? "" : String(p.default)}
                      onChange={(e) => updateParam(i, { default: e.target.value })}
                      placeholder={p.required ? "(required)" : "(none)"}
                      className="input font-mono w-full"
                    />
                  </div>
                  <label className="flex items-center gap-1 text-xs text-neutral-400 pb-2">
                    <input
                      type="checkbox"
                      checked={!!p.required}
                      onChange={(e) => updateParam(i, { required: e.target.checked })}
                    />
                    required
                  </label>
                  <button
                    onClick={() => removeParam(i)}
                    className="text-xs px-2 py-1 mb-0.5 rounded text-rose-300 border border-rose-900/60 hover:bg-rose-950/40"
                  >
                    remove
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm uppercase tracking-wide text-neutral-500">tasks</h2>
            <button
              onClick={addTask}
              className="text-xs px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800"
            >
              + add task
            </button>
          </div>
          <ol className="space-y-3">
            {spec.tasks.map((t, i) => (
              <li
                key={i}
                className="border border-neutral-800 bg-neutral-900/40 rounded p-3 space-y-2"
              >
                <div className="flex gap-2 items-start">
                  <input
                    value={t.task_id}
                    onChange={(e) => updateTask(i, { task_id: e.target.value })}
                    placeholder="task_id"
                    className="input font-mono flex-1"
                  />
                  {spec.tasks.length > 1 && (
                    <button
                      onClick={() => removeTask(i)}
                      className="text-xs px-2 py-1 rounded text-rose-300 border border-rose-900/60 hover:bg-rose-950/40"
                    >
                      remove
                    </button>
                  )}
                </div>

                {spec.tasks.length > 1 && (
                  <div>
                    <div className="text-xs text-neutral-500 mb-1">depends on:</div>
                    <div className="flex flex-wrap gap-1">
                      {spec.tasks
                        .filter((other, idx) => idx !== i && other.task_id)
                        .map((other) => {
                          const on = t.depends_on.includes(other.task_id);
                          return (
                            <button
                              key={other.task_id}
                              onClick={() => toggleDep(i, other.task_id)}
                              className={`text-xs font-mono px-2 py-0.5 rounded border transition ${
                                on
                                  ? "bg-emerald-900/40 border-emerald-700 text-emerald-300"
                                  : "border-neutral-700 text-neutral-400 hover:border-neutral-500"
                              }`}
                            >
                              {other.task_id}
                            </button>
                          );
                        })}
                      {spec.tasks.filter((_, idx) => idx !== i).length === 0 && (
                        <span className="text-xs text-neutral-600">
                          (no other tasks)
                        </span>
                      )}
                    </div>
                  </div>
                )}

                <div>
                  <div className="text-xs text-neutral-500 mb-1">
                    body (Python — upstream outputs by name, plus{" "}
                    <span className="font-mono">params</span>,{" "}
                    <span className="font-mono">Variable</span>,{" "}
                    <span className="font-mono">Connection</span>):
                  </div>
                  <textarea
                    value={t.body}
                    onChange={(e) => updateTask(i, { body: e.target.value })}
                    rows={4}
                    spellCheck={false}
                    className="input font-mono text-sm w-full resize-y"
                    placeholder="return some_value"
                  />
                </div>
              </li>
            ))}
          </ol>
        </div>

        {hasErrors && (
          <div className="border border-rose-900 bg-rose-950/30 rounded p-3">
            <div className="text-sm font-semibold text-rose-300 mb-1">
              validation errors
            </div>
            <ul className="text-xs text-rose-200 space-y-0.5 font-mono">
              {preview!.errors.map((e, i) => (
                <li key={i}>
                  <span className="text-rose-400">{e.field}</span> — {e.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {submitError && (
          <div className="border border-rose-900 bg-rose-950/30 rounded p-3 text-sm text-rose-200">
            {String(submitError)}
          </div>
        )}

        <button
          onClick={() => onSubmit(toApiSpec(spec))}
          disabled={!canSubmit}
          className="w-full py-2.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed font-semibold"
        >
          {submitting ? pendingLabel : submitLabel}
        </button>
      </div>

      {/* RIGHT: preview */}
      <div className="lg:sticky lg:top-24 lg:self-start">
        <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2 flex items-center justify-between">
          <span>generated dags/{spec.dag_id || "<dag_id>"}.py</span>
          {previewing && <span className="text-neutral-600 normal-case">previewing…</span>}
        </div>
        <pre className="text-xs font-mono bg-neutral-950 border border-neutral-800 rounded p-4 overflow-auto max-h-[70vh] whitespace-pre">
          {preview?.source || "(empty)"}
        </pre>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs uppercase tracking-wide text-neutral-500 mb-1">
        {label}
      </label>
      {children}
      {hint && <div className="text-xs text-neutral-600 mt-1">{hint}</div>}
    </div>
  );
}

// API expects null (not empty string) for omitted optional fields.
function toApiSpec(spec: DagSpec): DagSpec {
  return {
    ...spec,
    dag_id: spec.dag_id.trim(),
    description: spec.description?.trim() ? spec.description.trim() : null,
    schedule: spec.schedule?.trim() ? spec.schedule.trim() : null,
    params: spec.params.map((p) => ({
      name: p.name.trim(),
      type: p.type,
      default: coerceDefault(p.type, p.default),
      required: !!p.required,
    })),
    tasks: spec.tasks.map((t) => ({
      task_id: t.task_id.trim(),
      depends_on: t.depends_on,
      body: t.body,
    })),
  };
}

// Defaults are edited as text; coerce to the declared type so the stored spec (and the
// generated .py) carry a real int/float/bool. Unparseable values pass through as-is so
// the backend's validation surfaces a clear error rather than us swallowing it.
function coerceDefault(
  type: ParamType,
  raw: ParamSpec["default"],
): ParamSpec["default"] {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (s === "") return null;
  if (type === "int") {
    return /^-?\d+$/.test(s) ? parseInt(s, 10) : s;
  }
  if (type === "float") {
    const n = Number(s);
    return Number.isFinite(n) ? n : s;
  }
  if (type === "bool") {
    const l = s.toLowerCase();
    if (["true", "1", "yes", "on"].includes(l)) return true;
    if (["false", "0", "no", "off"].includes(l)) return false;
    return s;
  }
  return s;
}
