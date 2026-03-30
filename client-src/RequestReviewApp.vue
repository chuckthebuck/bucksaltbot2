<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxButton, CdxMessage } from "@wikimedia/codex";
import {
  approveJob,
  fetchRollbackRequestPreview,
  fetchRollbackRequests,
  forceDryRunRequest,
  rejectRollbackRequest,
  runJobLive,
  type RollbackRequestPreview,
  type RollbackRequestRow,
} from "./api";
import UnifiedTable from "./components/UnifiedTable.vue";
import {
  actionColumn,
  type TableColumn,
} from "./components/unifiedTable";
import {
  buttonCell,
  dryRunModeColumn,
  modeLabel,
  statusTagColumn,
  textColumn,
} from "./components/tableColumnFactories";

const props = JSON.parse(
  document.getElementById("request-review-props")!.textContent || "{}"
) as {
  username: string;
  can_review_all_requests: boolean;
  can_approve_diff: boolean;
  can_approve_batch: boolean;
};

const loading = ref(true);
const refreshing = ref(false);
const hasLoadedOnce = ref(false);
const error = ref("");
const notice = ref("");
const requests = ref<RollbackRequestRow[]>([]);

const previewByJob = ref<Record<number, RollbackRequestPreview>>({});
const previewLoading = ref<Record<number, boolean>>({});
const approveLoading = ref<Record<number, boolean>>({});
const rejectLoading = ref<Record<number, boolean>>({});
const forceDryRunLoading = ref<Record<number, boolean>>({});
const runLiveLoading = ref<Record<number, boolean>>({});
const pollingTimer = ref<number | null>(null);

const pendingRequests = computed(() =>
  requests.value.filter((r) => r.status === "pending_approval")
);

const actionableRequests = computed(() =>
  requests.value.filter(
    (r) => r.status === "pending_approval" || (r.status === "completed" && r.dry_run)
  )
);

interface PreviewItemRow {
  key: string;
  index: number;
  title: string;
  user: string;
  summary: string;
}

function normalizeEndpoint(endpoint?: string | null): string | null {
  if (!endpoint) return null;
  const normalized = String(endpoint).trim().toLowerCase().replace(/-/g, "_");
  return normalized || null;
}

function isAccountStyleRequest(row: RollbackRequestRow): boolean {
  return row.request_type === "diff" && normalizeEndpoint(row.requested_endpoint) === "from_account";
}

function canUseFromDiffEndpoint(row: RollbackRequestRow): boolean {
  return row.request_type === "diff" && !isAccountStyleRequest(row);
}

function requestTypeLabel(row: RollbackRequestRow): string {
  if (isAccountStyleRequest(row)) {
    return "account";
  }
  return row.request_type;
}

function canApproveRequest(row: RollbackRequestRow): boolean {
  if (row.status !== "pending_approval") {
    return false;
  }

  return canReviewDecision(row);
}

function canReviewDecision(row: RollbackRequestRow): boolean {
  if (row.status !== "pending_approval") {
    if (row.requested_by === props.username) {
      return true;
    }
  }

  if (row.approval_required === "maintainer") {
    return Boolean(props.can_approve_diff);
  }

  if (row.approval_required === "admin") {
    return Boolean(props.can_approve_batch);
  }

  if (row.request_type === "diff") {
    return Boolean(props.can_approve_diff);
  }

  if (row.request_type === "batch") {
    return Boolean(props.can_approve_batch);
  }

  return false;
}

function canRejectRequest(row: RollbackRequestRow): boolean {
  return row.status === "pending_approval" && canReviewDecision(row);
}

function canForceDryRun(row: RollbackRequestRow): boolean {
  return row.status === "pending_approval" && !row.dry_run && canReviewDecision(row);
}

function canRunLive(row: RollbackRequestRow): boolean {
  if (row.status !== "completed" || !row.dry_run) {
    return false;
  }

  if (row.requested_by === props.username) {
    return true;
  }

  return canReviewDecision(row);
}

function dryRunLabel(row: RollbackRequestRow): string {
  return row.dry_run ? "dry-run" : "live";
}

