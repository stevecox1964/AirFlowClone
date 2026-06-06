import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import type { VariableIn } from "../types";

const BLANK: VariableIn & { key: string } = {
  key: "",
  value: "",
  is_secret: false,
  description: "",
};

export default function Variables() {
  const qc = useQueryClient();
  const [form, setForm] = useState<VariableIn & { key: string }>(BLANK);
  const [editingKey, setEditingKey] = useState<string | null>(null);

  const listQ = useQuery({ queryKey: ["variables"], queryFn: api.listVariables });

  const saveM = useMutation({
    mutationFn: (f: VariableIn & { key: string }) =>
      api.upsertVariable(f.key, {
        value: f.value,
        is_secret: f.is_secret,
        description: f.description?.trim() ? f.description : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["variables"] });
      setForm(BLANK);
      setEditingKey(null);
    },
  });

  const deleteM = useMutation({
    mutationFn: (key: string) => api.deleteVariable(key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["variables"] }),
  });

  const startEdit = (key: string, is_secret: boolean, description: string | null) => {
    // Secret values are never sent back to the client — re-enter to change one.
    setEditingKey(key);
    setForm({ key, value: "", is_secret, description: description ?? "" });
  };

  return (
    <div>
      <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-300">
        ← all DAGs
      </Link>
      <h1 className="text-2xl font-semibold mt-3 mb-1">variables</h1>
      <p className="text-sm text-neutral-500 mb-6">
        global key/value config read by tasks via{" "}
        <span className="font-mono">Variable.get('key')</span>. Secret values are masked
        here, kept off disk, and redacted from logs.
      </p>

      <div className="border border-neutral-800 bg-neutral-900/40 rounded p-4 mb-6 space-y-3">
        <div className="text-sm font-semibold">
          {editingKey ? `edit "${editingKey}"` : "add variable"}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value })}
            placeholder="key (identifier)"
            readOnly={!!editingKey}
            className={`input font-mono ${editingKey ? "opacity-60 cursor-not-allowed" : ""}`}
          />
          <input
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
            placeholder={
              editingKey && form.is_secret ? "new secret value" : "value"
            }
            className="input font-mono"
          />
        </div>
        <input
          value={form.description ?? ""}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="description (optional)"
          className="input w-full"
        />
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-neutral-400">
            <input
              type="checkbox"
              checked={form.is_secret}
              onChange={(e) => setForm({ ...form, is_secret: e.target.checked })}
            />
            secret (masked + redacted)
          </label>
          <div className="flex gap-2">
            {editingKey && (
              <button
                onClick={() => {
                  setForm(BLANK);
                  setEditingKey(null);
                }}
                className="px-3 py-1.5 rounded border border-neutral-700 hover:bg-neutral-800 text-sm"
              >
                cancel
              </button>
            )}
            <button
              onClick={() => saveM.mutate(form)}
              disabled={!form.key.trim() || saveM.isPending}
              className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold"
            >
              {saveM.isPending ? "saving…" : editingKey ? "save" : "add"}
            </button>
          </div>
        </div>
        {saveM.error && (
          <div className="text-xs text-rose-300">{String(saveM.error)}</div>
        )}
      </div>

      <div className="border border-neutral-800 rounded divide-y divide-neutral-800 bg-neutral-900/30">
        {listQ.data?.length === 0 && (
          <div className="p-4 text-sm text-neutral-500">no variables yet.</div>
        )}
        {listQ.data?.map((v) => (
          <div key={v.key} className="p-3 flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-emerald-300">{v.key}</span>
                {v.is_secret && (
                  <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-800">
                    secret
                  </span>
                )}
              </div>
              <div className="font-mono text-sm text-neutral-400 truncate">
                {v.is_secret ? "••••••••" : v.value}
              </div>
              {v.description && (
                <div className="text-xs text-neutral-600">{v.description}</div>
              )}
            </div>
            <button
              onClick={() => startEdit(v.key, v.is_secret, v.description)}
              className="text-xs px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800"
            >
              edit
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Delete variable "${v.key}"?`)) deleteM.mutate(v.key);
              }}
              className="text-xs px-2 py-1 rounded border border-rose-900/60 text-rose-300 hover:bg-rose-950/40"
            >
              delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
