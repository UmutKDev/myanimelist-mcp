import { label, statusColor } from "../lib/format";

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return (
    <span className="status-badge" style={{ color: statusColor(status) }}>
      <span className="status-dot" style={{ background: statusColor(status) }} />
      {label(status)}
    </span>
  );
}
