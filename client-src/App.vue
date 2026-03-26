<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxButton, CdxCheckbox, CdxMessage } from "@wikimedia/codex";
import JobItemRow from "./components/JobItemRow.vue";
import JobsTable, { type UiJob } from "./components/JobsTable.vue";
import {
  createJob,
  fetchProgress,
  fetchUserJobs,
  getInitialProps,
  loadNamespaces,
  type CreateJobItem
} from "./api";

const props = getInitialProps();

const requestedBy = ref(props.username || "");
const items = ref<Array<{ key: number; data: CreateJobItem | null }>>([
  { key: Date.now(), data: null },
]);

const statusToken = ref("");
const namespaceId = ref("");
const namespaces = ref<Array<{ id: string; name: string }>>([]);
const dryRun = ref(false);
const createResult = ref("");
const pollingTimer = ref<number | null>(null);
const terminalStatuses = new Set(["completed", "failed", "canceled"]);

function asBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return ["1", "true", "yes", "on"].includes(normalized);
  }

  return false;
}

function normalizeJob(row: unknown): UiJob | null {
  if (Array.isArray(row)) {
    // rollback_queue.html currently injects DB tuples:
    // [id, requested_by, status, dry_run, created_at]
    const id = Number(row[0]);
    if (!Number.isFinite(id) || id <= 0) return null;

    return {
      id,
      status: String(row[2] ?? "queued"),
      dryRun: asBoolean(row[3]),
      created: String(row[4] ?? ""),
      total: 0,
      completed: 0,
      failed: 0,
    };
  }

  if (row && typeof row === "object") {
    const obj = row as Record<string, unknown>;
    const id = Number(obj.id);
    if (!Number.isFinite(id) || id <= 0) return null;

    return {
      id,
      status: String(obj.status ?? "queued"),
      dryRun: asBoolean(obj.dryRun ?? obj.dry_run),
      created: String(obj.created ?? obj.created_at ?? ""),
      total: Number(obj.total ?? 0),
      completed: Number(obj.completed ?? 0),
      failed: Number(obj.failed ?? 0),
    };
  }

  return null;
}

const jobs = ref<UiJob[]>(
  ((props.jobs as unknown[]) || [])
    .map((j) => normalizeJob(j))
    .filter((j): j is UiJob => j !== null)
);

const activeJobIds = computed(() =>
  jobs.value
    .filter((j) => !terminalStatuses.has(j.status))
    .map((j) => j.id)
);

function createdTimeMs(created: string): number | null {
  const trimmed = created.trim();
  if (!trimmed) return null;

  const withT = trimmed.includes(" ") && !trimmed.includes("T")
    ? trimmed.replace(" ", "T")
    : trimmed;

  // Some DB timestamps include microseconds; JS Date handles milliseconds.
  const normalized = withT.replace(/(\.\d{3})\d+/, "$1");

  const parsed = Date.parse(normalized);
  return Number.isNaN(parsed) ? null : parsed;
}

function shouldShowInUserJobs(job: UiJob): boolean {
  if (!terminalStatuses.has(job.status)) return true;
  if (job.status !== "failed" && job.status !== "completed") return false;

  const createdAt = createdTimeMs(job.created);
  if (createdAt === null) return false;

  const ageMs = Date.now() - createdAt;

  if (job.status === "failed") {
    return ageMs <= 24 * 60 * 60 * 1000;
  }

  return ageMs <= 2 * 60 * 60 * 1000;
}

const visibleJobs = computed(() => jobs.value.filter(shouldShowInUserJobs));

async function loadJobs() {
  const rows = await fetchUserJobs();

  jobs.value = rows
    .map((j) => normalizeJob(j))
    .filter((j): j is UiJob => j !== null);
}

function addItem() {
  items.value.push({ key: Date.now() + Math.floor(Math.random() * 1000), data: null });
}

function removeItem(index: number) {
  items.value.splice(index, 1);
  if (!items.value.length) addItem();
}

function updateItem(index: number, data: CreateJobItem | null) {
  items.value[index].data = data;
}

