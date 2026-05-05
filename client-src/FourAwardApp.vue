<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CdxButton, CdxMessage } from "@wikimedia/codex";
import {
  fetchFourAwardRun,
  fetchFourAwardRuns,
  queueFourAwardHistoricalDiffTest,
  type ModuleRunItem,
} from "./api";

interface InitialProps {
  username: string | null;
  can_run: boolean;
}

function parseProps(): InitialProps {
  const el = document.getElementById("four-award-props");
  if (!el?.textContent) return { username: null, can_run: false };
  try {
    const parsed = JSON.parse(el.textContent);
    return {
      username: parsed.username ?? null,
      can_run: !!parsed.can_run,
    };
  } catch {
    return { username: null, can_run: false };
  }
}

const props = parseProps();
const loading = ref(true);
const queueing = ref(false);
const refreshingRun = ref<number | null>(null);
const error = ref("");
const success = ref("");
const jobs = ref<Array<{ name: string; enabled: boolean }>>([]);
const runs = ref<ModuleRunItem[]>([]);
const selectedJob = ref("");
const historicalDiff = ref("");
const selectedRunId = ref<number | null>(null);

const selectedRun = computed(
  () => runs.value.find((run) => run.id === selectedRunId.value) || runs.value[0] || null
);

const dryRunEdits = computed(() => {
  const edits = selectedRun.value?.result?.dry_run_edits;
  return Array.isArray(edits) ? edits : [];
});

const reportWikitext = computed(
  () => selectedRun.value?.result?.dry_run_report?.wikitext || ""
);

function moduleRunReportUrl(runId: number): string {
  return `/modules/runs/${runId}/report`;
}

function oldidFromPayload(run: ModuleRunItem): string {
  const value = run.payload?.oldid ?? run.payload?.diff ?? "";
  return String(value || "");
}

async function loadRuns(): Promise<void> {
  try {
    loading.value = true;
    error.value = "";
    const data = await fetchFourAwardRuns();
    jobs.value = data.jobs.map((job) => ({
      name: job.name,
      enabled: job.enabled,
    }));
    runs.value = data.runs;
    if (!selectedJob.value) {
      selectedJob.value = jobs.value.find((job) => job.enabled)?.name || jobs.value[0]?.name || "";
    }
    if (!selectedRunId.value && runs.value.length > 0) {
      selectedRunId.value = runs.value[0].id;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load 4award runs.";
  } finally {
    loading.value = false;
  }
}

async function refreshRun(runId: number): Promise<void> {
  try {
    refreshingRun.value = runId;
    error.value = "";
    const data = await fetchFourAwardRun(runId);
    const index = runs.value.findIndex((run) => run.id === runId);
    if (index >= 0) {
      runs.value.splice(index, 1, data.run);
    } else {
      runs.value = [data.run, ...runs.value];
    }
    selectedRunId.value = runId;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to refresh run.";
  } finally {
    refreshingRun.value = null;
  }
}

async function queueHistoricalDiffTest(): Promise<void> {
  const diff = historicalDiff.value.trim();
  if (!diff) {
    error.value = "Enter a revision id or diff URL.";
    return;
  }

  try {
    queueing.value = true;
    error.value = "";
    success.value = "";
    const queued = await queueFourAwardHistoricalDiffTest({
      diff,
      job_name: selectedJob.value || undefined,
    });
    success.value = `Queued dry-run #${queued.run_id}.`;
    historicalDiff.value = "";
    await loadRuns();
    selectedRunId.value = queued.run_id;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to queue dry-run.";
  } finally {
    queueing.value = false;
  }
}

onMounted(() => {
  void loadRuns();
});
</script>

<template>
  <div class="four-award-page">
    <CdxMessage v-if="error" type="error" class="top-message">
      {{ error }}
    </CdxMessage>
    <CdxMessage v-if="success" type="success" class="top-message">
      {{ success }}
    </CdxMessage>

    <section class="four-award-runner">
      <h3>Historical Diff Dry Run</h3>
      <p class="help-text">
        Queues a dry-run module job with this diff as test input. The result stays
        in Chuckbot run output unless the module explicitly reports otherwise.
      </p>
      <div class="four-award-form">
        <label>
          <span>Job</span>
          <select v-model="selectedJob" :disabled="!props.can_run || queueing">
            <option v-for="job in jobs" :key="job.name" :value="job.name">
              {{ job.name }}{{ job.enabled ? "" : " (disabled)" }}
            </option>
          </select>
        </label>
        <label>
          <span>Historical diff</span>
          <input
            v-model="historicalDiff"
            :disabled="!props.can_run || queueing"
            type="text"
            placeholder="Revision id or diff URL"
            @keyup.enter="queueHistoricalDiffTest"
          >
        </label>
        <CdxButton
          action="progressive"
          weight="primary"
          :disabled="!props.can_run || queueing || !historicalDiff.trim()"
          @click="queueHistoricalDiffTest"
        >
          {{ queueing ? "Queueing..." : "Queue dry run" }}
        </CdxButton>
      </div>
    </section>

    <div v-if="loading" class="help-text">Loading 4award runs...</div>

    <section v-else class="four-award-layout">
      <div>
        <h3>Recent Runs</h3>
        <table class="four-award-runs">
          <thead>
            <tr>
              <th>Run</th>
              <th>Status</th>
              <th>Trigger</th>
              <th>Diff</th>
              <th>Output</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="runs.length === 0">
              <td colspan="5">No 4award runs recorded yet.</td>
            </tr>
            <tr
              v-for="run in runs"
              :key="run.id"
              :class="{ selected: selectedRun?.id === run.id }"
              @click="selectedRunId = run.id"
            >
              <td>#{{ run.id }}</td>
              <td>{{ run.status }}</td>
              <td>{{ run.trigger_type }}</td>
              <td>{{ oldidFromPayload(run) }}</td>
              <td>
                <a :href="moduleRunReportUrl(run.id)">Report</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <aside class="four-award-output">
        <div v-if="selectedRun">
          <div class="four-award-output-header">
            <h3>Run #{{ selectedRun.id }}</h3>
            <CdxButton
              weight="quiet"
              :disabled="refreshingRun === selectedRun.id"
              @click="refreshRun(selectedRun.id)"
            >
              {{ refreshingRun === selectedRun.id ? "Refreshing..." : "Refresh" }}
            </CdxButton>
          </div>
          <dl class="four-award-summary">
            <dt>Status</dt>
            <dd>{{ selectedRun.status }}</dd>
            <dt>Dry-run edits</dt>
            <dd>{{ dryRunEdits.length }}</dd>
            <dt>Finished</dt>
            <dd>{{ selectedRun.finished_at || "Not finished" }}</dd>
          </dl>

          <h4>Proposed Edits</h4>
          <div v-if="dryRunEdits.length === 0" class="help-text">
            No proposed edits were recorded for this run.
          </div>
          <details v-for="(edit, index) in dryRunEdits" :key="index" class="four-award-edit">
            <summary>{{ edit.title || `Edit ${index + 1}` }}</summary>
            <p v-if="edit.summary">{{ edit.summary }}</p>
            <pre>{{ edit.diff || "No diff text was captured." }}</pre>
          </details>

          <h4>Report Wikitext</h4>
          <pre class="four-award-report">{{ reportWikitext || "No report wikitext captured." }}</pre>
        </div>
        <div v-else class="help-text">Select a run to inspect its output.</div>
      </aside>
    </section>
  </div>
</template>
