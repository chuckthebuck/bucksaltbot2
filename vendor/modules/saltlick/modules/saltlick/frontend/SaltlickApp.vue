<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

type TransformType =
  | "literal_replace"
  | "regex_replace"
  | "prepend"
  | "append"
  | "set_text"
  | "template"
  | "expression";

interface Transform {
  type: TransformType;
  find?: string;
  replace?: string;
  text?: string;
  pattern?: string;
  flags?: string;
  count?: number;
  expression?: string;
}

interface Workflow {
  version: number;
  name: string;
  wiki: { code: string; family: string };
  source: {
    type: string;
    titles: string[];
    target: string;
    limit: number;
    namespaces: number[];
    recursive: number;
    only_template_inclusion: boolean;
  };
  filters: {
    title_regex: string;
    contains: string;
    not_contains: string;
    skip_redirects: boolean;
    skip_missing: boolean;
  };
  transforms: Transform[];
  save: {
    summary: string;
    minor: boolean;
    bot: boolean;
    watch: string;
    throttle_seconds: number;
  };
  limits: {
    max_edits: number;
    stop_on_error: boolean;
    max_page_bytes: number;
  };
  metadata: Record<string, unknown>;
}

interface AuthState {
  username?: string;
  can_preview?: boolean;
  can_apply?: boolean;
  can_manage?: boolean;
}

interface RunItem {
  title: string;
  status: string;
  reason?: string;
  error?: string;
  diff?: string;
}

interface RunResult {
  ok: boolean;
  dry_run: boolean;
  scanned_count: number;
  changed_count: number;
  saved_count: number;
  skipped_count: number;
  error_count: number;
  items: RunItem[];
  generated_jobs_py?: string;
}

const DRAFT_KEY = "saltlick:workflow:v1";
const sourceOptions = [
  ["titles", "Page titles"],
  ["category", "Category members"],
  ["backlinks", "Backlinks"],
  ["links", "Links from a page"],
  ["search", "Wiki search"],
  ["user_contribs", "User contributions"],
  ["recent_changes", "Recent changes"],
  ["prefix", "Title prefix"],
] as const;
const transformOptions: Array<[TransformType, string]> = [
  ["literal_replace", "Find and replace"],
  ["regex_replace", "Regular expression"],
  ["prepend", "Prepend text"],
  ["append", "Append text"],
  ["template", "Template the whole page"],
  ["expression", "Expression (advanced)"],
  ["set_text", "Replace the whole page"],
];

function defaultWorkflow(): Workflow {
  return {
    version: 1,
    name: "My first Saltlick bot",
    wiki: { code: "commons", family: "commons" },
    source: {
      type: "titles",
      titles: ["User:Example/Sandbox"],
      target: "",
      limit: 10,
      namespaces: [],
      recursive: 0,
      only_template_inclusion: false,
    },
    filters: {
      title_regex: "",
      contains: "",
      not_contains: "",
      skip_redirects: true,
      skip_missing: true,
    },
    transforms: [
      {
        type: "literal_replace",
        find: "old text",
        replace: "new text",
        count: 0,
      },
    ],
    save: {
      summary: "Updating {{pagename}} with Saltlick",
      minor: false,
      bot: true,
      watch: "nochange",
      throttle_seconds: 0,
    },
    limits: {
      max_edits: 10,
      stop_on_error: false,
      max_page_bytes: 2_000_000,
    },
    metadata: {},
  };
}

const workflow = ref<Workflow>(defaultWorkflow());
const titlesText = ref(workflow.value.source.titles.join("\n"));
const namespacesText = ref("");
const auth = ref<AuthState>({});
const loadingAuth = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const runId = ref<number | null>(null);
const runStatus = ref("");
const result = ref<RunResult | null>(null);
const liveConfirmed = ref(false);
const exportTab = ref<"jobs" | "manifest" | "recipe">("jobs");
const generatedJobs = ref("");
const generatedManifest = ref("");
const validatedRecipe = ref("");
const showAdvanced = ref(false);

const sourceTargetLabel = computed(() => {
  const labels: Record<string, string> = {
    category: "Category",
    backlinks: "Page receiving links",
    links: "Page containing links",
    search: "Search query",
    user_contribs: "Username",
    prefix: "Title prefix",
  };
  return labels[workflow.value.source.type] || "Target";
});

