<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxButton, CdxCheckbox, CdxMessage } from "@wikimedia/codex";
import JobItemRow from "./components/JobItemRow.vue";
import JobsTable, { type UiJob } from "./components/JobsTable.vue";
import { createJob, fetchProgress, getInitialProps, loadNamespaces, type CreateJobItem } from "./api";

const props = getInitialProps();

const requestedBy = ref(props.username || "");
const token = ref("");
const dryRun = ref(false);
const namespaceId = ref("");
const namespaces = ref<Array<{ id: string; name: string }>>([]);
const createResult = ref("");
const pollingTimer = ref<number | null>(null);
<template>
  <h1 style="color:red;">APP IS RENDERING</h1>
</template>
const items = ref<Array<{ key: number; data: CreateJobItem | null }>>([
  { key: Date.now(), data: null },
]);

const jobs = ref<UiJob[]>(
  props.jobs.map((j) => ({
    id: j[0],
    status: j[2],
    created: j[4],
    total: 0,
    completed: 0,
    failed: 0,
  }))
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

async function submit() {
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
    token: token.value || undefined,
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

  const data = await fetchProgress(activeJobIds.value);

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
  <div class="container">
    <cdx-message class="top-message">
      Submitting a job will trigger your configured rollback bot account on Wikimedia Commons.
      You are responsible for reviewing results.
    </cdx-message>

    <h3>Create job</h3>

    <form @submit.prevent="submit" class="rollback-tool-form">
      <input v-model="requestedBy" type="hidden" id="requested-by" />

      <label for="token">Status token (optional)</label>
      <input id="token" v-model="token" type="password" />

      <br /><br />

      <label for="namespace-select">Namespace</label>
      <select id="namespace-select" v-model="namespaceId" :disabled="!props.is_maintainer">
        <option value="">All</option>
        <option v-for="ns in namespaces" :key="ns.id" :value="ns.id">
          {{ ns.name }}
        </option>
      </select>

      <br /><br />

      <cdx-button type="button" @click="addItem">Add item</cdx-button>

      <div id="job-items" class="job-items">
        <JobItemRow
          v-for="(item, index) in items"
          :key="item.key"
          :namespace-id="namespaceId"
          @remove="removeItem(index)"
          @update="updateItem(index, $event)"
        />
      </div>

      <label>
        <input v-model="dryRun" type="checkbox" id="dry" />
        Dry run
      </label>

      <br /><br />

      <cdx-button action="progressive" weight="primary" type="submit">
        Create rollback job
      </cdx-button>
    </form>

    <pre id="create-result">{{ createResult }}</pre>

    <h3>Your jobs</h3>
    <p>To cancel a queued or running job, use the <em>Cancel rollback job</em> button in the Actions column.</p>

    <JobsTable :jobs="jobs" :token="token" />
  </div>
</template>
