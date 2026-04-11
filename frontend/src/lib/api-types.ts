export type EvidenceStatus = "supported" | "insufficient_evidence" | "unsupported";

export type Citation = {
  label: string;
  source_type: "database" | "external_web";
  locator: string;
  excerpt?: string | null;
};

export type MetricReference = {
  metric_id: string;
  label: string;
  formula: string;
  unit?: string | null;
};

export type SummaryBlock = {
  kind: "summary";
  title: string;
  body: string;
};

export type TableBlock = {
  kind: "table";
  title: string;
  columns: string[];
  rows: Array<Array<string | number | null>>;
};

export type ChartPoint = {
  label: string;
  value: number;
};

export type ChartBlock = {
  kind: "chart";
  title: string;
  chart_type: string;
  series: ChartPoint[];
};

export type EvidenceNote = {
  title: string;
  detail: string;
};

export type InsufficientEvidenceBlock = {
  kind: "insufficient_evidence";
  title: string;
  detail: string;
  missing_inputs: string[];
  suggestions: string[];
};

export type QueryInterpretation = {
  original_question: string;
  query_class: string;
  entities: string[];
  filters: Record<string, unknown>;
};

export type QueryResponse = {
  status: EvidenceStatus;
  interpretation: QueryInterpretation;
  summaries: SummaryBlock[];
  tables: TableBlock[];
  charts: ChartBlock[];
  metric_references: MetricReference[];
  evidence_notes: EvidenceNote[];
  citations: Citation[];
  insufficiencies: InsufficientEvidenceBlock[];
};

export type PlayerBattingSummary = {
  player_name: string;
  balls_faced: number;
  runs_scored: number;
  dismissals?: number;
  strike_rate?: number | null;
  boundary_percentage?: number | null;
  control_percentage?: number | null;
};

export type PlayerTrendRow = {
  year: number;
  balls_faced: number;
  runs_scored: number;
  control_percentage?: number | null;
};

export type PlayerProfileResponse = {
  player_name: string;
  summary: PlayerBattingSummary | null;
  trend: PlayerTrendRow[];
  suggestions: string[];
};

export type VenueLeaderboardRow = {
  player_name: string;
  deliveries: number;
  runs_conceded: number;
  wickets: number;
  economy_rate?: number | null;
};

export type VenueProfileResponse = {
  venue_name: string;
  bowling_leaderboard: VenueLeaderboardRow[];
};

export type CompareResponse = {
  players: PlayerBattingSummary[];
};
