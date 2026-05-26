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
const nonBlankOnly = ref(false);
const uniqueOnly = ref(true);
const runLimit = ref(50);
const apiReturned = ref(0);

function runHasNonBlankResult(run: ModuleRunItem): boolean {
  const result = run.result;
  if (!result) return run.status !== "succeeded";
  if (result.has_nominations === true) return true;
  if (Number(result.nomination_count || 0) > 0) return true;
  if (Array.isArray(result.dry_run_edits) && result.dry_run_edits.length > 0) return true;
  return result.run_kind !== "empty" && result.has_nominations !== false;
}

function runResultLabel(run: ModuleRunItem): string {
  const result = run.result;
  if (!result) return "Pending";
  if (result.run_kind === "empty" || result.has_nominations === false) return "Blank";
  if (result.run_kind === "reviewed" || result.has_nominations === true) {
    const count = Number(result.nomination_count || 0);
    return count === 1 ? "1 nomination" : `${count} nominations`;
  }
  return result.run_kind || "Result";
}

const displayedRuns = computed(() =>
  nonBlankOnly.value ? runs.value.filter(runHasNonBlankResult) : runs.value
);

const selectedRun = computed(
  () =>
    displayedRuns.value.find((run) => run.id === selectedRunId.value) ||
    displayedRuns.value[0] ||
    null
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
    const data = await fetchFourAwardRuns({
      unique: uniqueOnly.value,
      limit: runLimit.value,
    });
    jobs.value = data.jobs.map((job) => ({
      name: job.name,
      enabled: job.enabled,
    }));
    runs.value = data.runs;
    apiReturned.value = data.returned || data.runs.length;
    if (!selectedJob.value) {
      selectedJob.value = jobs.value.find((job) => job.enabled)?.name || jobs.value[0]?.name || "";
    }
    if (!selectedRunId.value && runs.value.length > 0) {
      selectedRunId.value = runs.value[0].id;
    }
    if (
      selectedRunId.value &&
      !displayedRuns.value.some((run) => run.id === selectedRunId.value)
    ) {
      selectedRunId.value = displayedRuns.value[0]?.id || null;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load 4award runs.";
  } finally {
    loading.value = false;
  }
}

async function reloadRunsWithCurrentFilters(): Promise<void> {
  selectedRunId.value = null;
  await loadRuns();
}

async function loadMoreRuns(): Promise<void> {
  runLimit.value = Math.min(runLimit.value + 50, 1000);
  await loadRuns();
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
        <div class="four-award-runs-header">
          <h3>Recent Runs</h3>
          <label class="four-award-filter">
            <input v-model="nonBlankOnly" type="checkbox">
            <span>Non-blank only</span>
          </label>
          <label class="four-award-filter">
            <input
              v-model="uniqueOnly"
              type="checkbox"
              :disabled="loading"
              @change="reloadRunsWithCurrentFilters"
            >
            <span>Unique historical claims only</span>
          </label>
        </div>
        <p class="help-text">
          Showing {{ displayedRuns.length }} of {{ runs.length }} loaded runs.
        </p>
        <table class="four-award-runs">
          <thead>
            <tr>
              <th>Run</th>
              <th>Status</th>
              <th>Result</th>
              <th>Trigger</th>
              <th>Diff</th>
              <th>Output</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="displayedRuns.length === 0">
              <td colspan="6">
                {{ runs.length === 0 ? "No 4award runs recorded yet." : "No non-blank runs match the current filter." }}
              </td>
            </tr>
            <tr
              v-for="run in displayedRuns"
              :key="run.id"
              :class="{ selected: selectedRun?.id === run.id }"
              @click="selectedRunId = run.id"
            >
              <td>#{{ run.id }}</td>
              <td>{{ run.status }}</td>
              <td>{{ runResultLabel(run) }}</td>
              <td>{{ run.trigger_type }}</td>
              <td>{{ oldidFromPayload(run) }}</td>
              <td>
                <a :href="moduleRunReportUrl(run.id)">Report</a>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="four-award-load-more">
          <CdxButton
            weight="quiet"
            :disabled="loading || runLimit >= 1000"
            @click="loadMoreRuns"
          >
            Load 50 more
          </CdxButton>
          <span class="help-text">
            Loaded {{ apiReturned }} runs from the latest {{ runLimit }} checked.
          </span>
        </div>
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

<style>
.four-award-page {
  display: grid;
  gap: 1.5rem;
  max-width: 100%;
}

.four-award-page h3,
.four-award-page h4 {
  margin: 0;
}

.four-award-runner {
  border: 1px solid #c8ccd1;
  border-radius: 4px;
  padding: 1rem;
  background: #fff;
}

.top-message {
  margin-bottom: 0;
}

.help-text {
  color: #54595d;
  margin: 0.35rem 0 0.75rem;
}

.four-award-form {
  display: grid;
  grid-template-columns: minmax(12rem, 18rem) minmax(18rem, 1fr) auto;
  gap: 0.75rem;
  align-items: end;
}

.four-award-form label {
  display: grid;
  gap: 0.25rem;
  font-weight: 700;
}

.four-award-form select,
.four-award-form input {
  box-sizing: border-box;
  width: 100%;
  min-height: 32px;
  border: 1px solid #72777d;
  border-radius: 2px;
  padding: 4px 8px;
  font: inherit;
}

.four-award-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(20rem, 32rem);
  gap: 1.25rem;
  align-items: start;
}

.four-award-runs-header,
.four-award-output-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.four-award-filter {
  display: inline-flex;
  gap: 0.35rem;
  align-items: center;
  color: #54595d;
}

.four-award-load-more {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.four-award-runs {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #c8ccd1;
}

.four-award-runs th,
.four-award-runs td {
  padding: 0.55rem 0.7rem;
  border-bottom: 1px solid #eaecf0;
  text-align: left;
  vertical-align: top;
}

.four-award-runs th {
  background: #f8f9fa;
  font-weight: 700;
}

.four-award-runs tbody tr {
  cursor: pointer;
}

.four-award-runs tbody tr:hover,
.four-award-runs tbody tr.selected {
  background: #eef3ff;
}

.four-award-output {
  border: 1px solid #c8ccd1;
  border-radius: 4px;
  padding: 1rem;
  background: #fff;
}

.four-award-summary {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.35rem 0.75rem;
  margin: 1rem 0;
}

.four-award-summary dt {
  color: #54595d;
  font-weight: 700;
}

.four-award-summary dd {
  margin: 0;
}

.four-award-edit {
  border: 1px solid #eaecf0;
  border-radius: 4px;
  margin: 0.5rem 0;
  padding: 0.5rem;
}

.four-award-edit summary {
  cursor: pointer;
  font-weight: 700;
}

.four-award-edit pre,
.four-award-report {
  max-height: 22rem;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f8f9fa;
  border: 1px solid #eaecf0;
  border-radius: 4px;
  padding: 0.75rem;
}

@media (max-width: 900px) {
  .four-award-form,
  .four-award-layout {
    grid-template-columns: 1fr;
  }
}
</style>
