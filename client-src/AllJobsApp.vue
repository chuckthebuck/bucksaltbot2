<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchAllJobs, type AllJobsRow as ApiAllJobsRow } from "./api";
import { fetchJobDetails } from "./api";

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
  if (!row || typeof row !== "object") return null;

  const obj = row as Record<string, unknown>;
  const id = Number(obj.id);
  if (!Number.isFinite(id) || id <= 0) return null;

  return {
    id,
    requestedBy: String(obj.requested_by ?? ""),
    status: String(obj.status ?? "queued"),
    dryRun: asBoolean(obj.dry_run),
    created: String(obj.created_at ?? ""),
    total: Number(obj.total ?? 0),
    completed: Number(obj.completed ?? 0),
    failed: Number(obj.failed ?? 0)
  };
}

const jobs = ref<AllJobsRow[]>([]);
const loading = ref(true);
const error = ref("");
const details = ref<Record<number, string>>({});
const openRows = ref<Record<number, boolean>>({});

onMounted(async () => {
  try {
    const rows = await fetchAllJobs();
    jobs.value = (rows as ApiAllJobsRow[])
      .map((j) => normalizeAllJobsRow(j))
      .filter((j): j is AllJobsRow => j !== null);
  } catch (e) {
    console.error("Failed to load all jobs:", e);
    error.value = "Failed to load all jobs.";
  } finally {
    loading.value = false;
  }
});

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

function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function toggle(id: number) {
  if (openRows.value[id]) {
    openRows.value[id] = false;
    return;
  }

  const d = await fetchJobDetails(id);
  const isDryRun = !!((d as { dry_run?: boolean; dryRun?: boolean }).dry_run ??
    (d as { dry_run?: boolean; dryRun?: boolean }).dryRun);

  details.value[id] = `
    <b>Status:</b> ${esc(d.status)}<br>
    <b>Mode:</b> ${isDryRun ? "Dry run" : "Live"}<br>
    <b>Total:</b> ${d.total}<br>
    <b>Completed:</b> ${d.completed}<br>
    <b>Failed:</b> ${d.failed}<br>
    <pre>${esc(JSON.stringify(d.items, null, 2))}</pre>
  `;
  openRows.value[id] = true;
}

const orderedJobs = computed(() => jobs.value);
</script>

<template>
  <div class="all-jobs-table-wrap">
    <div v-if="loading" class="all-jobs-table__empty">Loading jobs...</div>
    <div v-else-if="error" class="all-jobs-table__empty">{{ error }}</div>
    <table v-else class="all-jobs-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Requested by</th>
          <th>Status</th>
          <th>Mode</th>
          <th>Progress</th>
          <th>Created</th>
          <th>Links</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="job in orderedJobs" :key="job.id">
          <tr>
            <td class="all-jobs-table__id"><a href="#" @click.prevent="toggle(job.id)">{{ job.id }}</a></td>
            <td>{{ job.requestedBy }}</td>
            <td>
              <span
                class="cdx-tag"
                :class="{
                  'cdx-tag--status-success': job.status === 'completed',
                  'cdx-tag--status-error': job.status === 'failed',
                  'cdx-tag--status-warning': job.status === 'queued' || job.status === 'running',
                  'cdx-tag--status-muted': job.status === 'canceled'
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
            <td class="all-jobs-table__created">{{ job.created }}</td>
            <td class="all-jobs-table__links">
              <a :href="`/api/v1/rollback/jobs/${job.id}`" target="_blank" rel="noopener noreferrer">JSON</a>
              <span aria-hidden="true"> | </span>
              <a :href="`/api/v1/rollback/jobs/${job.id}?format=log`" target="_blank" rel="noopener noreferrer">Log</a>
            </td>
          </tr>
          <tr v-if="openRows[job.id]">
            <td colspan="7">
              <div class="job-details" style="display:block" v-html="details[job.id]"></div>
            </td>
          </tr>
        </template>
        <tr v-if="!orderedJobs.length">
          <td colspan="7" class="all-jobs-table__empty">No jobs found.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.all-jobs-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.all-jobs-table {
  width: 100%;
  min-width: 860px;
  border-collapse: separate;
  border-spacing: 0;
}

.all-jobs-table th,
.all-jobs-table td {
  padding: 8px 10px;
  vertical-align: middle;
}

.all-jobs-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background-color: var(--background-color-neutral, #eaecf0);
  text-align: left;
  white-space: nowrap;
}

.all-jobs-table tbody tr:nth-child(odd) {
  background-color: var(--background-color-base, #fff);
}

.all-jobs-table tbody tr:nth-child(even) {
  background-color: var(--background-color-neutral-subtle, #f8f9fa);
}

.all-jobs-table tbody tr:hover {
  background-color: #f1f4fd;
}

.all-jobs-table__id {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.all-jobs-table__created {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.all-jobs-table__links {
  white-space: nowrap;
}

.all-jobs-table__empty {
  text-align: center;
  color: var(--color-subtle, #54595d);
  padding: 20px;
}

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

.cdx-tag--status-muted {
  background-color: var(--background-color-disabled-subtle, #f0f0f0);
  border-color: var(--border-color-subtle, #c8ccd1);
  color: var(--color-subtle, #54595d);
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
  width: 180px;
  height: 10px;
  border-radius: 9999px;
  background: var(--background-color-neutral, #eaecf0);
  border: 1px solid var(--border-color-subtle, #c8ccd1);
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
