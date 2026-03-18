<script setup lang="ts">
import { ref } from "vue";
import { CdxButton, CdxProgressBar } from "@wikimedia/codex";
import { cancelJob, fetchJobDetails, retryJob } from "../api";

export interface UiJob {
  id: number;
  status: string;
  created: string;
  total: number;
  completed: number;
  failed: number;
}

const props = defineProps<{
  jobs: UiJob[];
  token: string;
}>();

const details = ref<Record<number, string>>({});
const openRows = ref<Record<number, boolean>>({});

function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function progressText(job: UiJob): string {
  const done = (job.completed || 0) + (job.failed || 0);
  return `${done}/${job.total || 0}`;
}

function progressPct(job: UiJob): number {
  const done = (job.completed || 0) + (job.failed || 0);
  return job.total ? Math.round((done / job.total) * 100) : 0;
}

async function toggle(id: number) {
  if (openRows.value[id]) {
    openRows.value[id] = false;
    return;
  }

  const d = await fetchJobDetails(id);
  details.value[id] = `
    <b>Status:</b> ${esc(d.status)}<br>
    <b>Total:</b> ${d.total}<br>
    <b>Completed:</b> ${d.completed}<br>
    <b>Failed:</b> ${d.failed}<br>
    <pre>${esc(JSON.stringify(d.items, null, 2))}</pre>
  `;
  openRows.value[id] = true;
}

async function onRetry(id: number) {
  if (!confirm(`Retry job ${id}?`)) return;
  await retryJob(id);
}

async function onCancel(id: number) {
  if (!confirm(`Cancel job ${id}?`)) return;
  await cancelJob(id, props.token);
}
</script>

<template>
  <table class="wikitable">
    <tr>
      <th>ID</th>
      <th>Status</th>
      <th>Progress</th>
      <th>Created</th>
      <th>Actions</th>
    </tr>

    <template v-for="job in jobs" :key="job.id">
      <tr>
        <td>
          <a href="#" @click.prevent="toggle(job.id)">{{ job.id }}</a>
        </td>

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
          <div class="job-progress">
            <CdxProgressBar
              inline
              :disabled="!(job.status === 'queued' || job.status === 'running')"
              :aria-label="`Job ${job.id} progress`"
            />
          </div>
          <div class="job-progress-text">
            <span>{{ progressText(job) }}</span>
            <span>{{ progressPct(job) }}%</span>
          </div>
        </td>

        <td>{{ job.created }}</td>

        <td>
          <CdxButton
            v-if="job.status === 'failed'"
            action="progressive"
            weight="primary"
            type="button"
            @click="onRetry(job.id)"
          >
            Retry
          </CdxButton>

          <CdxButton
            v-if="job.status === 'queued' || job.status === 'running'"
            action="destructive"
            weight="quiet"
            type="button"
            @click="onCancel(job.id)"
          >
            Cancel rollback job
          </CdxButton>
        </td>
      </tr>

      <tr v-if="openRows[job.id]">
        <td colspan="5">
          <div class="job-details" style="display:block" v-html="details[job.id]"></div>
        </td>
      </tr>
    </template>
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

.job-progress {
  min-width: 160px;
}

.job-progress-text {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  font-size: 0.8125rem;
}
</style>
