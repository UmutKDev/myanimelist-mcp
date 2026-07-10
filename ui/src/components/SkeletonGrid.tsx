export function SkeletonGrid({ count = 8, label }: { count?: number; label?: string }) {
  return (
    <div className="skeleton-root" aria-busy="true" aria-label={label ?? "Loading"}>
      {label && <div className="eyebrow skeleton-label">{label}</div>}
      <div className="card-grid">
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className="skeleton-card">
            <div className="skeleton-cover shimmer" />
            <div className="skeleton-line shimmer" />
            <div className="skeleton-line skeleton-line-short shimmer" />
          </div>
        ))}
      </div>
    </div>
  );
}
