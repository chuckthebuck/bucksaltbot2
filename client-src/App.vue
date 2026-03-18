<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxButton, CdxMessage } from "@wikimedia/codex";
import JobItemRow from "./components/JobItemRow.vue";
import JobsTable, { type UiJob } from "./components/JobsTable.vue";
import { createJob, fetchProgress, getInitialProps, loadNamespaces, type CreateJobItem } from "./api";

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

function normalizeJob(row: unknown): UiJob | null {
  if (Array.isArray(row)) {
    // rollback_queue.html currently injects DB tuples:
    // [id, requested_by, status, dry_run, created_at]
    const id = Number(row[0]);
    if (!Number.isFinite(id) || id <= 0) return null;

    return {
      id,
      status: String(row[2] ?? "queued"),
      created: String(row[4] ?? ""),
      total: 0,
      completed: 0,
      failed: 0,
    };
  }

  if (row && typeof row === "object") {
    const obj = row as Partial<UiJob>;
    const id = Number(obj.id);
    if (!Number.isFinite(id) || id <= 0) return null;

    return {
      id,
      status: String(obj.status ?? "queued"),
      created: String(obj.created ?? ""),
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
    .filter((j) => !["completed", "failed", "canceled"].includes(j.status))
    .map((j) => j.id)
);

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
      created: "just now",
      total: payload.length,
      completed: 0,
      failed: 0,
    });
  }
}

async function refresh() {
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

        <label class="inline-checkbox">
          <input type="checkbox" v-model="dryRun" />
          Dry run
        </label>
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
    <p>To cancel a queued or running job, use the <em>Cancel rollback job</em> button in the Actions column.</p>

    <JobsTable :jobs="jobs" :token="statusToken" />
  </div>
</template>
