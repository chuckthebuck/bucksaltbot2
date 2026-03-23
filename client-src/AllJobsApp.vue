<script setup lang="ts">
import { computed, ref } from "vue";

interface AllJobsRow {
  id: number;
  requestedBy: string;
  status: string;
  dryRun: boolean;
  created: string;
  total: number;
  completed: number;
  failed: number;
}

function asBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return ["1", "true", "yes", "on"].includes(normalized);
  }

  return false;
}

function normalizeAllJobsRow(row: unknown): AllJobsRow | null {
  if (!Array.isArray(row)) return null;

  const id = Number(row[0]);
  if (!Number.isFinite(id) || id <= 0) return null;

  return {
    id,
    requestedBy: String(row[1] ?? ""),
    status: String(row[2] ?? "queued"),
    dryRun: asBoolean(row[3]),
    created: String(row[4] ?? ""),
    total: Number(row[5] ?? 0),
    completed: Number(row[6] ?? 0),
    failed: Number(row[7] ?? 0)
  };
}

const props = JSON.parse(
  document.getElementById("all-jobs-props")!.textContent || "{}"
) as { jobs?: unknown[] };

const jobs = ref<AllJobsRow[]>(
  ((props.jobs as unknown[]) || [])
    .map((j) => normalizeAllJobsRow(j))
    .filter((j): j is AllJobsRow => j !== null)
);

function progressText(job: AllJobsRow): string {
  const done = (job.completed || 0) + (job.failed || 0);
  return `${done}/${job.total || 0}`;
}

function progressPct(job: AllJobsRow): number {
  const done = (job.completed || 0) + (job.failed || 0);
  return job.total ? Math.round((done / job.total) * 100) : 0;
}

function modeLabel(job: AllJobsRow): string {
  return job.dryRun ? "Dry run" : "Live";
}

const orderedJobs = computed(() => jobs.value);
</script>

<template>
  <table class="wikitable">
    <tr>
      <th>ID</th>
      <th>Requested by</th>
      <th>Status</th>
      <th>Mode</th>
      <th>Progress</th>
      <th>Created</th>
    </tr>

    <tr v-for="job in orderedJobs" :key="job.id">
      <td>{{ job.id }}</td>
      <td>{{ job.requestedBy }}</td>
      <td>
        <span
          class="cdx-tag"
          :class="{
            'cdx-tag--status-success': job.status === 'completed',
            'cdx-tag--status-error': job.status === 'failed',
            'cdx-tag--status-warning': job.status === 'queued'
          }"
        >
          {{ job.status }}
        </span>
      </td>
      <td>
        <span
          class="cdx-tag"
          :class="{
            'cdx-tag--mode-dry-run': job.dryRun,
            'cdx-tag--mode-live': !job.dryRun
          }"
        >
          {{ modeLabel(job) }}
        </span>
      </td>
      <td>
        <div class="job-progress-track" :aria-label="`Job ${job.id} progress`">
          <div class="job-progress-fill" :style="{ width: `${progressPct(job)}%` }"></div>
        </div>
        <div class="job-progress-text">
          <span>{{ progressText(job) }}</span>
          <span>{{ progressPct(job) }}%</span>
        </div>
      </td>
      <td>{{ job.created }}</td>
    </tr>
  </table>
</template>

<style scoped>
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

.job-progress-track {
  width: 160px;
  height: 8px;
  border-radius: 9999px;
  background: #eaecf0;
  overflow: hidden;
}

.job-progress-fill {
  height: 100%;
  background: var(--color-progressive, #36c);
}

.job-progress-text {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  font-size: 0.8125rem;
}
</style>
