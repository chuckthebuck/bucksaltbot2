<script setup lang="ts">
import { ref } from "vue";
import { CdxButton, CdxProgressBar } from "@wikimedia/codex";
import { cancelJob, fetchJobDetails, retryJob } from "../api";
import UnifiedTable from "./UnifiedTable.vue";
import {
  actionColumn,
  type TableColumn,
} from "./unifiedTable";
import {
  buttonCell,
  dryRunModeColumn,
  linkCell,
  modeLabel,
  progressPercent,
  progressSummary,
  statusTagColumn,
  textColumn,
} from "./tableColumnFactories";

export interface UiJob {
  id: number;
  status: string;
  dryRun: boolean;
  created: string;
  total: number;
  completed: number;
  failed: number;
}

const props = defineProps<{
  jobs: UiJob[];
  token: string;
}>();

const emit = defineEmits<{
  (e: "job-updated"): void;
}>();

const details = ref<Record<number, string>>({});
const openRows = ref<Record<number, boolean>>({});

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

async function onRetry(id: number) {
  if (!confirm(`Retry job ${id}?`)) return;
  await retryJob(id);
  emit("job-updated");
}

async function onCancel(id: number) {
  if (!confirm(`Cancel job ${id}?`)) return;
  await cancelJob(id, props.token);
  emit("job-updated");
}

const columns: TableColumn<UiJob>[] = [
  {
    key: "id",
    label: "ID",
    render: (job) => linkCell(job.id, "#", {
      onClick: (event) => {
        event.preventDefault();
        void toggle(job.id);
      },
    }),
  },
  statusTagColumn("status", "Status", (job) => job.status),
  dryRunModeColumn("mode", "Mode", (job) => job.dryRun),
  {
    key: "progress",
    label: "Progress",
    render: (job) => [
      {
        component: CdxProgressBar,
        key: `bar-${job.id}`,
        props: {
          inline: true,
          disabled: !(job.status === "queued" || job.status === "running"),
          "aria-label": `Job ${job.id} progress`,
        },
      },
      {
        component: "span",
        key: `text-${job.id}`,
        props: {
          class: "job-progress-inline-text",
        },
        children: `${progressSummary(job)} (${progressPercent(job)}%)`,
      },
    ],
  },
  textColumn("created", "Created", (job) => job.created),
  actionColumn("retry", "Retry", (job) => {
    if (!(job.status === "failed" || job.status === "resolving")) return null;
    return buttonCell(CdxButton, "Retry", () => {
      void onRetry(job.id);
    }, {
      action: "progressive",
      weight: "primary",
    });
  }),
  actionColumn("cancel", "Cancel", (job) => {
    if (!(
      job.status === "queued" ||
      job.status === "running" ||
      job.status === "resolving" ||
      job.status === "staging" ||
      job.status === "pending_approval"
    )) {
      return null;
    }

    return buttonCell(CdxButton, "Cancel rollback job", () => {
      void onCancel(job.id);
    }, {
      action: "destructive",
      weight: "quiet",
    });
  }),
];

function isExpandedRow(row: unknown): boolean {
  const id = (row as UiJob).id;
  return Boolean(openRows.value[id]);
}

function detailsHtml(row: unknown): string {
  const id = (row as UiJob).id;
  return details.value[id] || "";
}
</script>

<template>
  <UnifiedTable
    :rows="jobs"
    :columns="columns"
    row-key="id"
    table-class="jobs-table"
    empty-text="No jobs found."
    :expanded="isExpandedRow"
  >
    <template #expanded="{ row }">
      <div class="job-details" style="display:block" v-html="detailsHtml(row)"></div>
    </template>
  </UnifiedTable>
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

.job-progress-inline-text {
  font-size: 0.8125rem;
  white-space: nowrap;
}

:deep(.jobs-table td) {
  white-space: nowrap;
}
</style>
