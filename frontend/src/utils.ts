export function formatRelative(iso: string | null): string | null {
  if (!iso) return null;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return null;
  const diffSec = Math.round((target - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  const suffix = diffSec >= 0 ? "from now" : "ago";

  if (abs < 60) return `${abs}s ${suffix}`;
  if (abs < 3600) {
    const m = Math.floor(abs / 60);
    const s = abs % 60;
    return s ? `${m}m ${s}s ${suffix}` : `${m}m ${suffix}`;
  }
  if (abs < 86400) {
    const h = Math.floor(abs / 3600);
    const m = Math.floor((abs % 3600) / 60);
    return m ? `${h}h ${m}m ${suffix}` : `${h}h ${suffix}`;
  }
  const d = Math.floor(abs / 86400);
  const h = Math.floor((abs % 86400) / 3600);
  return h ? `${d}d ${h}h ${suffix}` : `${d}d ${suffix}`;
}
