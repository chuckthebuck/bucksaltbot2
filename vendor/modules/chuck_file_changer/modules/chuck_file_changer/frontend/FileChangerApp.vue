<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

// These result interfaces mirror the durable job API. The browser renders
// plans and progress but never receives a Pywikibot object or write primitive.
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
  run_ids?: number[];
  chunks?: number;
  status: string;
  error?: string | null;
  result?: RunResult | null;
}

// Framework-injected props provide page-shell capabilities such as manage.
// Missing props are valid during standalone frontend development.
const props = JSON.parse(
  document.getElementById("chuck-file-changer-props")?.textContent || "{}"
);

type SourceMode = "manual" | "quarry" | "user" | "category" | "page" | "search";

// Form state retains independent values for every source/operation mode. Only
// the fields selected by ``sourceMode`` and ``mode`` are serialized per run.
const sourceMode = ref<SourceMode>("manual");
const targetsText = ref("");
const quarry = ref("");
const sourceTarget = ref("");
const sourceLimit = ref(5000);
const sourceSort = ref("newest");
const mode = ref<Mode>("replace");
const find = ref("");
const replace = ref("");
const prepend = ref("");
const append = ref("");
const editSummary = ref("");
const useRegex = ref(false);
const result = ref<RunResult | null>(null);
const runStatus = ref("");
const runId = ref<number | null>(null);
const runIds = ref<number[]>([]);
const error = ref("");
const busy = ref(false);
const canApplyRight = ref(false);

const canApply = computed(() =>
  // This controls the button only. Shell ``can_manage`` includes framework
  // maintainers, while the custom API checks configured module rights directly;
  // /api/auth and the apply response remain authoritative and may return 403.
  Boolean(canApplyRight.value || props?.can_manage)
);
const sourceCount = computed(() =>
  sourceMode.value === "manual"
    ? targetsText.value.split(/\r?\n/).filter((line) => line.trim()).length
    : 0
);
const sourceTargetLabel = computed(() => {
  if (sourceMode.value === "user") return "Uploader";
  if (sourceMode.value === "category") return "Category";
  if (sourceMode.value === "page") return "Page or gallery";
  if (sourceMode.value === "search") return "Search query";
  return "Source";
});
const sourceTargetPlaceholder = computed(() => {
  if (sourceMode.value === "user") return "ExampleUser";
  if (sourceMode.value === "category") return "Category:Files uploaded by ExampleUser";
  if (sourceMode.value === "page") return "Commons:Example gallery";
  if (sourceMode.value === "search") return 'insource:"{{Species gallery}}"';
  return "";
});
const operationLabel = computed(() => {
  if (mode.value === "replace") return useRegex.value ? "Regex replace" : "Find/replace";
  if (mode.value === "prepend") return "Prepend text";
  return "Append text";
});

