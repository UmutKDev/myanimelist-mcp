/** TypeScript mirrors of every structuredContent payload the server emits. */

export type Kind = "anime" | "manga";

export interface SearchResult {
  id: number;
  title: string;
  picture: string | null;
  year: number | null;
  media_type: string | null;
  airing_status?: string | null;
  publishing_status?: string | null;
  mean: number | null;
  num_episodes?: number;
  num_chapters?: number;
  num_volumes?: number;
  genres: string[];
  authors?: string[];
  synopsis: string;
}

export interface SearchPayload {
  view: "search";
  kind: Kind;
  query?: string;
  suggested?: boolean;
  count?: number;
  total_returned?: number;
  offset?: number;
  has_more?: boolean;
  results: SearchResult[];
}

export interface ListEntry {
  id: number;
  title: string;
  picture: string | null;
  year: number | null;
  media_type: string | null;
  airing_status?: string | null;
  publishing_status?: string | null;
  my_status: string | null;
  my_score: number;
  episodes_watched?: number;
  total_episodes?: number;
  chapters_read?: number;
  volumes_read?: number;
  total_chapters?: number;
  total_volumes?: number;
  genres: string[];
  mal_mean: number | null;
  studios?: string[];
  authors?: string[];
  updated_at: string | null;
}

export interface ListPayload {
  view: "list";
  kind: Kind;
  editable: boolean;
  user_name?: string;
  total_returned: number;
  offset: number;
  has_more: boolean;
  entries: ListEntry[];
}

export interface RelatedTitle {
  id: number;
  title: string;
  relation_type: string;
}

export interface Recommendation {
  id: number;
  title: string;
  num_recommendations: number;
}

export interface MyListStatus {
  status?: string;
  score?: number;
  num_episodes_watched?: number;
  num_chapters_read?: number;
  num_volumes_read?: number;
  is_rewatching?: boolean;
  is_rereading?: boolean;
  updated_at?: string;
}

export interface DetailPayload {
  view: "detail";
  kind: Kind;
  id: number;
  title: string;
  picture: string | null;
  picture_large: string | null;
  alternative_titles?: { synonyms?: string[]; en?: string; ja?: string } | null;
  synopsis: string | null;
  mean: number | null;
  rank: number | null;
  popularity: number | null;
  num_list_users: number | null;
  num_scoring_users: number | null;
  media_type: string | null;
  airing_status?: string | null;
  publishing_status?: string | null;
  num_episodes?: number;
  num_chapters?: number;
  num_volumes?: number;
  year: number | null;
  start_date?: string | null;
  end_date?: string | null;
  source?: string | null;
  average_episode_duration_sec?: number | null;
  rating?: string | null;
  genres: string[];
  studios?: string[];
  authors?: string[];
  serialization?: string[];
  related_anime?: RelatedTitle[];
  related_manga?: RelatedTitle[];
  recommendations?: Recommendation[];
  statistics?: { status?: Record<string, number | string>; num_list_users?: number } | null;
  my_list_status?: MyListStatus | null;
}

export interface RankingEntry {
  rank: number | null;
  previous_rank: number | null;
  id: number;
  title: string;
  picture: string | null;
  media_type: string | null;
  mean: number | null;
  num_list_users: number | null;
  genres: string[];
  year?: number | null;
  num_episodes?: number;
  airing_status?: string | null;
  num_chapters?: number;
  publishing_status?: string | null;
  authors?: string[];
}

export interface RankingPayload {
  view: "ranking";
  kind: Kind;
  ranking_type: string;
  total_returned: number;
  offset: number;
  has_more: boolean;
  entries: RankingEntry[];
}

export interface SeasonalPayload {
  view: "seasonal";
  kind: "anime";
  year: number;
  season: string;
  total_returned: number;
  offset: number;
  has_more: boolean;
  entries: RankingEntry[];
}

export interface ProfileData {
  id: number | null;
  name: string | null;
  picture: string | null;
  birthday?: string | null;
  location?: string | null;
  joined_at?: string | null;
  time_zone?: string | null;
  is_supporter?: boolean | null;
  anime_statistics?: Record<string, number> | null;
}

export interface RankedName {
  name: string;
  count: number;
  avg_my_score: number | null;
}

export interface StatsData {
  total_entries: number;
  status_distribution: Record<string, number>;
  scores: {
    scored_count: number;
    mean: number | null;
    median: number | null;
    histogram_1_to_10: Record<string, number>;
  };
  episodes: {
    total_episodes_watched: number;
    estimated_watch_hours: number;
    estimated_watch_days: number;
  };
  top_genres: RankedName[];
  media_type_distribution: Record<string, number>;
  release_decades: Record<string, number>;
  community_comparison: {
    avg_my_score_minus_mal_mean: number | null;
    compared_entries: number;
  };
  top_studios: RankedName[];
  truncated?: boolean;
  warning?: string;
}

export interface DashboardPayload {
  view: "dashboard";
  profile?: ProfileData;
  stats?: StatsData;
}

export interface ScheduleEntry {
  id: number;
  title: string;
  picture: string | null;
  media_type: string | null;
  airing_status: string | null;
  my_score: number;
  episodes_watched: number;
  total_episodes: number;
  broadcast_time: string | null;
}

export interface ScheduleDay {
  day: string; // "monday".."sunday" | "unscheduled"
  entries: ScheduleEntry[];
}

export interface SchedulePayload {
  view: "schedule";
  timezone: string;
  today: string;
  total: number;
  days: ScheduleDay[];
}

export type ViewPayload =
  | SearchPayload
  | ListPayload
  | DetailPayload
  | RankingPayload
  | SeasonalPayload
  | DashboardPayload
  | SchedulePayload;

/** Result shape of the update_my_*_entry tools (used for optimistic edits). */
export interface UpdateResult {
  anime_id?: number;
  manga_id?: number;
  my_list_status?: MyListStatus;
}
