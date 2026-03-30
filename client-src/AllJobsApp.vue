<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxButton } from "@wikimedia/codex";
import {
  approveJob,
  fetchAllJobs,
  fetchJobDetails,
  type AllJobsRow as ApiAllJobsRow,
} from "./api";
import UnifiedTable from "./components/UnifiedTable.vue";
import {
  actionColumn,
  type TableColumn,
} from "./components/unifiedTable";
import {
  buttonCell,
  dryRunModeColumn,
  linkCell,
  modeLabel,
  progressPercent,
  progressSummary,
  statusTagColumn,
  textColumn,
} from "./components/tableColumnFactories";

const pageProps = JSON.parse(
  document.getElementById("all-jobs-props")!.textContent || "{}"
) as {
  can_approve_diff?: boolean;
  can_approve_batch?: boolean;
};

interface AllJobsRow {
  id: number;
  batchId: number | null;
  requestedBy: string;
  status: string;
  dryRun: boolean;
  created: string;
  requestType: string;
  requestedEndpoint: string | null;
  approvedEndpoint: string | null;
  approvalRequired: string | null;
  approvedBy: string | null;
  approvedAt: string | null;
  total: number;
  completed: number;
  failed: number;
}

interface DisplayJobRow extends AllJobsRow {
  kind: "job";
  rowKey: string;
  label: string;
}

interface DisplayBatchRow {
  kind: "batch";
  rowKey: string;
  batchId: number;
  label: string;
  requestedBy: string;
  status: string;
  dryRun: boolean | null;
  created: string;
  total: number;
  completed: number;
  failed: number;
  jobs: AllJobsRow[];
}

type DisplayRow = DisplayJobRow | DisplayBatchRow;

const ACTIVE_STATUSES = new Set(["queued", "running", "resolving", "staging", "pending_approval"]);

function asBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return ["1", "true", "yes", "on"].includes(normalized);
  }

  return false;
}