onMounted(async () => {
  // Fetch current rights instead of trusting potentially stale shell props.
  // Failure degrades to preview-only UI and never enables a write affordance.
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
  // Send one canonical payload for both endpoints. Inactive source fields are
  // blanked so stale form values cannot compete in server-side precedence.
  return {
    source_text: sourceMode.value === "manual" ? targetsText.value : "",
    quarry: sourceMode.value === "quarry" ? quarry.value : "",
    source_mode: ["user", "category", "page", "search"].includes(sourceMode.value)
      ? sourceMode.value
      : "",
    source_target: sourceTarget.value,
    source_limit: sourceLimit.value,
    source_sort: sourceSort.value,
    mode: mode.value,
    find: find.value,
    replace: replace.value,
    prepend: prepend.value,
    append: append.value,
    edit_summary: editSummary.value,
    use_regex: useRegex.value,
    dry_run: !apply,
    apply,
  };
}

async function run(apply: boolean) {
  // A new request invalidates the displayed result and all prior chunk state.
  // Preview and apply are independent submissions; server authorization and
  // dry-run flags—not prior client state—determine whether writes are possible.
  busy.value = true;
  error.value = "";
  result.value = null;
  runStatus.value = "";
  runId.value = null;
  runIds.value = [];

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
    // The queue returns compatibility singular IDs plus the complete chunk ID
    // list. Poll every finite ID and use the first only for compact status text.
    runIds.value = Array.isArray(data?.run_ids)
      ? data.run_ids.map((id: unknown) => Number(id)).filter((id: number) => Number.isFinite(id))
      : [Number(data?.run_id)].filter((id: number) => Number.isFinite(id));
    runId.value = runIds.value[0] || null;
    runStatus.value = String(data?.status || "queued");
    await pollRuns(runIds.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "Request failed";
  } finally {
    busy.value = false;
  }
}

function mergeResults(results: RunResult[]): RunResult {
  // Chunk ordering follows the original queue ID order. Counts are additive;
  // dry-run remains true only when every chunk reports itself as dry.
  return {
    dry_run: results.every((item) => item.dry_run),
    target_count: results.reduce((sum, item) => sum + Number(item.target_count || 0), 0),
    planned_count: results.reduce((sum, item) => sum + Number(item.planned_count || 0), 0),
    changed_count: results.reduce((sum, item) => sum + Number(item.changed_count || 0), 0),
    saved_count: results.reduce((sum, item) => sum + Number(item.saved_count || 0), 0),
    error_count: results.reduce((sum, item) => sum + Number(item.error_count || 0), 0),
    source_url: results.find((item) => item.source_url)?.source_url || null,
    items: results.flatMap((item) => item.items || []),
  };
}

async function pollRuns(ids: number[]) {
  // Completed chunks are memoized so later polling rounds query only work that
  // is still active. Any failed/canceled chunk fails the aggregate UI result.
  const completed = new Map<number, RunResult>();
  for (let attempt = 0; attempt < 240; attempt += 1) {
    for (const id of ids) {
      if (completed.has(id)) continue;
      const data = await fetchRun(id);
      if (data.status === "completed" && data.result) {
        completed.set(id, data.result);
        continue;
      }
      if (data.status === "failed" || data.status === "canceled") {
        throw new Error(data.error || `Run ${id} ${data.status}`);
      }
    }

    runStatus.value = `${completed.size}/${ids.length} completed`;
    if (completed.size === ids.length) {
      result.value = mergeResults(ids.map((id) => completed.get(id)!));
      runStatus.value = "completed";
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("Run is still pending after 240 seconds");
}

async function fetchRun(id: number): Promise<QueuedRun> {
  // Job state changes rapidly and is ownership-protected server-side; bypass
  // HTTP caches on every poll.
  const response = await fetch(`/chuck_file_changer/api/jobs/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  const data = (await response.json()) as QueuedRun;
  if (!response.ok) {
    throw new Error((data as any)?.detail || `HTTP ${response.status}`);
  }
  return data;
}

</script>

<template>
  <main class="cfc">
    <!-- The status pill is an affordance, not authorization. Apply is always
         rechecked by the authenticated server route. -->
    <section class="cfc-header">
      <div>
        <h1>File Changer</h1>
        <p>{{ operationLabel }} · Commons file pages · queued module run</p>
      </div>
      <div class="cfc-status-pill" :class="{ live: canApply }">
        {{ canApply ? "Live apply enabled" : "Preview only" }}
      </div>
    </section>

    <section class="cfc-grid">
      <!-- Source and action choices are kept separate so the same normalized
           target batch can be previewed with any supported text operation. -->
      <div class="cfc-panel">
        <header>
          <h2>Source</h2>
          <span v-if="sourceMode === 'manual'">{{ sourceCount }} rows</span>
        </header>
        <div class="cfc-segmented" role="group" aria-label="Source">
          <button :class="{ active: sourceMode === 'manual' }" @click="sourceMode = 'manual'">Manual list</button>
          <button :class="{ active: sourceMode === 'quarry' }" @click="sourceMode = 'quarry'">Quarry</button>
          <button :class="{ active: sourceMode === 'user' }" @click="sourceMode = 'user'">Uploader</button>
          <button :class="{ active: sourceMode === 'category' }" @click="sourceMode = 'category'">Category</button>
          <button :class="{ active: sourceMode === 'page' }" @click="sourceMode = 'page'">Page</button>
          <button :class="{ active: sourceMode === 'search' }" @click="sourceMode = 'search'">Search</button>
        </div>

        <label v-if="sourceMode === 'manual'">
          Targets
          <textarea
            v-model="targetsText"
            rows="14"
            placeholder="File:Example.jpg&#10;Example2.jpg|Uploader|Optional note"
          />
        </label>

        <label v-else-if="sourceMode === 'quarry'">
          Quarry source
          <input
            v-model="quarry"
            placeholder="Query URL, run URL, query ID, query:ID, or run:ID"
          />
        </label>

        <div v-else class="cfc-source-form">
          <label>
            {{ sourceTargetLabel }}
            <input
              v-model="sourceTarget"
              :placeholder="sourceTargetPlaceholder"
            />
          </label>
          <div class="cfc-source-options">
            <label>
              Limit
              <input v-model.number="sourceLimit" type="number" min="1" max="50000" step="100" />
            </label>
            <label>
              Sort
              <select v-model="sourceSort" aria-label="Source sort">
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="name_asc">Name A-Z</option>
                <option value="name_desc">Name Z-A</option>
              </select>
            </label>
          </div>
        </div>
      </div>

      <div class="cfc-panel">
        <header>
          <h2>Action</h2>
          <span>{{ operationLabel }}</span>
        </header>

        <label>
          Operation
          <select v-model="mode" aria-label="Operation">
            <option value="replace">Find/replace</option>
            <option value="prepend">Prepend text</option>
            <option value="append">Append text</option>
          </select>
        </label>

        <label v-if="mode === 'replace'">
          Find
          <textarea v-model="find" rows="5" />
        </label>
        <label v-if="mode === 'replace'" class="cfc-check">
          <input v-model="useRegex" type="checkbox" />
          <span>Regular expression</span>
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
          <input v-model="editSummary" placeholder="Optional custom summary; supports %FULLPAGENAME%, %FULLPAGENAMEE%, %PAGENAME%, %SUMMARY_HINT%" />
        </label>
      </div>
    </section>

    <section class="cfc-queue">
      <div>
        <h2>Queue</h2>
        <p v-if="runIds.length > 1">{{ runIds.length }} chunks · {{ runStatus }}</p>
        <p v-else-if="runId">Run #{{ runId }} · {{ runStatus }}</p>
        <p v-else>Ready</p>
      </div>
      <div class="cfc-actions">
        <!-- Preview and apply submit fresh payloads; the UI does not execute or
             replay wikitext mutations locally. -->
        <button :disabled="busy" @click="run(false)">Preview</button>
        <button class="primary" :disabled="busy || !canApply" @click="run(true)">Apply</button>
      </div>
    </section>

    <p v-if="error" class="cfc-error">{{ error }}</p>

    <section v-if="result" class="cfc-results">
      <!-- Diffs are rendered as text in <pre>; no returned wikitext is injected
           as HTML into the module page. -->
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
