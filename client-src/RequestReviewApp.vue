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

    <div v-else-if="!requests.length" class="request-empty">
      No rollback requests found.
    </div>

    <div v-else>
      <h3>Pending approval ({{ pendingRequests.length }})</h3>

      <table class="wikitable">
        <thead>
          <tr>
            <th>ID</th>
            <th>Requester</th>
            <th>Type</th>
            <th>Endpoint</th>
            <th>Status</th>
            <th>Mode</th>
            <th>Items</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in requests" :key="row.id">
            <tr>
              <td>{{ row.id }}</td>
              <td>{{ row.requested_by }}</td>
              <td>{{ requestTypeLabel(row) }}</td>
              <td>{{ normalizeEndpoint(row.requested_endpoint) || '-' }}</td>
              <td>{{ row.status }}</td>
              <td>{{ dryRunLabel(row) }}</td>
              <td>{{ row.total }}</td>
              <td>
                <div class="request-actions">
                  <CdxButton
                    size="small"
                    action="default"
                    weight="quiet"
                    :disabled="previewLoading[row.id]"
                    @click="loadPreview(row, row.requested_endpoint || undefined)"
                  >
                    {{ previewLoading[row.id] ? 'Loading...' : 'Preview' }}
                  </CdxButton>

                  <template v-if="row.request_type === 'diff'">
                    <CdxButton
                      v-if="canUseFromDiffEndpoint(row)"
                      size="small"
                      action="default"
                      weight="quiet"
                      :disabled="previewLoading[row.id]"
                      @click="loadPreview(row, 'from_diff')"
                    >
                      Preview all after diff
                    </CdxButton>

                    <CdxButton
                      size="small"
                      action="default"
                      weight="quiet"
                      :disabled="previewLoading[row.id]"
                      @click="loadPreview(row, 'from_account')"
                    >
                      Preview as account
                    </CdxButton>
                  </template>

                  <template v-if="canApproveRequest(row)">
                    <CdxButton
                      v-if="row.request_type === 'batch'"
                      size="small"
                      action="progressive"
                      weight="primary"
                      :disabled="approveLoading[row.id]"
                      @click="approve(row, 'batch')"
                    >
                      {{ approveLoading[row.id] ? 'Approving...' : 'Approve batch' }}
                    </CdxButton>

                    <template v-else-if="row.request_type === 'diff'">
                      <CdxButton
                        v-if="canUseFromDiffEndpoint(row)"
                        size="small"
                        action="progressive"
                        weight="primary"
                        :disabled="approveLoading[row.id]"
                        @click="approve(row, 'from_diff')"
                      >
                        {{ approveLoading[row.id] ? 'Approving...' : 'Approve from diff' }}
                      </CdxButton>

                      <CdxButton
                        size="small"
                        :action="canUseFromDiffEndpoint(row) ? 'default' : 'progressive'"
                        :weight="canUseFromDiffEndpoint(row) ? 'quiet' : 'primary'"
                        :disabled="approveLoading[row.id]"
                        @click="approve(row, 'from_account')"
                      >
                        {{ canUseFromDiffEndpoint(row) ? 'Approve as account' : 'Approve account rollback' }}
                      </CdxButton>
                    </template>
                  </template>

                  <CdxButton
                    v-if="canForceDryRun(row)"
                    size="small"
                    action="default"
                    weight="quiet"
                    :disabled="forceDryRunLoading[row.id]"
                    @click="forceDryRun(row)"
                  >
                    {{ forceDryRunLoading[row.id] ? 'Updating...' : 'Force dry-run' }}
                  </CdxButton>

                  <CdxButton
                    v-if="canRejectRequest(row)"
                    size="small"
                    action="destructive"
                    weight="quiet"
                    :disabled="rejectLoading[row.id]"
                    @click="reject(row)"
                  >
                    {{ rejectLoading[row.id] ? 'Rejecting...' : 'Reject' }}
                  </CdxButton>

                  <CdxButton
                    v-if="canRunLive(row)"
                    size="small"
                    action="progressive"
                    weight="quiet"
                    :disabled="runLiveLoading[row.id]"
                    @click="runLive(row)"
                  >
                    {{ runLiveLoading[row.id] ? 'Queueing...' : 'Run live now' }}
                  </CdxButton>
                </div>
              </td>
            </tr>

            <tr v-if="previewByJob[row.id]">
              <td colspan="8">
                <div class="request-preview">
                  <div>
                    <b>Preview endpoint:</b> {{ previewByJob[row.id].endpoint }}
                    <span v-if="previewByJob[row.id].resolved_user">
                      | <b>User:</b> {{ previewByJob[row.id].resolved_user }}
                    </span>
                    <span>
                      | <b>Total edits:</b> {{ previewByJob[row.id].total_items }}
                    </span>
                  </div>

                  <table class="wikitable request-preview-table" v-if="previewByJob[row.id].items?.length">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Title</th>
                        <th>User</th>
                        <th>Summary/Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(item, idx) in previewByJob[row.id].items"
                        :key="`${row.id}-${idx}-${item.title}`"
                      >
                        <td>{{ idx + 1 }}</td>
                        <td>{{ item.title }}</td>
                        <td>{{ item.user }}</td>
                        <td>
                          {{ item.summary || item.status || '-' }}
                          <span v-if="item.error"> ({{ item.error }})</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
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

.request-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
</style>
