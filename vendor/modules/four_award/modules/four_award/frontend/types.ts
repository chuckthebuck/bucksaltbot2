export interface ModuleRunItem {
  id: number;
  module_name: string;
  job_name: string;
  status: string;
  trigger_type: string;
  triggered_by?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  error?: string | null;
  payload?: Record<string, unknown>;
  result?: {
    status?: string;
    run_kind?: string;
    has_nominations?: boolean;
    nomination_count?: number;
    processed_count?: number;
    dry_run?: boolean;
    approved?: number;
    failed?: number;
    manual?: number;
    dry_run_edits?: Array<{
      title?: string;
      summary?: string;
      before_chars?: number;
      after_chars?: number;
      delta_chars?: number;
      diff?: string;
    }>;
    dry_run_report?: {
      published?: {
        title?: string;
        saved?: boolean;
      } | null;
      wikitext?: string;
    };
  };
  created_at?: string | null;
}
