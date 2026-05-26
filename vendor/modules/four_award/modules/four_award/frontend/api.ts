import type { ModuleRunItem } from "./types";

export async function fetchFourAwardRuns(options: {
  unique?: boolean;
  limit?: number;
} = {}): Promise<{
  module: string;
  jobs: Array<{ name: string; enabled: boolean }>;
  runs: ModuleRunItem[];
  can_run: boolean;
  limit: number;
  unique: boolean;
  returned: number;
}> {
  const params = new URLSearchParams();
  params.set("unique", options.unique === false ? "0" : "1");
  if (options.limit) {
    params.set("limit", String(options.limit));
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
