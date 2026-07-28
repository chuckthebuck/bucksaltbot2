import type { ModuleRunItem } from "./types";

export async function fetchFourAwardRuns(options: {
  unique?: boolean;
  limit?: number;
  nonBlank?: boolean;
  scanLimit?: number;
} = {}): Promise<{
  module: string;
  jobs: Array<{ name: string; enabled: boolean }>;
  runs: ModuleRunItem[];
  can_run: boolean;
  limit: number;
  hits: number;
  non_blank: boolean;
  requested_scan_limit: number;
  scan_limit: number;
  scanned: number;
  scan_capped: boolean;
  unique: boolean;
  returned: number;
}> {
  const params = new URLSearchParams();
  params.set("unique", options.unique === false ? "0" : "1");
  const requestedLimit = options.limit || 50;
  if (options.nonBlank) {
    params.set("non_blank", "1");
    params.set("hits", String(requestedLimit));
    params.set("scan_limit", String(options.scanLimit || 50000));
  } else {
    params.set("limit", String(requestedLimit));
  }
  const r = await fetch(`/api/v1/four-award/runs?${params.toString()}`);
  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to fetch 4award runs: ${r.status}`);
  }
  return {
    module: data.module || "four_award",
    jobs: Array.isArray(data.jobs) ? data.jobs : [],
    runs: Array.isArray(data.runs) ? data.runs : [],
    can_run: !!data.can_run,
    limit: Number(data.limit || options.limit || 50),
    hits: Number(data.hits || requestedLimit),
    non_blank: data.non_blank === true,
    requested_scan_limit: Number(data.requested_scan_limit || options.scanLimit || 1000),
    scan_limit: Number(data.scan_limit || options.scanLimit || 1000),
    scanned: Number(data.scanned || 0),
    scan_capped: data.scan_capped === true,
    unique: data.unique !== false,
    returned: Number(data.returned || 0),
  };
}

export async function fetchFourAwardRun(runId: number): Promise<{ run: ModuleRunItem }> {
  const r = await fetch(`/api/v1/four-award/runs/${encodeURIComponent(runId)}`);
  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to fetch 4award run: ${r.status}`);
  }
  return data;
}

export async function queueFourAwardHistoricalDiffTest(payload: {
  diff: string;
  job_name?: string;
}): Promise<{
  module: string;
  job: string;
  run_id: number;
  status: string;
  detail?: string;
}> {
  const r = await fetch("/api/v1/four-award/test-runs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to queue 4award test: ${r.status}`);
  }
  return data;
}
