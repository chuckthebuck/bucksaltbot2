// TYPES

export interface JobRow {
  id: number;
  status: string;
  progressText: string;
  progressPct: number;
  created: string;
  total?: number;
  completed?: number;
  failed?: number;
  items?: CreateJobItem[];
}

export interface CreateJobItem {
  title: string;
  user: string;
  summary: string | null;
}

export interface QueueProps {
  username: string | null;
  is_maintainer: boolean;
  jobs: JobRow[];
}

// ------------------------
// INITIAL PROPS
// ------------------------

export function getInitialProps(): QueueProps {
  const el = document.getElementById("rollback-queue-props");

  if (!el?.textContent) {
    return { username: null, is_maintainer: false, jobs: [] };
  }

  try {
    const parsed = JSON.parse(el.textContent);

    return {
      username: parsed.username ?? null,
      is_maintainer: !!parsed.is_maintainer,
      jobs: Array.isArray(parsed.jobs) ? parsed.jobs : [],
    };
  } catch (e) {
    console.error("Failed to parse initial props:", e);
    return { username: null, is_maintainer: false, jobs: [] };
  }
}

// ------------------------
// MEDIAWIKI API
// ------------------------

export function mwApi(params: string): string {
  return "https://commons.wikimedia.org/w/api.php?origin=*&format=json&" + params;
}

// ------------------------
// NAMESPACES
// ------------------------

export async function loadNamespaces(): Promise<Array<{ id: string; name: string }>> {
  const r = await fetch(
    mwApi(
      "action=query&meta=siteinfo&siprop=namespaces"
    )
  );

  if (!r.ok) throw new Error(`Failed to load namespaces: ${r.status}`);

  const data = await r.json();
  const namespaces = data?.query?.namespaces ?? {};

  return Object.keys(namespaces).map((id) => ({
    id,
    name: namespaces[id]["*"] || "(Main)",
  }));
}

// ------------------------
// SEARCH TITLES
// ------------------------

export async function searchTitles(
  value: string,
  namespaceId: string
): Promise<Array<{ label: string; value: string }>> {
  if (!value) return [];

  const nsParam = namespaceId ? "&namespace=" + namespaceId : "";

  const r = await fetch(
    mwApi(
      "action=opensearch" +
        "&limit=10" +
        nsParam +
        "&search=" +
        encodeURIComponent(value)
    )
  );

  if (!r.ok) throw new Error(`Search failed: ${r.status}`);

  const d = await r.json();

  return (d?.[1] ?? []).map((t: string) => ({
    label: t,
    value: t,
  }));
}

// ------------------------
// LOAD EDITORS
// ------------------------

export async function loadEditorsForTitle(
  title: string
): Promise<{ users: string[]; latestUser: string; latestComment: string }> {
  const r = await fetch(
    mwApi(
      "action=query" +
        "&prop=revisions" +
        "&titles=" +
        encodeURIComponent(title) +
        "&rvprop=user|comment" +
        "&rvlimit=10"
    )
  );

  if (!r.ok) throw new Error(`Failed to load revisions: ${r.status}`);

  const data = await r.json();

  const pages = data?.query?.pages as Record<
    string,
    { revisions?: Array<{ user: string; comment?: string }> }
  >;

  let revisions: { user: string; comment?: string }[] = [];

  for (const page of Object.values(pages || {})) {
    if (page.revisions?.length) {
      revisions = page.revisions;
      break;
    }
  }

  if (!revisions.length) {
    return { users: [], latestUser: "", latestComment: "" };
  }

  const latest = revisions[0];

  return {
    users: [...new Set(revisions.map((r) => r.user))],
    latestUser: latest.user,
    latestComment: latest.comment ?? "",
  };
}

// ------------------------
// JOB API
// ------------------------

export async function fetchJobDetails(id: number): Promise<JobRow> {
  const r = await fetch(`/api/v1/rollback/jobs/${id}`);

  if (!r.ok) throw new Error(`Failed to fetch job ${id}: ${r.status}`);

  return r.json();
}

export async function fetchProgress(ids: number[]): Promise<Record<number, any>> {
  const r = await fetch(`/api/v1/rollback/jobs/progress?ids=${ids.join(",")}`);

  if (!r.ok) throw new Error(`Failed to fetch progress: ${r.status}`);

  return r.json();
}

export async function retryJob(id: number): Promise<void> {
  const r = await fetch(`/api/v1/rollback/jobs/${id}/retry`, {
    method: "POST",
  });

  if (!r.ok) throw new Error(`Retry failed for job ${id}: ${r.status}`);
}

export async function cancelJob(id: number, token?: string): Promise<void> {
  const headers: Record<string, string> = {};

  if (token) headers["X-Status-Token"] = token;

  const r = await fetch(`/api/v1/rollback/jobs/${id}`, {
    method: "DELETE",
    headers,
  });

  if (!r.ok) throw new Error(`Cancel failed for job ${id}: ${r.status}`);
}

// ------------------------
// CREATE JOB
// ------------------------

export async function createJob(payload: {
  requested_by: string;
  dry_run: boolean;
  items: CreateJobItem[];
  token?: string;
}): Promise<{ ok: boolean; result: any }> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (payload.token) headers["X-Status-Token"] = payload.token;

  const r = await fetch("/api/v1/rollback/jobs", {
    method: "POST",
    headers,
    body: JSON.stringify({
      requested_by: payload.requested_by,
      dry_run: payload.dry_run,
      items: payload.items,
    }),
  });

  let result: any = null;

  try {
    result = await r.json();
  } catch {
    // backend returned non-JSON (rare but possible)
  }

  return {
    ok: r.ok,
    result,
  };
}
