import { label } from "../lib/format";

export interface SortOption {
  value: string;
  text: string;
}

/** Filter/search/sort toolbar for the list browser (all client-side). */
export function Toolbar({
  statuses,
  statusCounts,
  activeStatus,
  onStatus,
  search,
  onSearch,
  sort,
  sortOptions,
  onSort,
}: {
  statuses: readonly string[];
  statusCounts: Record<string, number>;
  activeStatus: string | null;
  onStatus: (status: string | null) => void;
  search: string;
  onSearch: (value: string) => void;
  sort: string;
  sortOptions: SortOption[];
  onSort: (value: string) => void;
}) {
  const total = Object.values(statusCounts).reduce((a, b) => a + b, 0);
  return (
    <div className="toolbar glass">
      <div className="toolbar-tabs" role="tablist" aria-label="Filter by status">
        <button
          role="tab"
          aria-selected={activeStatus === null}
          className={`tab${activeStatus === null ? " is-active" : ""}`}
          onClick={() => onStatus(null)}
        >
          All <span className="num tab-count">{total}</span>
        </button>
        {statuses.map((status) => (
          <button
            key={status}
            role="tab"
            aria-selected={activeStatus === status}
            className={`tab${activeStatus === status ? " is-active" : ""}`}
            onClick={() => onStatus(status)}
          >
            {label(status)}
            <span className="num tab-count">{statusCounts[status] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="toolbar-controls">
        <input
          type="search"
          className="toolbar-search"
          placeholder="Filter titles…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          aria-label="Filter titles"
        />
        <select
          className="toolbar-sort"
          value={sort}
          onChange={(e) => onSort(e.target.value)}
          aria-label="Sort by"
        >
          {sortOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.text}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
