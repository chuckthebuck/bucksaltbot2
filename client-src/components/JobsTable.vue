<script setup lang="ts">
import { ref } from "vue";
import { CdxButton } from "@wikimedia/codex";
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
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
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
          <span :class="`status status-${job.status}`">
            {{ job.status }}
          </span>
        </td>

        <td>
          <div class="progress">
            <div :style="{ width: `${progressPct(job)}%` }"></div>
          </div>
          <span>{{ progressText(job) }}</span>
        </td>

        <td>{{ job.created }}</td>

        <td>
          <Cdxbutton
            v-if="job.status === 'failed'"
            weight="quiet"
            @click="onRetry(job.id)"
          >
            Retry
          </Cdxbutton>

          <Cdxbutton
            v-if="job.status === 'queued' || job.status === 'running'"
            action="destructive"
            weight="quiet"
            @click="onCancel(job.id)"
          >
            Cancel rollback job
          </Cdxbutton>
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
