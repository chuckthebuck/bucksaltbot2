export interface BatchRollbackItem {
  title: string;
  user: string;
  summary: string | null;
  selected: boolean;
}

interface QuarryJson {
  headers?: unknown;
  rows?: unknown;
}

const TITLE_COLUMNS = [
  "title",
  "page_title",
  "file",
  "file_title",
  "image",
  "img_name",
  "log_title",
];

const USER_COLUMNS = [
  "user",
  "username",
  "target_user",
  "actor_name",
  "rev_user_text",
  "commenter",
];

const SUMMARY_COLUMNS = [
  "summary",
  "comment",
  "rev_comment",
  "comment_text",
  "edit_summary",
  "reason",
];

export function quarryResultUrl(input: string): string | null {
  const value = input.trim();
  if (!value) return null;

  if (/^https?:\/\//i.test(value)) {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return null;
    }

    if (url.hostname !== "quarry.wmcloud.org") return null;

    const queryMatch = url.pathname.match(/^\/query\/(\d+)(?:\/|$)/);
    if (queryMatch) {
      return `https://quarry.wmcloud.org/query/${queryMatch[1]}/result/latest/0/json`;
    }

    const runMatch = url.pathname.match(/^\/run\/(\d+)(?:\/|$)/);
    if (runMatch) {
      return `https://quarry.wmcloud.org/run/${runMatch[1]}/output/0/json`;
    }

    return null;
  }

  const bareId = value.match(/^(?:query:)?(\d+)$/i);
  if (bareId) {
    return `https://quarry.wmcloud.org/query/${bareId[1]}/result/latest/0/json`;
  }

  const runId = value.match(/^run:(\d+)$/i);
  if (runId) {
    return `https://quarry.wmcloud.org/run/${runId[1]}/output/0/json`;
  }

  return null;
}

export function parseQuarryJson(payload: QuarryJson): BatchRollbackItem[] {
  if (!Array.isArray(payload.headers) || !Array.isArray(payload.rows)) {
    throw new Error("Quarry JSON must include headers and rows");
  }

  const headers = payload.headers.map((header) => String(header));

  return payload.rows
    .map((row) => rowToRecord(headers, row))
    .map(recordToItem)
    .filter((item): item is BatchRollbackItem => item !== null);
}

export function parseDelimitedRows(text: string): BatchRollbackItem[] {
  const rows = parseDelimited(text);
  if (rows.length < 2) return [];

  const headers = rows[0].map((header) => header.trim());
  return rows
    .slice(1)
    .map((row) => rowToRecord(headers, row))
    .map(recordToItem)
    .filter((item): item is BatchRollbackItem => item !== null);
}

export function parseQuarryText(text: string): BatchRollbackItem[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  try {
    const payload = JSON.parse(trimmed);
    if (Array.isArray(payload?.items)) {
      return payload.items
        .map(recordToItem)
        .filter((item: BatchRollbackItem | null): item is BatchRollbackItem => item !== null);
    }
    return parseQuarryJson(payload);
  } catch {
    return parseDelimitedRows(trimmed);
  }
}

function rowToRecord(headers: string[], row: unknown): Record<string, unknown> {
  if (Array.isArray(row)) {
    return Object.fromEntries(headers.map((header, index) => [header, row[index]]));
  }

  if (row && typeof row === "object") {
    return row as Record<string, unknown>;
  }

  return {};
}

function recordToItem(record: Record<string, unknown>): BatchRollbackItem | null {
  const title = stringFromRecord(record, TITLE_COLUMNS);
  const user = stringFromRecord(record, USER_COLUMNS);

  if (!title || !user) return null;

  return {
    title: normalizeTitle(title),
    user,
    summary: stringFromRecord(record, SUMMARY_COLUMNS) || null,
    selected: true,
  };
}

function stringFromRecord(
  record: Record<string, unknown>,
  names: string[]
): string {
  const lookup = new Map(
    Object.entries(record).map(([key, value]) => [key.toLowerCase(), value])
  );

  for (const name of names) {
    const value = lookup.get(name.toLowerCase());
    if (value !== undefined && value !== null) {
      const text = String(value).trim();
      if (text) return text;
    }
  }

  return "";
}

function normalizeTitle(title: string): string {
  return title.startsWith("File:") || title.startsWith("Category:")
    ? title
    : `File:${title}`;
}

function parseDelimited(text: string): string[][] {
  const delimiter = text.includes("\t") ? "\t" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      quoted = !quoted;
      continue;
    }

    if (char === delimiter && !quoted) {
      row.push(cell);
      cell = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      continue;
    }

    cell += char;
  }

  row.push(cell);
  rows.push(row);

  return rows.filter((fields) => fields.some((field) => field.trim()));
}
