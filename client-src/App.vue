<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { CdxMessage } from "@wikimedia/codex";
import JobsTable, { type UiJob } from "./components/JobsTable.vue";
import { createJob, fetchProgress, getInitialProps, loadEditorsForTitle } from "./api";

const props = getInitialProps();

const requestedBy = ref(props.username || "");

const items = ref<Array<{ title: string; user: string; summary: string }>>([]);

const newItem = ref({
  title: "",
  user: "",
  summary: "",
});

const users = ref<string[]>([]);
const statusToken = ref("");
const namespace = ref("all");
const dryRun = ref(false);
const createResult = ref("");
const pollingTimer = ref<number | null>(null);

const jobs = ref<UiJob[]>(
  props.jobs.map((j) => ({
    id: j.id,
    status: j.status,
    created: j.created,
    total: j.total || 0,
    completed: j.completed || 0,
    failed: j.failed || 0,
  }))
);

const activeJobIds = computed(() =>
  jobs.value
    .filter((j) => !["completed", "failed", "canceled"].includes(j.status))
    .map((j) => j.id)
);

async function loadContributorsForTitle() {
  const title = newItem.value.title.trim();

  if (!title) {
    users.value = [];
    newItem.value.user = "";
    return;
  }

  try {
    const editorData = await loadEditorsForTitle(title);
    users.value = editorData.users;

    if (!users.value.includes(newItem.value.user)) {
      newItem.value.user = editorData.latestUser || "";
    }
  } catch {
    users.value = [];
    newItem.value.user = "";
  }
}

function addItem() {
  if (!newItem.value.title || !newItem.value.user) return;

  items.value.push({ ...newItem.value });

  newItem.value = {
    title: "",
    user: "",
    summary: "",
  };

  users.value = [];
}

function removeItem(index: number) {
  items.value.splice(index, 1);
}

async function submitJob() {
  console.log({
    items: items.value,
    statusToken: statusToken.value,
    namespace: namespace.value,
    dryRun: dryRun.value,
  });

  if (!items.value.length) return;

  const payload = items.value.map((item) => ({
    title: item.title,
    user: item.user,
    summary: item.summary || null,
  }));

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
    <CdxMessage class="top-message">
      Submitting a job will trigger your configured rollback bot account on Wikimedia Commons.
      You are responsible for reviewing results.
    </CdxMessage>

    <div class="layout">
      <div class="left-panel">
        <h3>Create job</h3>

        <div class="item-row">
          <input
            v-model="newItem.title"
            placeholder="Search page"
            @change="loadContributorsForTitle"
          />

          <select v-model="newItem.user">
            <option disabled value="">Select contributor</option>
            <option v-for="u in users" :key="u">{{ u }}</option>
          </select>

          <input v-model="newItem.summary" placeholder="Summary (optional)" />

          <button class="cdx-button" type="button" @click="addItem">Add</button>
        </div>

        <div class="item-list">
          <div v-for="(item, i) in items" :key="i" class="item-card">
            <div>
              <strong>{{ item.title }}</strong> - {{ item.user }}
              <div class="meta">{{ item.summary }}</div>
            </div>

            <button
              class="cdx-button cdx-button--destructive"
              type="button"
              @click="removeItem(i)"
            >
              Remove
            </button>
          </div>
        </div>
      </div>

      <div class="right-panel">
        <h3>Settings</h3>

        <label>Status token</label>
        <input v-model="statusToken" type="password" />

        <label>Namespace</label>
        <select v-model="namespace">
          <option value="all">All</option>
        </select>

        <label>
          <input type="checkbox" v-model="dryRun" />
          Dry run
        </label>
      </div>
    </div>

    <div class="submit-bar">
      <button
        class="cdx-button cdx-button--action-progressive"
        type="button"
        @click="submitJob"
      >
        Create rollback job
      </button>
    </div>

    <pre id="create-result">{{ createResult }}</pre>

    <h3>Your jobs</h3>
    <p>To cancel a queued or running job, use the <em>Cancel rollback job</em> button in the Actions column.</p>

    <JobsTable :jobs="jobs" :token="statusToken" />
  </div>
</template>
