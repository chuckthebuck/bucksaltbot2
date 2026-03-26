// TYPES

export interface JobRow {
  id: number;
  status: string;
  dry_run?: boolean;
  dryRun?: boolean;
  progressText: string;
  progressPct: number;
  created: string;
  created_at?: string;
  total?: number;
  completed?: number;
  failed?: number;
  items?: CreateJobItem[];
  request_type?: string;
  requested_endpoint?: string | null;
  approved_endpoint?: string | null;
  approval_required?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
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

export interface AllJobsRow {
  id: number;
  batch_id: number | null;
  requested_by: string;
  status: string;
  dry_run: boolean;
  created_at: string;
  request_type?: string | null;
  requested_endpoint?: string | null;
  approved_endpoint?: string | null;
  approval_required?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  total: number;
  completed: number;
  failed: number;
}

export interface RuntimeAuthzConfig {
  EXTRA_AUTHORIZED_USERS: string[];
  USERS_READ_ONLY: string[];
  USERS_TESTER: string[];
  USERS_GRANTED_FROM_DIFF: string[];
  USERS_GRANTED_VIEW_ALL: string[];
  USERS_GRANTED_BATCH: string[];
  USERS_GRANTED_CANCEL_ANY: string[];
  USERS_GRANTED_RETRY_ANY: string[];
  USER_GRANTS_JSON: Record<string, string[]>;
  RATE_LIMIT_JOBS_PER_HOUR: number;
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: number;
}

export interface RuntimeAuthzResponse {
  config: RuntimeAuthzConfig;
  can_edit: boolean;
  editable_keys: string[];
  grant_groups?: string[];
  grant_rights?: string[];
}

export interface RuntimeUserGrantsResponse {
  ok?: boolean;
  username: string;
  normalized_username: string;
  atoms: string[];
  groups: string[];
  rights: string[];
  expanded_rights: string[];
  implicit: Record<string, boolean>;
  implicit_flag_order?: string[];
  grant_groups?: string[];
  grant_rights?: string[];
  can_edit?: boolean;
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

export async function searchUsernames(
  value: string
): Promise<Array<{ label: string; value: string }>> {
  const query = value.trim();
  if (!query) return [];

  const r = await fetch(
    mwApi(
      "action=query" +
        "&list=allusers" +
        "&aulimit=10" +
        "&auprefix=" +
        encodeURIComponent(query)
    )
  );

  if (!r.ok) throw new Error(`User search failed: ${r.status}`);

  const data = await r.json();
  const users = data?.query?.allusers ?? [];

  return users.map((u: { name: string }) => ({
    label: u.name,
    value: u.name,
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

export async function fetchUserJobs(): Promise<JobRow[]> {
  const r = await fetch("/api/v1/rollback/jobs");

  if (!r.ok) throw new Error(`Failed to fetch jobs: ${r.status}`);

  const data = await r.json();
  return Array.isArray(data?.jobs) ? data.jobs : [];
}

export async function fetchAllJobs(): Promise<AllJobsRow[]> {
  const r = await fetch("/rollback-queue/all-jobs?format=json");

  if (!r.ok) throw new Error(`Failed to fetch all jobs: ${r.status}`);

  const data = await r.json();
  return Array.isArray(data?.jobs) ? data.jobs : [];
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

export async function approveJob(id: number, endpoint?: string): Promise<any> {
  const body: Record<string, unknown> = {};
  if (endpoint) {
    body.endpoint = endpoint;
  }

  const r = await fetch(`/api/v1/rollback/jobs/${id}/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  let data: any = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }

  if (!r.ok) {
    throw new Error(String(data?.detail || `Approval failed for job ${id}: ${r.status}`));
  }

  return data;
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

export async function fetchRuntimeAuthzConfig(): Promise<RuntimeAuthzResponse> {
  const r = await fetch("/api/v1/config/authz");

  if (!r.ok) throw new Error(`Failed to fetch runtime config: ${r.status}`);

  return r.json();
}

export async function updateRuntimeAuthzConfig(
  config: Partial<RuntimeAuthzConfig>
): Promise<RuntimeAuthzResponse> {
  const r = await fetch("/api/v1/config/authz", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ config }),
  });

  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to save runtime config: ${r.status}`);
  }

  return data;
}

export async function fetchRuntimeUserGrants(
  username: string
): Promise<RuntimeUserGrantsResponse> {
  const normalized = username.trim();
  const r = await fetch(`/api/v1/config/authz/user-grants/${encodeURIComponent(normalized)}`);

  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to fetch user grants: ${r.status}`);
  }

  return data;
}

export async function updateRuntimeUserGrants(
  username: string,
  payload: {
    groups?: string[];
    rights?: string[];
    reason?: string;
  }
): Promise<RuntimeUserGrantsResponse> {
  const normalized = username.trim();
  const r = await fetch(`/api/v1/config/authz/user-grants/${encodeURIComponent(normalized)}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await r.json();
  if (!r.ok) {
    throw new Error(data?.detail || `Failed to update user grants: ${r.status}`);
  }

  return data;
}
