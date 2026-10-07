<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CdxButton, CdxMessage, CdxProgressBar } from "@wikimedia/codex";

interface InitialProps {
  username?: string | null;
  can_run?: boolean;
  can_edit_config?: boolean;
}

interface ModuleRun {
  id: number;
  job_name: string;
  status: string;
  trigger_type?: string;
  triggered_by?: string | null;
  created_at?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

interface JobResponse {
  jobs?: Array<{ name: string; enabled: boolean }>;
  runs?: ModuleRun[];
}

function initialProps(): InitialProps {
  const element = document.getElementById("self-delete-props");
  try {
    return JSON.parse(element?.textContent || "{}") as InitialProps;
  } catch {
    return {};
  }
}

async function jsonResponse<T>(response: Response): Promise<T> {
  const data = (await response.json().catch(() => ({}))) as T & { detail?: string };
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

const props = initialProps();
const loading = ref(true);
const queueing = ref(false);
const error = ref("");
const success = ref("");
const config = ref<Record<string, unknown>>({});
const jobs = ref<Array<{ name: string; enabled: boolean }>>([]);
const runs = ref<ModuleRun[]>([]);

const dryRun = computed(() => config.value.dry_run !== false);
const enabled = computed(() => config.value.enabled !== false);
const category = computed(() =>
  String(config.value.category_title || "Category:Other speedy deletions")
);
const workerCount = computed(() => Number(config.value.workers || 4));
const candidateLimit = computed(() => Number(config.value.max_candidates || 250));
const runnableJob = computed(
  () => jobs.value.find((job) => job.name === "self-delete-sync") || jobs.value[0]
);
const canQueue = computed(
  () => Boolean(props.can_run && dryRun.value && enabled.value && runnableJob.value?.enabled)
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [configResponse, jobsResponse] = await Promise.all([
      fetch("/api/v1/modules/self_delete/config", {
        cache: "no-store",
        credentials: "same-origin",
      }),
      fetch("/api/v1/modules/self_delete/jobs", {
        cache: "no-store",
        credentials: "same-origin",
      }),
    ]);
    const configPayload = await jsonResponse<{ config?: Record<string, unknown> }>(
      configResponse
    );
    const jobsPayload = await jsonResponse<JobResponse>(jobsResponse);
    config.value = configPayload.config || {};
    jobs.value = Array.isArray(jobsPayload.jobs) ? jobsPayload.jobs : [];
    runs.value = Array.isArray(jobsPayload.runs) ? jobsPayload.runs : [];
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : "Unable to load module state.";
  } finally {
    loading.value = false;
  }
}

async function queueDryRun(): Promise<void> {
  if (!canQueue.value || !runnableJob.value) return;
  queueing.value = true;
  error.value = "";
  success.value = "";
  try {
    // Re-read configuration immediately before enqueueing. The backend also
    // ignores payload attempts to override dry_run, so this button can never
    // turn a protected run into a live deletion run.
    const configResponse = await fetch("/api/v1/modules/self_delete/config", {
      cache: "no-store",
      credentials: "same-origin",
    });
    const configPayload = await jsonResponse<{ config?: Record<string, unknown> }>(
      configResponse
    );
    config.value = configPayload.config || {};
    if (config.value.dry_run === false) {
      throw new Error("Dry-run mode is off. Re-enable it in module configuration first.");
    }

    const response = await fetch(
      `/api/v1/modules/self_delete/jobs/${encodeURIComponent(runnableJob.value.name)}/runs`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ source: "self_delete_ui_dry_run", dry_run: true }),
      }
    );
    const queued = await jsonResponse<{ run_id: number }>(response);
    success.value = `Dry run ${queued.run_id} was queued. Eligible files will be logged, not deleted.`;
    await load();
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : "Unable to queue dry run.";
  } finally {
    queueing.value = false;
  }
}

function reportUrl(runId: number): string {
  return `/modules/runs/${runId}/report`;
}

onMounted(load);
</script>

<template>
  <main class="self-delete">
    <header class="self-delete__header">
      <div>
        <p class="self-delete__eyebrow">Commons safety module</p>
        <h1>Self Delete</h1>
        <p>
          Find uploader-requested G7 files, validate every safety condition, and
          hand eligible work to the dedicated queue.
        </p>
      </div>
      <span class="self-delete__identity">{{ props.username || "Unknown operator" }}</span>
    </header>

    <CdxProgressBar v-if="loading" aria-label="Loading Self Delete" />

    <template v-else>
      <CdxMessage v-if="error" type="error" class="self-delete__message">
        {{ error }}
      </CdxMessage>
      <CdxMessage v-if="success" type="success" class="self-delete__message">
        {{ success }}
      </CdxMessage>
      <CdxMessage :type="dryRun ? 'success' : 'warning'" class="self-delete__message">
        <template v-if="dryRun">
          Dry-run protection is on. Queue workers will revalidate candidates and record
          the decision without sending a delete request.
        </template>
        <template v-else>
          Live mode is configured. This page will not offer the manual dry-run button
          until dry-run protection is restored.
        </template>
      </CdxMessage>

      <section class="self-delete__grid" aria-label="Effective configuration">
        <article><strong>Category</strong><span>{{ category }}</span></article>
        <article><strong>Maximum age</strong><span>Strictly under 7 days</span></article>
        <article><strong>Validation workers</strong><span>{{ workerCount }}</span></article>
        <article><strong>Candidate limit</strong><span>{{ candidateLimit }}</span></article>
      </section>

      <section class="self-delete__panel">
        <div>
          <h2>Safe test run</h2>
          <p>
            Uses the normal scheduler, SQL audit log, dedicated queue tables, and
            worker recheck. Deletion is suppressed by persisted module configuration.
          </p>
        </div>
        <CdxButton
          action="progressive"
          weight="primary"
          :disabled="!canQueue || queueing"
          @click="queueDryRun"
        >
          {{ queueing ? "Queueing…" : "Run dry test" }}
        </CdxButton>
      </section>

      <CdxMessage v-if="!props.can_run" type="notice" class="self-delete__message">
        Your account can view this module but does not have permission to run its job.
      </CdxMessage>

      <section class="self-delete__runs">
        <div class="self-delete__runs-heading">
          <div>
            <h2>Recent framework runs</h2>
            <p>Detailed per-file checks are retained in the Self Delete audit tables.</p>
          </div>
          <CdxButton weight="quiet" @click="load">Refresh</CdxButton>
        </div>
        <div class="self-delete__table-wrap">
          <table>
            <thead>
              <tr><th>Run</th><th>Status</th><th>Trigger</th><th>Operator</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="run in runs.slice(0, 20)" :key="run.id">
                <td>#{{ run.id }}</td>
                <td><span class="self-delete__status">{{ run.status }}</span></td>
                <td>{{ run.trigger_type || "scheduled" }}</td>
                <td>{{ run.triggered_by || "scheduler" }}</td>
                <td><a :href="reportUrl(run.id)">View output</a></td>
              </tr>
              <tr v-if="runs.length === 0">
                <td colspan="5" class="self-delete__empty">No runs have been recorded.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </main>
</template>
