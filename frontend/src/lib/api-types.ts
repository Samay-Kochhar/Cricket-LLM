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

export type EvidenceQueryBlock = {
  kind: "evidence_query";
  title: string;
  description: string;
  sql: string;
  parameters: Array<string | number | null>;
  table: TableBlock;
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

export type VisualCoverage = {
  total_balls: number;
  covered_balls: number;
  coverage_percentage: number;
  detail: string;
};

export type PitchMapCell = {
  line: string;
  length: string;
  balls: number;
  runs: number;
  strike_rate?: number | null;
  dismissals: number;
  boundary_balls: number;
  dot_balls: number;
  singles: number;
  doubles: number;
  triples: number;
  fours: number;
  sixes: number;
  wicket_balls: number;
  control_percentage?: number | null;
};

export type PitchMapBlock = {
  kind: "pitch_map";
  handedness?: string | null;
  coverage: VisualCoverage;
  cells: PitchMapCell[];
};

export type WagonWheelPoint = {
  x: number;
  y: number;
  outcome: "dot" | "single" | "double" | "triple" | "four" | "six" | "wicket";
  runs: number;
};

export type WagonWheelSector = {
  zone_id: number;
  label: string;
  balls: number;
  runs: number;
  dismissals: number;
  strike_rate?: number | null;
  run_share_percentage: number;
  singles: number;
  doubles: number;
  triples: number;
  fours: number;
  sixes: number;
  wicket_balls: number;
};

export type WagonWheelBlock = {
  kind: "wagon_wheel";
  handedness?: string | null;
  coverage: VisualCoverage;
  points: WagonWheelPoint[];
  sectors: WagonWheelSector[];
};

export type ShotTypeMetric = {
  shot: string;
  balls: number;
  runs: number;
  run_share_percentage?: number | null;
  control_percentage?: number | null;
  false_shot_percentage?: number | null;
  dismissal_rate?: number | null;
  boundary_percentage?: number | null;
};

export type ShotProfileBlock = {
  kind: "shot_profile";
  coverage: VisualCoverage;
  metrics: ShotTypeMetric[];
};

export type FieldZoneMetric = {
  zone_id: number;
  label: string;
  balls: number;
  runs: number;
  dismissals: number;
  strike_rate?: number | null;
  run_share_percentage: number;
  singles: number;
  doubles: number;
  triples: number;
  fours: number;
  sixes: number;
  wicket_balls: number;
};

export type FieldZoneBlock = {
  kind: "field_zones";
  handedness?: string | null;
  coverage: VisualCoverage;
  zones: FieldZoneMetric[];
};

export type RadarMetric = {
  label: string;
  subject: number;
  benchmark: number;
};

export type RadarBlock = {
  kind: "radar";
  subject_label: string;
  benchmark_label: string;
  metrics: RadarMetric[];
};

export type VisualPayload = {
  pitch_map?: PitchMapBlock | null;
  wagon_wheel?: WagonWheelBlock | null;
  shot_profile?: ShotProfileBlock | null;
  field_zones?: FieldZoneBlock | null;
  radar?: RadarBlock | null;
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
  visuals?: VisualPayload | null;
  metric_references: MetricReference[];
  evidence_queries: EvidenceQueryBlock[];
  evidence_notes: EvidenceNote[];
  citations: Citation[];
  insufficiencies: InsufficientEvidenceBlock[];
};

export type MatchupPageResponse = {
  matchup: QueryResponse;
  baseline: QueryResponse;
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
  visuals?: VisualPayload | null;
  coverage_notes?: EvidenceNote[];
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

export type ChatHistoryTurn = {
  role: string;
  content: string;
};

export type ClarificationOption = {
  label: string;
  message: string;
};

export type ConversationState = {
  players: string[];
  operation?: string | null;
  metric?: string | null;
  group_by: string[];
  comparison_participants: string[];
  comparison_metrics: string[];
  filters: Record<string, unknown>;
};

export type ChatReply = {
  mode: string;
  message: string;
  query_response?: QueryResponse | null;
  suggestions: string[];
  clarification_options?: ClarificationOption[];
  conversation_state?: ConversationState | null;
  resolved_input?: string | null;
  resolution_note?: string | null;
  activity_trace: string[];
};

export type TeamSquadPlayer = {
  player_name: string;
  role_summary: string;
  bat_hand?: string | null;
  bowl_style?: string | null;
};

export type WorkbenchSearchResponse =
  | {
      kind: "player_result";
      trace_id: string;
      trace: string[];
      query: string;
      player_name: string;
      role_summary: string;
      query_response: QueryResponse;
    }
  | {
      kind: "team_year_required";
      trace_id: string;
      trace: string[];
      team_name: string;
      available_years: number[];
    }
  | {
      kind: "team_squad";
      trace_id: string;
      trace: string[];
      team_name: string;
      year: number;
      players: TeamSquadPlayer[];
    }
  | {
      kind: "unsupported" | "empty";
      trace_id: string;
      trace: string[];
      message?: string;
    };