const sourceTargetPlaceholder = computed(() => {
  const placeholders: Record<string, string> = {
    category: "Category:Files needing review",
    backlinks: "Template:Example",
    links: "Commons:Example gallery",
    search: 'insource:"old template"',
    user_contribs: "ExampleUser",
    prefix: "Draft:",
  };
  return placeholders[workflow.value.source.type] || "";
});

const exportText = computed(() => {
  if (exportTab.value === "manifest") return generatedManifest.value;
  if (exportTab.value === "recipe") return validatedRecipe.value;
  return generatedJobs.value;
});

const sourceDescription = computed(() => {
  const label = sourceOptions.find(([value]) => value === workflow.value.source.type)?.[1];
  return `${label || "Pages"} · up to ${workflow.value.source.limit}`;
});

function normalizeDraft(): Workflow {
  const draft = JSON.parse(JSON.stringify(workflow.value)) as Workflow;
  draft.source.titles = titlesText.value
    .split(/\r?\n/)
    .map((title) => title.trim())
    .filter(Boolean);
  draft.source.namespaces = namespacesText.value
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value));
  return draft;
}

function restoreDraft() {
  try {
    const stored = window.localStorage.getItem(DRAFT_KEY);
    if (!stored) return;
    const parsed = JSON.parse(stored) as Workflow;
    workflow.value = { ...defaultWorkflow(), ...parsed };
    titlesText.value = (parsed.source?.titles || []).join("\n");
    namespacesText.value = (parsed.source?.namespaces || []).join(", ");
  } catch {
    window.localStorage.removeItem(DRAFT_KEY);
  }
}

watch(
  workflow,
  () => {
    try {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify(normalizeDraft()));
    } catch {
      // A private browser session may not expose localStorage.
    }
  },
  { deep: true },
);
watch([titlesText, namespacesText], () => {
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(normalizeDraft()));
  } catch {
    // Keep the wizard usable when storage is unavailable.
  }
});