async function submitJob() {
  console.log({
    items: items.value.map((item) => item.data).filter(Boolean),
    statusToken: statusToken.value,
    namespace: namespaceId.value,
    dryRun: dryRun.value,
  });

  const payload = items.value
    .map((item) => item.data)
    .filter(Boolean) as CreateJobItem[];

  if (!payload.length) {
    alert("Add at least one item");
    return;
  }

  const { ok, result } = await createJob({
    requested_by: requestedBy.value,
    dry_run: dryRun.value,
    items: payload,
    token: statusToken.value || undefined,
  });

  createResult.value = JSON.stringify(result, null, 2);

  if (ok && result.job_id) {
    jobs.value.unshift({
      id: result.job_id,
      status: "queued",
      dryRun: dryRun.value,
      created: new Date().toISOString(),
      total: payload.length,
      completed: 0,
      failed: 0,
    });
  }
}

async function refresh() {
  await loadJobs();

  if (!activeJobIds.value.length) return;

  const data = (await fetchProgress(activeJobIds.value)) as {
    jobs?: Array<{
      id: number;
      status: string;
      total?: number;
      completed?: number;
      failed?: number;
    }>;
  };

  if (!data.jobs) return;

  for (const updated of data.jobs) {
    const target = jobs.value.find((j) => j.id === updated.id);
    if (!target) continue;

    target.status = updated.status;
    target.total = updated.total || 0;
    target.completed = updated.completed || 0;
    target.failed = updated.failed || 0;
  }
}

async function onJobUpdated() {
  await loadJobs();
  await refresh();
}

function startPolling() {
  if (pollingTimer.value !== null) return;
  void refresh();
  pollingTimer.value = window.setInterval(() => {
    void refresh();
  }, 5000);
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    clearInterval(pollingTimer.value);
    pollingTimer.value = null;
  }
}

function onVisibilityChange() {
  if (document.hidden) {
    stopPolling();
  } else {
    startPolling();
  }
}

onMounted(async () => {
  try {
    await loadJobs();
  } catch (e) {
    console.error("Failed to load jobs; using embedded props.", e);
  }

  namespaces.value = await loadNamespaces();

  if (!props.is_maintainer) {
    namespaceId.value = "6";
  }

  if (!document.hidden) startPolling();
  document.addEventListener("visibilitychange", onVisibilityChange);
});

onBeforeUnmount(() => {
  stopPolling();
  document.removeEventListener("visibilitychange", onVisibilityChange);
});
</script>

<template>
  <div class="container rollback-queue-container">
    <CdxMessage class="top-message">
      Submitting a job will trigger your configured rollback bot account on Wikimedia Commons.
      You are responsible for reviewing results.
    </CdxMessage>

    <div class="layout">
      <div class="left-panel">
        <h3>Create job</h3>

        <CdxButton type="button" @click="addItem">Add item</CdxButton>

        <div id="job-items" class="job-items">
          <div class="job-item-table-head" aria-hidden="true">
            <span>Page</span>
            <span>Contributor</span>
            <span>Summary</span>
            <span>Action</span>
          </div>

          <JobItemRow
            v-for="(item, index) in items"
            :key="item.key"
            :namespace-id="namespaceId"
            @remove="removeItem(index)"
            @update="updateItem(index, $event)"
          />
        </div>
      </div>

      <div class="right-panel">
        <h3>Settings</h3>

        <label>Status token</label>
        <input v-model="statusToken" type="password" />

        <label>Namespace</label>
        <select v-model="namespaceId" :disabled="!props.is_maintainer">
          <option value="">All</option>
          <option v-for="ns in namespaces" :key="ns.id" :value="ns.id">
            {{ ns.name }}
          </option>
        </select>

        <CdxCheckbox v-model="dryRun">Dry run</CdxCheckbox>
      </div>
    </div>

    <div class="submit-bar">
      <CdxButton
        action="progressive"
        weight="primary"
        type="button"
        @click="submitJob"
      >
        Create rollback job
      </CdxButton>
    </div>

    <pre id="create-result">{{ createResult }}</pre>

    <h3>Your jobs</h3>
    <p>Showing active jobs, failed jobs from the last 24 hours, and completed jobs from the last 2 hours.</p>
    <p>To cancel a queued or running job, use the <em>Cancel rollback job</em> button in the Actions column.</p>

    <JobsTable :jobs="visibleJobs" :token="statusToken" @job-updated="onJobUpdated" />
  </div>
</template>