function buildButton(
  row: RollbackRequestRow,
  text: string,
  onClick: () => void,
  options?: {
    action?: "default" | "progressive" | "destructive";
    weight?: "normal" | "primary" | "quiet";
    disabled?: boolean;
    key?: string;
  }
){
  return buttonCell(CdxButton, text, onClick, {
    key: options?.key,
    action: options?.action,
    weight: options?.weight,
    disabled: options?.disabled,
    extraProps: {
      "data-row-id": row.id,
    },
  });
}

const requestColumns: TableColumn<RollbackRequestRow>[] = [
  textColumn("id", "ID", (row) => row.id, { class: "request-col-id" }),
  textColumn("requester", "Requester", (row) => row.requested_by),
  textColumn("type", "Type", (row) => requestTypeLabel(row)),
  textColumn("endpoint", "Endpoint", (row) => normalizeEndpoint(row.requested_endpoint) || "-"),
  statusTagColumn("status", "Status", (row) => row.status),
  dryRunModeColumn(
    "mode",
    "Mode",
    (row) => row.dry_run,
    (dryRun) => modeLabel(dryRun, { dry: "dry-run", live: "live" })
  ),
  textColumn("items", "Items", (row) => row.total, { align: "right" }),
  actionColumn("preview", "Preview", (row) => {
    const loadingPreview = Boolean(previewLoading.value[row.id]);
    return buildButton(
      row,
      loadingPreview ? "Loading..." : "Preview",
      () => {
        void loadPreview(row, row.requested_endpoint || undefined);
      },
      {
        disabled: loadingPreview,
      }
    );
  }),
  actionColumn("preview_diff", "After diff", (row) => {
    if (row.request_type !== "diff" || !canUseFromDiffEndpoint(row)) return null;
    const loadingPreview = Boolean(previewLoading.value[row.id]);
    return buildButton(
      row,
      "Preview all after diff",
      () => {
        void loadPreview(row, "from_diff");
      },
      {
        disabled: loadingPreview,
      }
    );
  }),
  actionColumn("preview_account", "As account", (row) => {
    if (row.request_type !== "diff") return null;
    const loadingPreview = Boolean(previewLoading.value[row.id]);
    return buildButton(
      row,
      "Preview as account",
      () => {
        void loadPreview(row, "from_account");
      },
      {
        disabled: loadingPreview,
      }
    );
  }),
  actionColumn("approve", "Approve", (row) => {
    if (!canApproveRequest(row)) return null;

    const isApproving = Boolean(approveLoading.value[row.id]);

    if (row.request_type === "batch") {
      return buildButton(
        row,
        isApproving ? "Approving..." : "Approve batch",
        () => {
          void approve(row, "batch");
        },
        {
          action: "progressive",
          weight: "primary",
          disabled: isApproving,
        }
      );
    }

    if (row.request_type === "diff") {
      if (canUseFromDiffEndpoint(row)) {
        return buildButton(
          row,
          isApproving ? "Approving..." : "Approve from diff",
          () => {
            void approve(row, "from_diff");
          },
          {
            action: "progressive",
            weight: "primary",
            disabled: isApproving,
          }
        );
      }

      return buildButton(
        row,
        isApproving ? "Approving..." : "Approve account rollback",
        () => {
          void approve(row, "from_account");
        },
        {
          action: "progressive",
          weight: "primary",
          disabled: isApproving,
        }
      );
    }

    return null;
  }),
  actionColumn("approve_account", "Approve acct", (row) => {
    if (!canApproveRequest(row) || row.request_type !== "diff" || !canUseFromDiffEndpoint(row)) {
      return null;
    }

    const isApproving = Boolean(approveLoading.value[row.id]);

    return buildButton(
      row,
      "Approve as account",
      () => {
        void approve(row, "from_account");
      },
      {
        disabled: isApproving,
      }
    );
  }),
  actionColumn("force_dry", "Force dry", (row) => {
    if (!canForceDryRun(row)) return null;

    const isUpdating = Boolean(forceDryRunLoading.value[row.id]);

    return buildButton(
      row,
      isUpdating ? "Updating..." : "Force dry-run",
      () => {
        void forceDryRun(row);
      },
      {
        disabled: isUpdating,
      }
    );
  }),
  actionColumn("reject", "Reject", (row) => {
    if (!canRejectRequest(row)) return null;

    const isRejecting = Boolean(rejectLoading.value[row.id]);

    return buildButton(
      row,
      isRejecting ? "Rejecting..." : "Reject",
      () => {
        void reject(row);
      },
      {
        action: "destructive",
        disabled: isRejecting,
      }
    );
  }),
  actionColumn("run_live", "Run live", (row) => {
    if (!canRunLive(row)) return null;

    const isQueueing = Boolean(runLiveLoading.value[row.id]);

    return buildButton(
      row,
      isQueueing ? "Queueing..." : "Run live now",
      () => {
        void runLive(row);
      },
      {
        action: "progressive",
        disabled: isQueueing,
      }
    );
  }),
];