onMounted(async () => {
  restoreDraft();
  try {
    const response = await fetch("/api/v1/modules/saltlick/auth", { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
    auth.value = body;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Could not load Saltlick access";
  } finally {
    loadingAuth.value = false;
  }
});

function addTransform() {
  workflow.value.transforms.push({
    type: "literal_replace",
    find: "",
    replace: "",
    count: 0,
  });
}

function removeTransform(index: number) {
  if (workflow.value.transforms.length > 1) {
    workflow.value.transforms.splice(index, 1);
  }
}

function moveTransform(index: number, direction: -1 | 1) {
  const next = index + direction;
  if (next < 0 || next >= workflow.value.transforms.length) return;
  const [item] = workflow.value.transforms.splice(index, 1);
  workflow.value.transforms.splice(next, 0, item);
}

async function api(path: string, payload: Record<string, unknown>) {
  const response = await fetch(`/api/v1/modules/saltlick/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
  return body;
}

async function validateWorkflow(quiet = false) {
  const body = await api("validate", { recipe: normalizeDraft() });
  generatedJobs.value = String(body.jobs_py || "");
  generatedManifest.value = String(body.module_toml || "");
  validatedRecipe.value = JSON.stringify(body.recipe || {}, null, 2);
  if (!quiet) notice.value = "Recipe validated. The fork-ready files are up to date.";
  return body;
}

async function startRun(live: boolean) {
  error.value = "";
  notice.value = "";
  result.value = null;
  runId.value = null;
  if (live && !liveConfirmed.value) {
    error.value = "Check the live-edit confirmation before applying.";
    return;
  }
  busy.value = true;
  try {
    await validateWorkflow(true);
    const body = await api(live ? "apply" : "preview", {
      recipe: normalizeDraft(),
      confirm_live: live,
    });
    runId.value = Number(body.run_id);
    runStatus.value = "queued";
    notice.value = live ? "Live run queued." : "Dry run queued.";
    await pollRun(runId.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Saltlick request failed";
  } finally {
    busy.value = false;
  }
}

async function pollRun(id: number) {
  for (let attempt = 0; attempt < 360; attempt += 1) {
    const response = await fetch(`/api/v1/modules/saltlick/runs/${id}`, {
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
    runStatus.value = String(body.status || "unknown");
    if (body.status === "completed") {
      result.value = body.result as RunResult;
      if (result.value?.generated_jobs_py) {
        generatedJobs.value = result.value.generated_jobs_py;
      }
      notice.value = result.value?.dry_run
        ? "Dry run complete. Review every proposed diff below."
        : "Live run complete.";
      return;
    }
    if (body.status === "failed" || body.status === "canceled") {
      throw new Error(body.error || `Run ${body.status}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("Run is still pending after six minutes.");
}

function downloadRecipe() {
  const recipe = JSON.stringify(normalizeDraft(), null, 2);
  const blob = new Blob([recipe], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "saltlick-recipe.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function copyExport() {
  if (!exportText.value) await validateWorkflow(true);
  await navigator.clipboard.writeText(exportText.value);
  notice.value = "Copied to clipboard.";
}

function resetDraft() {
  workflow.value = defaultWorkflow();
  titlesText.value = workflow.value.source.titles.join("\n");
  namespacesText.value = "";
  result.value = null;
  generatedJobs.value = "";
  generatedManifest.value = "";
  validatedRecipe.value = "";
  window.localStorage.removeItem(DRAFT_KEY);
  notice.value = "Started a fresh recipe.";
}
</script>

<template>
  <main class="saltlick">
    <header class="sl-hero">
      <div>
        <p class="sl-kicker">Chuckbot's Pywikibot workshop</p>
        <h1>Saltlick</h1>
        <p class="sl-lede">
          Choose pages, chain changes, inspect real diffs, then run or fork the result.
        </p>
      </div>
      <div class="sl-timebox" aria-label="Two hour path">
        <strong>&lt; 2 hours</strong>
        <span>idea to working bot</span>
      </div>
    </header>

    <ol class="sl-route" aria-label="Workflow">
      <li><span>1</span><strong>Pages</strong><small>{{ sourceDescription }}</small></li>
      <li><span>2</span><strong>Changes</strong><small>{{ workflow.transforms.length }} step(s)</small></li>
      <li><span>3</span><strong>Dry run</strong><small>bounded diffs</small></li>
      <li><span>4</span><strong>Run or fork</strong><small>your code, your bot</small></li>
    </ol>

    <p v-if="error" class="sl-message sl-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="sl-message sl-notice">{{ notice }}</p>

    <section class="sl-workbench">
      <div class="sl-builder">
        <section class="sl-card">
          <header>
            <div>
              <span class="sl-step">01</span>
              <h2>Name the bot and wiki</h2>
            </div>
            <button class="sl-link-button" type="button" @click="resetDraft">Start over</button>
          </header>
          <div class="sl-field-grid sl-field-grid-wide">
            <label>
              Bot name
              <input v-model="workflow.name" maxlength="80" />
            </label>
            <label>
              Wiki code
              <input v-model="workflow.wiki.code" placeholder="commons" />
            </label>
            <label>
              Family
              <input v-model="workflow.wiki.family" placeholder="commons" />
            </label>
          </div>
        </section>

        <section class="sl-card">
          <header>
            <div>
              <span class="sl-step">02</span>
              <h2>Choose the pages</h2>
            </div>
            <span class="sl-chip">Pywikibot generators</span>
          </header>
          <div class="sl-field-grid">
            <label>
              Source
              <select v-model="workflow.source.type">
                <option v-for="[value, label] in sourceOptions" :key="value" :value="value">
                  {{ label }}
                </option>
              </select>
            </label>
            <label>
              Page limit
              <input v-model.number="workflow.source.limit" type="number" min="1" max="500" />
            </label>
          </div>
          <label v-if="workflow.source.type === 'titles'">
            One title per line
            <textarea
              v-model="titlesText"
              rows="6"
              placeholder="User:Example/Sandbox"
            />
          </label>
          <label v-else-if="workflow.source.type !== 'recent_changes'">
            {{ sourceTargetLabel }}
            <input v-model="workflow.source.target" :placeholder="sourceTargetPlaceholder" />
          </label>
          <div class="sl-field-grid">
            <label>
              Namespaces <small>comma-separated IDs; blank means any</small>
              <input v-model="namespacesText" placeholder="0, 6, 10" />
            </label>
            <label v-if="workflow.source.type === 'category'">
              Category depth
              <input v-model.number="workflow.source.recursive" type="number" min="0" max="5" />
            </label>
            <label v-if="workflow.source.type === 'backlinks'" class="sl-check">
              <input v-model="workflow.source.only_template_inclusion" type="checkbox" />
              Template transclusions only
            </label>
          </div>
        </section>

        <section class="sl-card">
          <header>
            <div>
              <span class="sl-step">03</span>
              <h2>Chain the changes</h2>
            </div>
            <button class="sl-button sl-button-soft" type="button" @click="addTransform">
              Add step
            </button>
          </header>
          <div class="sl-transforms">
            <article
              v-for="(transform, index) in workflow.transforms"
              :key="index"
              class="sl-transform"
            >
              <div class="sl-transform-head">
                <strong>{{ index + 1 }}</strong>
                <select v-model="transform.type" :aria-label="`Transform ${index + 1}`">
                  <option v-for="[value, label] in transformOptions" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select>
                <div class="sl-order">
                  <button type="button" :disabled="index === 0" @click="moveTransform(index, -1)">↑</button>
                  <button
                    type="button"
                    :disabled="index === workflow.transforms.length - 1"
                    @click="moveTransform(index, 1)"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    :disabled="workflow.transforms.length === 1"
                    @click="removeTransform(index)"
                  >
                    ×
                  </button>
                </div>
              </div>

              <div v-if="transform.type === 'literal_replace'" class="sl-field-grid">
                <label>Find <textarea v-model="transform.find" rows="3" /></label>
                <label>Replace <textarea v-model="transform.replace" rows="3" /></label>
              </div>
              <div v-else-if="transform.type === 'regex_replace'" class="sl-field-grid">
                <label>Pattern <textarea v-model="transform.pattern" rows="3" /></label>
                <label>Replacement <textarea v-model="transform.replace" rows="3" /></label>
                <label>Flags <input v-model="transform.flags" placeholder="imsx" /></label>
                <label>
                  Max replacements <small>0 means all</small>
                  <input v-model.number="transform.count" type="number" min="0" />
                </label>
              </div>
              <label
                v-else-if="
                  transform.type === 'prepend' ||
                  transform.type === 'append' ||
                  transform.type === 'set_text' ||
                  transform.type === 'template'
                "
              >
                Text
                <textarea
                  v-model="transform.text"
                  rows="5"
                  placeholder="Use {{text}}, {{title}}, or {{namespace}}"
                />
              </label>
              <label v-else>
                Restricted expression
                <textarea
                  v-model="transform.expression"
                  rows="4"
                  placeholder='regex(r"old", "new", text, flags="i") if contains(text, "old") else text'
                />
                <small>
                  Available: text, title, namespace, replace, regex, strip, lower, upper,
                  contains, starts_with, ends_with, length, slice.
                </small>
              </label>
            </article>
          </div>
        </section>

        <section class="sl-card">
          <button
            class="sl-advanced-toggle"
            type="button"
            :aria-expanded="showAdvanced"
            @click="showAdvanced = !showAdvanced"
          >
            <span><span class="sl-step">04</span> Filters, edit settings, and limits</span>
            <strong>{{ showAdvanced ? "Hide" : "Show" }}</strong>
          </button>
          <div v-if="showAdvanced" class="sl-advanced">
            <h3>Only edit when…</h3>
            <div class="sl-field-grid">
              <label>Title regex <input v-model="workflow.filters.title_regex" /></label>
              <label>Text contains <input v-model="workflow.filters.contains" /></label>
              <label>Text does not contain <input v-model="workflow.filters.not_contains" /></label>
            </div>
            <div class="sl-check-row">
              <label class="sl-check">
                <input v-model="workflow.filters.skip_redirects" type="checkbox" />
                Skip redirects
              </label>
              <label class="sl-check">
                <input v-model="workflow.filters.skip_missing" type="checkbox" />
                Skip missing pages
              </label>
              <label class="sl-check">
                <input v-model="workflow.limits.stop_on_error" type="checkbox" />
                Stop on first error
              </label>
            </div>
            <h3>Save behavior</h3>
            <label>
              Edit summary
              <input
                v-model="workflow.save.summary"
                maxlength="500"
                placeholder="Supports {{title}} and {{pagename}}"
              />
            </label>
            <div class="sl-field-grid">
              <label>
                Maximum edits
                <input v-model.number="workflow.limits.max_edits" type="number" min="1" max="500" />
              </label>
              <label>
                Pause after saves (seconds)
                <input
                  v-model.number="workflow.save.throttle_seconds"
                  type="number"
                  min="0"
                  max="60"
                  step="0.5"
                />
              </label>
              <label>
                Watchlist
                <select v-model="workflow.save.watch">
                  <option value="nochange">Do not change</option>
                  <option value="preferences">Use preferences</option>
                  <option value="watch">Watch</option>
                  <option value="unwatch">Unwatch</option>
                </select>
              </label>
            </div>
            <div class="sl-check-row">
              <label class="sl-check">
                <input v-model="workflow.save.minor" type="checkbox" />
                Mark minor
              </label>
              <label class="sl-check">
                <input v-model="workflow.save.bot" type="checkbox" />
                Use bot flag
              </label>
            </div>
          </div>
        </section>
      </div>

      <aside class="sl-launch">
        <div class="sl-launch-sticky">
          <p class="sl-kicker">Launch pad</p>
          <h2>{{ workflow.name || "Untitled bot" }}</h2>
          <dl>
            <div><dt>Wiki</dt><dd>{{ workflow.wiki.code }}.{{ workflow.wiki.family }}</dd></div>
            <div><dt>Source</dt><dd>{{ sourceDescription }}</dd></div>
            <div><dt>Transforms</dt><dd>{{ workflow.transforms.length }}</dd></div>
            <div><dt>Live ceiling</dt><dd>{{ workflow.limits.max_edits }} edits</dd></div>
          </dl>

          <button
            class="sl-button sl-button-primary"
            type="button"
            :disabled="busy || loadingAuth || !auth.can_preview"
            @click="startRun(false)"
          >
            {{ busy && runStatus ? `Run ${runStatus}…` : "Run dry preview" }}
          </button>
          <p class="sl-safety">
            Preview reads live pages and records proposed saves. It never calls
            <code>page.save()</code>.
          </p>

          <label class="sl-live-confirm">
            <input v-model="liveConfirmed" type="checkbox" />
            I reviewed the dry run and intend to save these edits.
          </label>
          <button
            class="sl-button sl-button-live"
            type="button"
            :disabled="busy || !auth.can_apply || !liveConfirmed"
            @click="startRun(true)"
          >
            Run live
          </button>
          <small v-if="!auth.can_apply">
            Live execution needs the module's <code>apply_changes</code> right.
          </small>

          <hr />
          <button class="sl-button sl-button-soft" type="button" @click="validateWorkflow(false)">
            Validate and generate code
          </button>
          <button class="sl-link-button sl-download" type="button" @click="downloadRecipe">
            Download recipe.json
          </button>
        </div>
      </aside>
    </section>

    <section v-if="result" class="sl-results">
      <header>
        <div>
          <p class="sl-kicker">{{ result.dry_run ? "Dry-run report" : "Live report" }}</p>
          <h2>Run #{{ runId }} {{ result.ok ? "completed" : "completed with errors" }}</h2>
        </div>
        <a v-if="runId" :href="`/modules/runs/${runId}/report`">Open framework report</a>
      </header>
      <div class="sl-metrics">
        <div><strong>{{ result.scanned_count }}</strong><span>scanned</span></div>
        <div><strong>{{ result.changed_count }}</strong><span>changed</span></div>
        <div><strong>{{ result.saved_count }}</strong><span>saved</span></div>
        <div><strong>{{ result.skipped_count }}</strong><span>skipped</span></div>
        <div><strong>{{ result.error_count }}</strong><span>errors</span></div>
      </div>
      <div class="sl-result-list">
        <details v-for="(item, index) in result.items" :key="`${item.title}-${index}`">
          <summary>
            <span :class="`sl-status sl-status-${item.status}`">{{ item.status }}</span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.reason || item.error || "" }}</small>
          </summary>
          <pre v-if="item.diff">{{ item.diff }}</pre>
          <p v-if="item.error" class="sl-error-text">{{ item.error }}</p>
        </details>
      </div>
    </section>

    <section v-if="generatedJobs || generatedManifest || validatedRecipe" class="sl-export">
      <header>
        <div>
          <p class="sl-kicker">Fork boundary</p>
          <h2>Take the bot with you</h2>
          <p>These files turn the recipe into reviewed source in a Saltlick fork.</p>
        </div>
        <button class="sl-button sl-button-soft" type="button" @click="copyExport">
          Copy current file
        </button>
      </header>
      <nav aria-label="Generated files">
        <button :class="{ active: exportTab === 'jobs' }" @click="exportTab = 'jobs'">jobs.py</button>
        <button :class="{ active: exportTab === 'manifest' }" @click="exportTab = 'manifest'">
          module.toml
        </button>
        <button :class="{ active: exportTab === 'recipe' }" @click="exportTab = 'recipe'">
          recipe.json
        </button>
      </nav>
      <pre>{{ exportText }}</pre>
    </section>
  </main>
</template>
