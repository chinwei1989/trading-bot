export type RangeKey = "Today" | "7D" | "30D" | "3M" | "1Y" | "All";

export interface PerformancePoint {
  timestamp: string;
  equity: number;
  pnl: number;
  pnl_pct: number;
  cum_pct: number;
}

export interface PerformanceRange {
  range: RangeKey;
  granularity: "intraday" | "daily";
  points: PerformancePoint[];
  period_pnl: number;
  period_return: number;
  best: number;
  worst: number;
  latest_equity: number;
  observations: number;
  initial_total: number;
}

export interface Position {
  lane: string;
  asset: string;
  side: "long" | "short";
  qty: number;
  entry: number | null;
  cost: number | null;
  last_price: number | null;
  value: number;
  weight: number;
  pnl: number | null;
  pnl_pct: number | null;
}

export interface Lane {
  lane: string;
  equity: number;
  starting_cash: number;
  pnl: number;
  pnl_pct: number;
  positions: number;
  color: string;
}

export interface AIGist {
  headline?: string;
  summary?: string;
  bullets?: string[];
  created_at?: string;
  data_as_of?: string;
  model?: string;
  confidence?: number;
  method?: string;
}

export interface GateFailure {
  [key: string]: unknown;
}

export interface Readiness {
  status?: string;
  paper_ready?: boolean;
  paper_days?: number;
  target_paper_days?: number;
  health_status?: string;
  host_status?: string;
  live_gate?: string;
  options_live_gate?: string;
  options_status?: string;
  blockers?: string[];
  host_blockers?: string[];
  live_gate_failed?: string[];
  options_live_gate_failed?: string[];
  [key: string]: unknown;
}

export interface DashboardData {
  generated_at: string;
  data_as_of: string;
  source: string;
  ai_gist: AIGist | null;
  readiness: Readiness;
  portfolio: {
    gross_usd: number;
    net_usd: number;
    open_pnl_usd: number;
    open_pnl_pct: number;
    lane_pnl_usd: number;
    lane_pnl_pct: number;
    positions: number;
    active_lanes: number;
    paper_accounts: number;
  };
  lanes: Lane[];
  positions: Position[];
  top_positions: Position[];
  sui: { qty: number; value_usd: number; pnl_usd: number };
  options_holdings: { open_contracts: number; value_usd: number };
  options: {
    evidence: Record<string, unknown>;
    live_gate: Record<string, unknown>;
    lanes: Array<{
      lane: string;
      status: string;
      equity: number | null;
      as_of: string | null;
      directions: Record<string, string>;
    }>;
  };
  performance: {
    ranges: Record<RangeKey, PerformanceRange>;
    lane_curves: Array<{
      lane: string;
      color: string;
      initial: number;
      points: Array<{ timestamp: string; equity: number }>;
    }>;
  };
}
