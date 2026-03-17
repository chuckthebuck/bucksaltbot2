export interface JobRow {
  id: number;
  status: string;
  progressText: string;
  progressPct: number;
  created: string;
  total?: number;
  completed?: number;
  failed?: number;
  items?: unknown[];
}

export interface CreateJobItem {
  title: string;
  user: string;
  summary: string | null;
}

export interface QueueProps {
  username: string | null;
  is_maintainer: boolean;
  jobs: [number, unknown, string, unknown, string][];
}

export function getInitialProps(): QueueProps {
  const el = document.getElementById("rollback-queue-props");
  if (!el?.textContent) {
    return { username: null, is_maintainer: false, jobs: [] };
  }
  return JSON.parse(el.textContent) as QueueProps;
}

export function mwApi(params: string): string {
  return "https://commons.wikimedia.org/w/api.php?origin=*&format=json&" + params;
}

export async function loadNamespaces(): Promise<Array<{ id: string; name: string }>> {
  const r = await fetch(
    "https://commons.wikimedia.org/w/api.php" +
      "?origin=*" +
      "&action=query" +
      "&meta=siteinfo" +
      "&siprop=namespaces" +
      "&format=json"
  );

  const data = await r.json();
  const namespaces = data.query.namespaces as Record<string, { "*": string }>;

  return Object.keys(namespaces).map((id) => ({
    id,
    name: namespaces[id]["*"] || "(Main)",
  }));
}

export async function searchTitles(value: string, namespaceId: string): Promise<Array<{ label: string; value: string }>> {
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
  const d = await r.json();

  return (d[1] || []).map((t: string) => ({
    label: t,
    value: t,
  }));
}

export async function loadEditorsForTitle(title: string): Promise<{ users: string[]; latestUser: string; latestComment: string }> {
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

  const data = await r.json();
  const pages = data.query.pages as Record<string, { revisions?: Array<{ user: string; comment?: string }> }>;

  let revisions: { user: string; comment?: string }[] = []

for (const page of Object.values(pages)) {
  if (page.revisions?.length) {
    revisions = page.revisions
    break
  }
}

  if (!revisions.length) {
    return { users: [], latestUser: "", latestComment: "" };
  }

  const latest = revisions[0];
  const users = [...new Set(revisions.map((r) => r.user))];

  return {
    users,
    latestUser: latest.user,
    latestComment: latest.comment || "",
  };
}

export async function fetchJobDetails(id: number): Promise<any> {
  const r = await fetch(`/api/v1/rollback/jobs/${id}`);
  return r.json();
}

export async function fetchProgress(ids: number[]): Promise<any> {
  const r = await fetch(`/api/v1/rollback/jobs/progress?ids=${ids.join(",")}`);
  return r.json();
}

export async function retryJob(id: number): Promise<void> {
  await fetch(`/api/v1/rollback/jobs/${id}/retry`, {
    method: "POST",
  });
}

export async function cancelJob(id: number, token?: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (token) headers["X-Status-Token"] = token;

  await fetch(`/api/v1/rollback/jobs/${id}`, {
    method: "DELETE",
    headers,
  });
}

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

  return {
    ok: r.ok,
    result: await r.json(),
  };
}