const previewColumns: TableColumn<PreviewItemRow>[] = [
  textColumn("index", "#", (row) => row.index, { align: "right", width: "1%" }),
  textColumn("title", "Title", (row) => row.title),
  textColumn("user", "User", (row) => row.user),
  textColumn("summary", "Summary/Status", (row) => row.summary),
];

function previewForRow(row: unknown): RollbackRequestPreview | undefined {
  const id = Number((row as { id?: number }).id);
  if (!Number.isFinite(id)) return undefined;
  return previewByJob.value[id];
}

function hasPreview(row: unknown): boolean {
  return Boolean(previewForRow(row));
}

function previewRowsFor(row: unknown): PreviewItemRow[] {
  const preview = previewForRow(row);
  if (!preview?.items?.length) return [];

  return preview.items.map((item, idx) => ({
    key: `${idx + 1}-${item.title}`,
    index: idx + 1,
    title: item.title,
    user: item.user,
    summary: `${item.summary || item.status || "-"}${item.error ? ` (${item.error})` : ""}`,
  }));
}

async function loadRequests() {
  const isInitialLoad = !hasLoadedOnce.value;
  if (isInitialLoad) {
    loading.value = true;
  } else {
    refreshing.value = true;
  }
  error.value = "";

  try {
    const data = await fetchRollbackRequests();
    requests.value = Array.isArray(data.requests) ? data.requests : [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load rollback requests";
  } finally {
    hasLoadedOnce.value = true;
    loading.value = false;
    refreshing.value = false;
  }
}

async function loadPreview(row: RollbackRequestRow, endpoint?: string) {
  previewLoading.value[row.id] = true;
  error.value = "";

  try {
    const effectiveEndpoint = normalizeEndpoint(endpoint || row.requested_endpoint);
    const preview = await fetchRollbackRequestPreview(
      row.id,
      effectiveEndpoint || undefined,
      true,
    );
    previewByJob.value[row.id] = preview;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load request preview";
  } finally {
    previewLoading.value[row.id] = false;
  }
}

async function approve(row: RollbackRequestRow, endpoint?: string) {
  approveLoading.value[row.id] = true;
  error.value = "";
  notice.value = "";

  try {
    const result = await approveJob(row.id, endpoint);
    notice.value = `Request ${row.id} approved: ${result.status}`;
    await loadRequests();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to approve request";
  } finally {
    approveLoading.value[row.id] = false;
  }
}

async function reject(row: RollbackRequestRow) {
  rejectLoading.value[row.id] = true;
  error.value = "";
  notice.value = "";

  try {
    const result = await rejectRollbackRequest(row.id);
    notice.value = `Request ${row.id} rejected: ${result.status}`;
    await loadRequests();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to reject request";
  } finally {
    rejectLoading.value[row.id] = false;
  }
}

async function forceDryRun(row: RollbackRequestRow) {
  forceDryRunLoading.value[row.id] = true;
  error.value = "";
  notice.value = "";

  try {
    const result = await forceDryRunRequest(row.id);
    notice.value = `Request ${row.id} set to dry-run: ${result.status}`;
    await loadRequests();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to force dry-run";
  } finally {
    forceDryRunLoading.value[row.id] = false;
  }
}

async function runLive(row: RollbackRequestRow) {
  runLiveLoading.value[row.id] = true;
  error.value = "";
  notice.value = "";

  try {
    const result = await runJobLive(row.id);
    notice.value = `Job ${row.id} moved to ${result.status} as live run`;
    await loadRequests();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to run job live";
  } finally {
    runLiveLoading.value[row.id] = false;
  }
}

onMounted(async () => {
  await loadRequests();

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
    if (loading.value || refreshing.value) return;
    void loadRequests();
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
    void loadRequests();
    startPolling();
  }
}
</script>

<template>
  <div class="request-review-wrap">
    <CdxMessage type="notice" class="top-message">
      Review pending rollback requests. Diff previews load the full edit list for
      the "all edits after this diff" endpoint.
    </CdxMessage>

    <CdxMessage v-if="notice" type="success" class="top-message">
      {{ notice }}
    </CdxMessage>

    <CdxMessage v-if="error" type="error" class="top-message">
      {{ error }}
    </CdxMessage>

    <div class="request-review-actions">
      <CdxButton action="default" weight="quiet" :disabled="loading || refreshing" @click="loadRequests">
        {{ refreshing ? 'Refreshing...' : 'Refresh requests' }}
      </CdxButton>
    </div>

    <div v-if="loading">Loading requests...</div>

    <div v-else>
      <h3>Pending approval ({{ pendingRequests.length }})</h3>

      <UnifiedTable
        :rows="actionableRequests"
        :columns="requestColumns"
        row-key="id"
        table-class="request-review-table"
        empty-text="No rollback requests found."
        :expanded="hasPreview"
      >
        <template #expanded="{ row }">
          <div v-if="previewForRow(row)" class="request-preview">
            <div>
              <b>Preview endpoint:</b> {{ previewForRow(row)?.endpoint }}
              <span v-if="previewForRow(row)?.resolved_user">
                | <b>User:</b> {{ previewForRow(row)?.resolved_user }}
              </span>
              <span>
                | <b>Total edits:</b> {{ previewForRow(row)?.total_items }}
              </span>
            </div>

            <UnifiedTable
              v-if="previewRowsFor(row).length"
              :rows="previewRowsFor(row)"
              :columns="previewColumns"
              row-key="key"
              table-class="request-preview-table"
            />
          </div>
        </template>
      </UnifiedTable>
    </div>
  </div>
</template>

<style scoped>
.request-review-wrap {
  margin-top: 16px;
}

.request-review-actions {
  margin-bottom: 12px;
}

.request-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.request-preview-table {
  margin-top: 8px;
}

.request-empty {
  color: #54595d;
}

.request-col-id {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

:deep(.request-review-table td) {
  white-space: nowrap;
}

:deep(.cdx-tag) {
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

:deep(.cdx-tag--status-success) {
  background-color: var(--background-color-success-subtle, #d5fdf4);
  border-color: var(--color-success, #14866d);
  color: var(--color-success, #14866d);
}

:deep(.cdx-tag--status-error) {
  background-color: var(--background-color-error-subtle, #fee7e6);
  border-color: var(--color-error, #d73333);
  color: var(--color-error, #d73333);
}

:deep(.cdx-tag--status-warning) {
  background-color: var(--background-color-warning-subtle, #fef6e7);
  border-color: var(--color-warning, #edab00);
  color: var(--color-warning, #7a4b00);
}

:deep(.cdx-tag--status-muted) {
  background-color: var(--background-color-disabled-subtle, #f0f0f0);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-subtle, #54595d);
}

:deep(.cdx-tag--mode-dry-run) {
  background-color: var(--background-color-warning-subtle, #fef6e7);
  border-color: var(--color-warning, #edab00);
  color: var(--color-warning, #7a4b00);
}

:deep(.cdx-tag--mode-live) {
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-base, #202122);
}
</style>
