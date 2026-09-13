export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface Run {
  run_id: string
  trigger_type: string
  status: RunStatus
  progress_pct: number
  current_step: string
  edition_date: string
  started_at?: string
  finished_at?: string
  error?: string
}

export interface Dashboard {
  counts: { sources: number; events: number; items: number; editions: number }
  last_run: Run | null
  last_edition: any
  unhealthy_sources: number
  scheduler: {
    running: boolean
    paused: boolean
    schedule: string
    timezone: string
    next_run_time?: string
    active_workers: string[]
  }
  service: { version: string; git_sha: string; started_at: string; recovered_runs: number }
  agent: { binary: string; provider: string; model: string; thinking: string }
}

export interface EventRecord {
  id: number
  event_key: string
  entity: string
  subject: string
  event_type: string
  title_zh: string
  summary_zh: string
  why_it_matters_zh: string
  importance: number
  confidence: string
  first_seen_at: string
  last_seen_at: string
  status: string
  source_name?: string
  source_url?: string
  source_count: number
  claim_count: number
  last_edition?: string
  claims: { claim_key: string; claim_value: string; material: number }[]
}

export interface Edition {
  id: number
  edition_date: string
  status: string
  title: string
  overview: string
  item_count: number
  html_path?: string
  updated_at: string
}

export interface RuntimeSettings {
  schedule: string
  timezone: string
  max_items: number
  lookback_hours: number
  scheduler_paused: boolean
  agent_binary: string
  agent_provider: string
  agent_model: string
  agent_thinking: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  focus_profile: string
  report_rebuild_requested: boolean
}

export interface Source {
  id: string
  name: string
  kind: string
  url: string
  tier: string
  enabled: boolean
  config?: {
    quality?: {
      min_score?: number
      min_event_importance?: number
      min_content_chars?: number
      min_summary_chars?: number
      min_stars?: number
      min_description_chars?: number
      min_documentation_signals?: number
      require_license?: boolean
    }
  }
  quality_last_run?: { examined: number; accepted: number; rejected: number; unassessed: number }
  last_success_at?: string
  last_failure_at?: string
  consecutive_failures: number
  last_error?: string
}
