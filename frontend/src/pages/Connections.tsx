import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import type { ConnectionIn } from "../types";

interface FormState {
  conn_id: string;
  conn_type: string;
  host: string;
  port: string; // text input; coerced to number on submit
  login: string;
  password: string;
  extra: string;
  description: string;
}

const BLANK: FormState = {
  conn_id: "",
  conn_type: "",
  host: "",
  port: "",
  login: "",
  password: "",
  extra: "",
  description: "",
};

export default function Connections() {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(BLANK);
  const [editing, setEditing] = useState<string | null>(null);

  const listQ = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  const saveM = useMutation({
    mutationFn: (f: FormState) => {
      const body: ConnectionIn = {
        conn_type: f.conn_type.trim() || null,
        host: f.host.trim() || null,
        port: f.port.trim() ? Number(f.port) : null,
        login: f.login.trim() || null,
        // blank password on edit = leave unchanged; on create = no password
        password: f.password === "" ? null : f.password,
        extra: f.extra.trim() || null,
        description: f.description.trim() || null,
      };
      return api.upsertConnection(f.conn_id, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      setForm(BLANK);
      setEditing(null);
    },
  });

  const deleteM = useMutation({
    mutationFn: (connId: string) => api.deleteConnection(connId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
  });

  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  return (
    <div>
      <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-300">
        ← all DAGs
      </Link>
      <h1 className="text-2xl font-semibold mt-3 mb-1">connections</h1>
      <p className="text-sm text-neutral-500 mb-6">
        structured credentials read by tasks via{" "}
        <span className="font-mono">Connection.get('conn_id')</span> (
        <span className="font-mono">.host</span>,{" "}
        <span className="font-mono">.password</span>, …). The password is treated as a
        secret: never returned here, kept off disk, redacted from logs.
      </p>

      <div className="border border-neutral-800 bg-neutral-900/40 rounded p-4 mb-6 space-y-3">
        <div className="text-sm font-semibold">
          {editing ? `edit "${editing}"` : "add connection"}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input
            value={form.conn_id}
            onChange={(e) => set({ conn_id: e.target.value })}
            placeholder="conn_id (identifier)"
            readOnly={!!editing}
            className={`input font-mono ${editing ? "opacity-60 cursor-not-allowed" : ""}`}
          />
          <input
            value={form.conn_type}
            onChange={(e) => set({ conn_type: e.target.value })}
            placeholder="conn_type (e.g. postgres)"
            className="input font-mono"
          />
          <input
            value={form.host}
            onChange={(e) => set({ host: e.target.value })}
            placeholder="host"
            className="input font-mono"
          />
          <input
            value={form.port}
            onChange={(e) => set({ port: e.target.value })}
            placeholder="port"
            inputMode="numeric"
            className="input font-mono"
          />
          <input
            value={form.login}
            onChange={(e) => set({ login: e.target.value })}
            placeholder="login"
            className="input font-mono"
          />
          <input
            value={form.password}
            onChange={(e) => set({ password: e.target.value })}
            type="password"
            placeholder={editing ? "(leave blank to keep)" : "password"}
            className="input font-mono"
          />
        </div>
        <input
          value={form.extra}
          onChange={(e) => set({ extra: e.target.value })}
          placeholder='extra (JSON, e.g. {"sslmode":"require"})'
          className="input font-mono w-full"
        />
        <input
          value={form.description}
          onChange={(e) => set({ description: e.target.value })}
          placeholder="description (optional)"
          className="input w-full"
        />
        <div className="flex justify-end gap-2">
          {editing && (
            <button
              onClick={() => {
                setForm(BLANK);
                setEditing(null);
              }}
              className="px-3 py-1.5 rounded border border-neutral-700 hover:bg-neutral-800 text-sm"
            >
              cancel
            </button>
          )}
          <button
            onClick={() => saveM.mutate(form)}
            disabled={!form.conn_id.trim() || saveM.isPending}
            className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold"
          >
            {saveM.isPending ? "saving…" : editing ? "save" : "add"}
          </button>
        </div>
        {saveM.error && (
          <div className="text-xs text-rose-300">{String(saveM.error)}</div>
        )}
      </div>

      <div className="border border-neutral-800 rounded divide-y divide-neutral-800 bg-neutral-900/30">
        {listQ.data?.length === 0 && (
          <div className="p-4 text-sm text-neutral-500">no connections yet.</div>
        )}
        {listQ.data?.map((c) => (
          <div key={c.conn_id} className="p-3 flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-emerald-300">{c.conn_id}</span>
                {c.conn_type && (
                  <span className="text-xs text-neutral-500">{c.conn_type}</span>
                )}
                {c.has_password && (
                  <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-800">
                    password set
                  </span>
                )}
              </div>
              <div className="font-mono text-sm text-neutral-400 truncate">
                {[c.login && `${c.login}@`, c.host, c.port && `:${c.port}`]
                  .filter(Boolean)
                  .join("") || "(no host)"}
              </div>
              {c.description && (
                <div className="text-xs text-neutral-600">{c.description}</div>
              )}
            </div>
            <button
              onClick={() => {
                setEditing(c.conn_id);
                setForm({
                  conn_id: c.conn_id,
                  conn_type: c.conn_type ?? "",
                  host: c.host ?? "",
                  port: c.port != null ? String(c.port) : "",
                  login: c.login ?? "",
                  password: "",
                  extra: c.extra ?? "",
                  description: c.description ?? "",
                });
              }}
              className="text-xs px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800"
            >
              edit
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Delete connection "${c.conn_id}"?`))
                  deleteM.mutate(c.conn_id);
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
