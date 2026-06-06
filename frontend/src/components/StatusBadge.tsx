import type { RunStatus, TaskStatus } from "../types";

const STATUS_STYLES: Record<TaskStatus | RunStatus, string> = {
  pending: "bg-neutral-700/40 text-neutral-300 border-neutral-700",
  queued: "bg-neutral-700/40 text-neutral-300 border-neutral-700",
  running: "bg-sky-700/40 text-sky-200 border-sky-700 animate-pulse",
  success: "bg-emerald-700/40 text-emerald-200 border-emerald-700",
  failed: "bg-rose-700/40 text-rose-200 border-rose-700",
  skipped: "bg-neutral-700/40 text-neutral-400 border-neutral-700",
  upstream_failed: "bg-amber-700/40 text-amber-200 border-amber-700",
};

export default function StatusBadge({
  status,
}: {
  status: TaskStatus | RunStatus;
}) {
  const cls = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-mono ${cls}`}
    >
      {status}
    </span>
  );
}