function asPositiveIntOrNull(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function normalizeAllJobsRow(row: unknown): AllJobsRow | null {
  if (!row || typeof row !== "object") return null;

  const obj = row as Record<string, unknown>;
  const id = Number(obj.id);
  if (!Number.isFinite(id) || id <= 0) return null;

  return {
    id,
    batchId: asPositiveIntOrNull(obj.batch_id),
    requestedBy: String(obj.requested_by ?? ""),
    status: String(obj.status ?? "queued"),
    dryRun: asBoolean(obj.dry_run),
    created: String(obj.created_at ?? ""),
    requestType: String(obj.request_type ?? "queue"),
    requestedEndpoint: obj.requested_endpoint ? String(obj.requested_endpoint) : null,
    approvedEndpoint: obj.approved_endpoint ? String(obj.approved_endpoint) : null,
    approvalRequired: obj.approval_required ? String(obj.approval_required) : null,
    approvedBy: obj.approved_by ? String(obj.approved_by) : null,
    approvedAt: obj.approved_at ? String(obj.approved_at) : null,
    total: Number(obj.total ?? 0),
    completed: Number(obj.completed ?? 0),
    failed: Number(obj.failed ?? 0)
  };
}

const jobs = ref<AllJobsRow[]>([]);
const loading = ref(true);
const error = ref("");
const actionError = ref("");
const actionNotice = ref("");
const details = ref<Record<string, string>>({});
const openRows = ref<Record<string, boolean>>({});
const pendingApprove = ref<Record<number, boolean>>({});
const pollingTimer = ref<number | null>(null);
const refreshing = ref(false);

const canApproveDiff = computed(() => Boolean(pageProps.can_approve_diff));
const canApproveBatch = computed(() => Boolean(pageProps.can_approve_batch));

async function loadAllJobsRows() {
  refreshing.value = true;
  try {
    const rows = await fetchAllJobs();
    jobs.value = (rows as ApiAllJobsRow[])
      .map((j) => normalizeAllJobsRow(j))
      .filter((j): j is AllJobsRow => j !== null);
  } finally {
    refreshing.value = false;
  }
}

onMounted(async () => {
  try {
    await loadAllJobsRows();
  } catch (e) {
    console.error("Failed to load all jobs:", e);
    error.value = "Failed to load all jobs.";
  } finally {
    loading.value = false;
  }

  if (!document.hidden) startPolling();
  document.addEventListener("visibilitychange", onVisibilityChange);
});

onBeforeUnmount(() => {
  stopPolling();
  document.removeEventListener("visibilitychange", onVisibilityChange);
});

function startPolling() {
  if (pollingTimer.value !== null) return;

  pollingTimer.value = window.setInterval(() => {
    if (refreshing.value) return;
    void loadAllJobsRows();
  }, 5000);
}

function stopPolling() {
  if (pollingTimer.value === null) return;
  clearInterval(pollingTimer.value);
  pollingTimer.value = null;
}

function onVisibilityChange() {
  if (document.hidden) {
    stopPolling();
  } else {
    void loadAllJobsRows();
    startPolling();
  }
}

function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function summarizeBatchStatus(batchJobs: AllJobsRow[]): string {
  const statuses = batchJobs.map((job) => job.status);

  if (statuses.every((status) => status === "completed")) return "completed";
  if (statuses.every((status) => status === "canceled")) return "canceled";
  if (statuses.some((status) => status === "failed")) return "failed";
  if (statuses.some((status) => ACTIVE_STATUSES.has(status))) return "running";
  if (statuses.some((status) => status === "completed")) return "running";

  return statuses[0] ?? "queued";
}

function summarizeBatchMode(batchJobs: AllJobsRow[]): boolean | null {
  const hasDryRun = batchJobs.some((job) => job.dryRun);
  const hasLive = batchJobs.some((job) => !job.dryRun);

  if (hasDryRun && hasLive) return null;
  return hasDryRun;
}

function canApproveRow(row: DisplayRow): boolean {
  if (row.kind !== "job") return false;
  if (row.status !== "pending_approval") return false;

  if (row.approvalRequired === "maintainer") {
    return canApproveDiff.value;
  }

  if (row.approvalRequired === "admin") {
    return canApproveBatch.value;
  }

  if (row.requestType === "diff") {
    return canApproveDiff.value;
  }

  if (row.requestType === "batch") {
    return canApproveBatch.value;
  }

  return false;
}

async function onApprove(row: DisplayJobRow, endpoint?: string) {
  actionError.value = "";
  actionNotice.value = "";
  pendingApprove.value[row.id] = true;

  try {
    const result = await approveJob(row.id, endpoint);
    actionNotice.value = String(result?.status || "Approved");
    await loadAllJobsRows();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : "Approval failed";
  } finally {
    pendingApprove.value[row.id] = false;
  }
}

function buildBatchDetails(row: DisplayBatchRow): string {
  const jobsList = row.jobs
    .map(
      (job) =>
        `<li><b>Job ${job.id}</b>: ${esc(job.status)} (${progressSummary(job)}) - ` +
        `<a href="/api/v1/rollback/jobs/${job.id}" target="_blank" rel="noopener noreferrer">JSON</a> | ` +
        `<a href="/api/v1/rollback/jobs/${job.id}?format=log" target="_blank" rel="noopener noreferrer">Log</a></li>`
    )
    .join("");

  return `
    <b>Batch ID:</b> ${row.batchId}<br>
    <b>Jobs:</b> ${row.jobs.length}<br>
    <b>Requested by:</b> ${esc(row.requestedBy)}<br>
    <b>Status:</b> ${esc(row.status)}<br>
    <b>Mode:</b> ${esc(modeLabel(row.dryRun))}<br>
    <b>Progress:</b> ${progressSummary(row)} (${progressPercent(row)}%)<br>
    <ul>${jobsList}</ul>
  `;
}

async function toggle(row: DisplayRow) {
  const key = row.rowKey;

  if (openRows.value[key]) {
    openRows.value[key] = false;
    return;
  }

  if (row.kind === "batch") {
    details.value[key] = buildBatchDetails(row);
    openRows.value[key] = true;
    return;
  }

  const d = await fetchJobDetails(row.id);
  const isDryRun = !!((d as { dry_run?: boolean; dryRun?: boolean }).dry_run ??
    (d as { dry_run?: boolean; dryRun?: boolean }).dryRun);

  details.value[key] = `
    <b>Status:</b> ${esc(d.status)}<br>
    <b>Mode:</b> ${isDryRun ? "Dry run" : "Live"}<br>
    <b>Total:</b> ${d.total}<br>
    <b>Completed:</b> ${d.completed}<br>
    <b>Failed:</b> ${d.failed}<br>
    <pre>${esc(JSON.stringify(d.items, null, 2))}</pre>
  `;
  openRows.value[key] = true;
}

const displayedRows = computed<DisplayRow[]>(() => {
  const sorted = [...jobs.value].sort((a, b) => {
    const aBatchSortKey = a.batchId ?? a.id;
    const bBatchSortKey = b.batchId ?? b.id;

    if (aBatchSortKey !== bBatchSortKey) {
      return bBatchSortKey - aBatchSortKey;
    }

    return b.id - a.id;
  });

  const grouped = new Map<string, AllJobsRow[]>();
  for (const job of sorted) {
    const groupKey = String(job.batchId ?? job.id);
    if (!grouped.has(groupKey)) grouped.set(groupKey, []);
    grouped.get(groupKey)!.push(job);
  }

  const rows: DisplayRow[] = [];

  for (const groupJobs of grouped.values()) {
    const containsPendingBatchRequest = groupJobs.some(
      (job) => job.status === "pending_approval" && job.requestType === "batch"
    );

    if (containsPendingBatchRequest) {
      for (const job of groupJobs) {
        rows.push({
          ...job,
          kind: "job",
          rowKey: `job:${job.id}`,
          label: String(job.id),
        });
      }
      continue;
    }

    if (groupJobs.length === 1) {
      const job = groupJobs[0];
      rows.push({
        ...job,
        kind: "job",
        rowKey: `job:${job.id}`,
        label: String(job.id),
      });
      continue;
    }

    const batchId = groupJobs[0].batchId ?? groupJobs[0].id;
    const requesterSet = new Set(groupJobs.map((job) => job.requestedBy).filter(Boolean));

    rows.push({
      kind: "batch",
      rowKey: `batch:${batchId}`,
      batchId,
      label: `Batch ${batchId}`,
      requestedBy: requesterSet.size === 1 ? groupJobs[0].requestedBy : `${requesterSet.size} users`,
      status: summarizeBatchStatus(groupJobs),
      dryRun: summarizeBatchMode(groupJobs),
      created: groupJobs[0].created,
      total: groupJobs.reduce((sum, job) => sum + (job.total || 0), 0),
      completed: groupJobs.reduce((sum, job) => sum + (job.completed || 0), 0),
      failed: groupJobs.reduce((sum, job) => sum + (job.failed || 0), 0),
      jobs: groupJobs,
    });
  }

  return rows;
});

function buildApproveButton(
  row: DisplayJobRow,
  text: string,
  endpoint: string,
  options?: {
    action?: "default" | "progressive" | "destructive";
    weight?: "normal" | "primary" | "quiet";
  }
){
  return buttonCell(
    CdxButton,
    pendingApprove.value[row.id] ? "Approving..." : text,
    () => {
      void onApprove(row, endpoint);
    },
    {
      key: `${row.id}-${endpoint}`,
      action: options?.action,
      weight: options?.weight,
      disabled: pendingApprove.value[row.id],
    }
  );
}

const tableColumns: TableColumn<DisplayRow>[] = [
  {
    key: "id",
    label: "ID",
    class: "all-jobs-table__id",
    render: (row) => linkCell(row.label, "#", {
      onClick: (event) => {
        event.preventDefault();
        void toggle(row);
      },
    }),
  },
  textColumn("requester", "Requested by", (row) => row.requestedBy),
  statusTagColumn("status", "Status", (row) => row.status),
  dryRunModeColumn("mode", "Mode", (row) => row.dryRun),
  {
    key: "progress",
    label: "Progress",
    render: (row) => `${progressSummary(row)} (${progressPercent(row)}%)`,
    class: "all-jobs-table__progress",
  },
  textColumn("created", "Created", (row) => row.created, { class: "all-jobs-table__created" }),
  actionColumn("json", "JSON", (row) => {
    if (row.kind !== "job") return null;
    return linkCell("JSON", `/api/v1/rollback/jobs/${row.id}`, {
      target: "_blank",
      rel: "noopener noreferrer",
    });
  }),
  actionColumn("log", "Log", (row) => {
    if (row.kind !== "job") return null;
    return linkCell("Log", `/api/v1/rollback/jobs/${row.id}?format=log`, {
      target: "_blank",
      rel: "noopener noreferrer",
    });
  }),
  actionColumn("approve", "Approve", (row) => {
    if (row.kind !== "job" || !canApproveRow(row)) return null;

    if (row.requestType === "batch") {
      return buildApproveButton(row, "Approve batch", "batch", {
        action: "progressive",
        weight: "primary",
      });
    }

    if (row.requestType === "diff") {
      return buildApproveButton(row, "Approve as diff", "from_diff", {
        action: "progressive",
        weight: "primary",
      });
    }

    return null;
  }),
  actionColumn("approve_account", "Approve acct", (row) => {
    if (row.kind !== "job" || !canApproveRow(row) || row.requestType !== "diff") {
      return null;
    }

    return buildApproveButton(row, "Approve as account", "from_account");
  }),
  {
    key: "group",
    label: "Group",
    render: (row) => (row.kind === "batch" ? `${row.jobs.length} jobs` : "-"),
    class: "all-jobs-table__batch-hint",
  },
];

function isExpandedRow(row: unknown): boolean {
  const key = (row as DisplayRow).rowKey;
  return Boolean(openRows.value[key]);
}

function detailsHtml(row: unknown): string {
  const key = (row as DisplayRow).rowKey;
  return details.value[key] || "";
}
</script>

<template>
  <div class="all-jobs-table-wrap">
    <div v-if="actionNotice" class="all-jobs-action all-jobs-action--ok">{{ actionNotice }}</div>
    <div v-if="actionError" class="all-jobs-action all-jobs-action--error">{{ actionError }}</div>
    <div class="all-jobs-table__toolbar">
      <CdxButton
        action="default"
        weight="quiet"
        size="small"
        :disabled="refreshing"
        @click="loadAllJobsRows"
      >
        {{ refreshing ? 'Refreshing...' : 'Refresh list' }}
      </CdxButton>
    </div>

    <div v-if="loading" class="all-jobs-table__empty">Loading jobs...</div>
    <div v-else-if="error" class="all-jobs-table__empty">{{ error }}</div>
    <UnifiedTable
      v-else
      :rows="displayedRows"
      :columns="tableColumns"
      row-key="rowKey"
      table-class="all-jobs-table"
      empty-text="No jobs found."
      :expanded="isExpandedRow"
    >
      <template #expanded="{ row }">
        <div class="job-details" style="display:block" v-html="detailsHtml(row)"></div>
      </template>
    </UnifiedTable>
  </div>
</template>

<style scoped>
.all-jobs-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.all-jobs-table__toolbar {
  margin-bottom: 10px;
}

.all-jobs-action {
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: 4px;
}

.all-jobs-action--ok {
  background: #e6f5ff;
  border: 1px solid #7fb3ff;
}

.all-jobs-action--error {
  background: #fee7e6;
  border: 1px solid #d73333;
}

.all-jobs-table {
  width: 100%;
  min-width: 860px;
  border-collapse: separate;
  border-spacing: 0;
}

.all-jobs-table th,
.all-jobs-table td {
  padding: 8px 10px;
  vertical-align: middle;
}

.all-jobs-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background-color: var(--background-color-neutral, #eaecf0);
  text-align: left;
  white-space: nowrap;
}

.all-jobs-table tbody tr:nth-child(odd) {
  background-color: var(--background-color-base, #fff);
}

.all-jobs-table tbody tr:nth-child(even) {
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
}

.all-jobs-table tbody tr:hover {
  background-color: #f1f4fd;
}

.all-jobs-table__id {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.all-jobs-table__created {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.all-jobs-table__progress {
  white-space: nowrap;
}

.all-jobs-table__batch-hint {
  color: var(--color-subtle, #54595d);
}

.all-jobs-table__empty {
  text-align: center;
  color: var(--color-subtle, #54595d);
  padding: 20px;
}

.cdx-tag {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border-color-subtle, #c8ccd1);
  border-radius: 9999px;
  padding: 2px 8px;
  font-size: 0.8125rem;
  line-height: 1.4;
  text-transform: capitalize;
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
  color: var(--color-base, #202122);
}

.cdx-tag--status-success {
  background-color: var(--background-color-success-subtle, #d5fdf4);
  border-color: var(--color-success, #14866d);
  color: var(--color-success, #14866d);
}

.cdx-tag--status-error {
  background-color: var(--background-color-error-subtle, #fee7e6);
  border-color: var(--color-error, #d73333);
  color: var(--color-error, #d73333);
}

.cdx-tag--status-warning {
  background-color: var(--background-color-warning-subtle, #fef6e7);
  border-color: var(--color-warning, #edab00);
  color: var(--color-warning, #7a4b00);
}

.cdx-tag--status-muted {
  background-color: var(--background-color-disabled-subtle, #f0f0f0);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-subtle, #54595d);
}

.cdx-tag--mode-dry-run {
  background-color: var(--background-color-warning-subtle, #fef6e7);
  border-color: var(--color-warning, #edab00);
  color: var(--color-warning, #7a4b00);
}

.cdx-tag--mode-live {
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-base, #202122);
}

.cdx-tag--mode-mixed {
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-subtle, #54595d);
}

:deep(.all-jobs-table td) {
  white-space: nowrap;
}
</style>
