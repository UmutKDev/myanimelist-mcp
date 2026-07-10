export function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="empty-state" role="status">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 2.5l2.4 6.1 6.6.4-5.1 4.2 1.7 6.4L12 16l-5.6 3.6 1.7-6.4L3 9l6.6-.4L12 2.5z"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </svg>
      <p>{message}</p>
      {hint && <p className="empty-hint">{hint}</p>}
    </div>
  );
}
