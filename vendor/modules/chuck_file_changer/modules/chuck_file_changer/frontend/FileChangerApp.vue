<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type Mode = "replace" | "prepend" | "append";

interface PlanItem {
  title: string;
  status: string;
  changed: boolean;
  diff?: string;
  error?: string | null;
}

interface RunResult {
  dry_run: boolean;
  target_count: number;
  planned_count: number;
  changed_count: number;
  saved_count: number;
  error_count: number;
  source_url?: string | null;
  items: PlanItem[];
}

interface QueuedRun {
  id?: number;
  run_id?: number;
  status: string;
  error?: string | null;
  result?: RunResult | null;
}

const props = JSON.parse(
  document.getElementById("chuck-file-changer-props")?.textContent || "{}"
);

const sourceMode = ref<"manual" | "quarry">("manual");
const targetsText = ref("");
const quarry = ref("");
const mode = ref<Mode>("replace");
const find = ref("");
const replace = ref("");
const prepend = ref("");
const append = ref("");
const editSummary = ref("");
const result = ref<RunResult | null>(null);
const runStatus = ref("");
const runId = ref<number | null>(null);
const error = ref("");
const busy = ref(false);
const canApplyRight = ref(false);

const canApply = computed(() =>
  Boolean(canApplyRight.value || props?.can_manage)
);

onMounted(async () => {
  try {
    const response = await fetch("/chuck_file_changer/api/auth", {
      cache: "no-store",
    });
    const data = await response.json();
    canApplyRight.value = Boolean(data?.can_apply);
  } catch {
    canApplyRight.value = false;
  }
});

function payload(apply: boolean) {
  return {
    source_text: sourceMode.value === "manual" ? targetsText.value : "",
    quarry: sourceMode.value === "quarry" ? quarry.value : "",
    mode: mode.value,
    find: find.value,
    replace: replace.value,
    prepend: prepend.value,
    append: append.value,
    edit_summary: editSummary.value,
    dry_run: !apply,
    apply,
  };
}

async function run(apply: boolean) {
  busy.value = true;
  error.value = "";
  result.value = null;
  runStatus.value = "";
  runId.value = null;

  try {
    const response = await fetch(
      apply ? "/chuck_file_changer/api/apply" : "/chuck_file_changer/api/preview",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload(apply)),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }
    runId.value = Number(data?.run_id);
    runStatus.value = String(data?.status || "queued");
    await pollRun(runId.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "Request failed";
  } finally {
    busy.value = false;
  }
}

async function pollRun(id: number) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await fetch(`/chuck_file_changer/api/jobs/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    const data = (await response.json()) as QueuedRun;
    if (!response.ok) {
      throw new Error((data as any)?.detail || `HTTP ${response.status}`);
    }

    runStatus.value = data.status;
    if (data.status === "completed" && data.result) {
      result.value = data.result;
      return;
    }
    if (data.status === "failed" || data.status === "canceled") {
      throw new Error(data.error || `Run ${data.status}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("Run is still pending after 120 seconds");
}
</script>

<template>
  <main class="cfc">
    <section class="cfc-toolbar">
      <div class="cfc-segmented" role="group" aria-label="Source">
        <button :class="{ active: sourceMode === 'manual' }" @click="sourceMode = 'manual'">Manual</button>
        <button :class="{ active: sourceMode === 'quarry' }" @click="sourceMode = 'quarry'">Quarry</button>
      </div>

      <select v-model="mode" aria-label="Operation">
        <option value="replace">Find/replace</option>
        <option value="prepend">Prepend</option>
        <option value="append">Append</option>
      </select>
    </section>

    <section class="cfc-grid">
      <div class="cfc-panel">
        <label v-if="sourceMode === 'manual'">
          Targets
          <textarea
            v-model="targetsText"
            rows="12"
            placeholder="File:Example.jpg&#10;Example2.jpg|Uploader|Optional note"
          />
        </label>

        <label v-else>
          Quarry source
          <input
            v-model="quarry"
            placeholder="Query URL, run URL, query ID, query:ID, or run:ID"
          />
        </label>
      </div>

      <div class="cfc-panel">
        <label v-if="mode === 'replace'">
          Find
          <textarea v-model="find" rows="5" />
        </label>
        <label v-if="mode === 'replace'">
          Replace with
          <textarea v-model="replace" rows="5" />
        </label>
        <label v-if="mode === 'prepend'">
          Prepend text
          <textarea v-model="prepend" rows="10" />
        </label>
        <label v-if="mode === 'append'">
          Append text
          <textarea v-model="append" rows="10" />
        </label>
        <label>
          Edit summary
          <input v-model="editSummary" placeholder="Optional custom summary" />
        </label>
      </div>
    </section>

    <section class="cfc-actions">
      <button :disabled="busy" @click="run(false)">Preview dry run</button>
      <button class="primary" :disabled="busy || !canApply" @click="run(true)">Apply changes</button>
    </section>

    <p v-if="error" class="cfc-error">{{ error }}</p>
    <p v-if="runId" class="cfc-run-status">Run #{{ runId }}: {{ runStatus }}</p>

    <section v-if="result" class="cfc-results">
      <div class="cfc-summary">
        <span>{{ result.target_count }} targets</span>
        <span>{{ result.changed_count }} changed</span>
        <span>{{ result.saved_count }} saved</span>
        <span>{{ result.error_count }} errors</span>
        <span v-if="result.dry_run">dry run</span>
      </div>

      <article v-for="item in result.items" :key="item.title" class="cfc-item">
        <header>
          <strong>{{ item.title }}</strong>
          <span>{{ item.status }}</span>
        </header>
        <p v-if="item.error" class="cfc-error">{{ item.error }}</p>
        <pre v-if="item.diff">{{ item.diff }}</pre>
      </article>
    </section>
  </main>
</template>
