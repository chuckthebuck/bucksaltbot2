<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CdxButton, CdxProgressBar } from "@wikimedia/codex";
import {
  getInitialProps,
  emergencyStopModule,
  fetchModuleConfig,
  fetchModuleJobs,
  fetchModules,
  type ModuleRunItem,
  toggleModuleEnabled,
  updateModuleAccess,
  updateModuleConfig,
  updateModuleJob,
} from "./api";

interface Module {
  name: string;
  title: string;
  enabled: boolean;
  ui_enabled: boolean;
  has_access: boolean;
  can_manage?: boolean;
  can_estop?: boolean;
  redis_namespace: string;
  oauth_consumer_mode: string;
  cron_jobs: Array<{
    name: string;
    schedule: string;
    schedule_text?: string | null;
    endpoint: string;
    handler?: string | null;
    execution_mode?: string;
    concurrency_policy?: string;
    timeout_seconds: number;
    enabled: boolean;
  }>;
}

const props = getInitialProps();
const canManageModules = computed(
  () => props.can_manage_modules ?? props.is_maintainer
);

const modules = ref<Module[]>([]);
const loading = ref(true);
const error = ref("");
const selectedModule = ref<string | null>(null);
const togglingModule = ref<string | null>(null);
const estoppingModule = ref<string | null>(null);
const grantingAccess = ref<{ module: string; username: string } | null>(null);
const newAccessUsername = ref("");
const success = ref("");
const savingJob = ref<string | null>(null);
const moduleRuns = ref<ModuleRunItem[]>([]);
const jobDrafts = ref<
  Record<string, { scheduleText: string; timeoutSeconds: number; enabled: boolean }>
>({});
const moduleConfigText = ref("{}");
const moduleConfigDraft = ref<Record<string, unknown>>({});
const configLoadedFor = ref<string | null>(null);
const savingConfig = ref(false);
const selectedSitePreset = ref("custom");

const sitePresets = [
  {
    value: "testwiki",
    label: "Test Wikipedia",
    config: {
      wiki_code: "test",
      wiki_family: "wikipedia",
      wiki_api_url: "https://test.wikipedia.org/w/api.php",
      dry_run: true,
    },
  },
  {
    value: "enwiki",
    label: "English Wikipedia",
    config: {
      wiki_code: "en",
      wiki_family: "wikipedia",
      wiki_api_url: "https://en.wikipedia.org/w/api.php",
    },
  },
  {
    value: "custom",
    label: "Custom site",
    config: {},
  },
] as const;

async function loadModules() {
  try {
    loading.value = true;
    error.value = "";
    const data = await fetchModules();
    modules.value = data;
    syncJobDrafts();
  } catch (err) {
    error.value = `Failed to load modules: ${String(err)}`;
    console.error(err);
  } finally {
    loading.value = false;
  }
}

function syncJobDrafts() {
  const next: Record<
    string,
    { scheduleText: string; timeoutSeconds: number; enabled: boolean }
  > = {};
  for (const module of modules.value) {
    for (const job of module.cron_jobs) {
      next[`${module.name}/${job.name}`] = {
        scheduleText: job.schedule_text || job.schedule,
        timeoutSeconds: job.timeout_seconds,
        enabled: job.enabled,
      };
    }
  }
  jobDrafts.value = next;
}

async function toggleModule(moduleName: string, enabled: boolean) {
  try {
    togglingModule.value = moduleName;
    error.value = "";
    success.value = "";
    await toggleModuleEnabled(moduleName, enabled);
    success.value = enabled
      ? "Module enabled."
      : "Module disabled. Active work was not killed; use E-STOP for immediate shutdown.";
    await loadModules();
  } catch (err) {
    error.value = `Failed to toggle module: ${String(err)}`;
    console.error(err);
  } finally {
    togglingModule.value = null;
  }
}

async function estopModule(moduleName: string) {
  try {
    estoppingModule.value = moduleName;
    error.value = "";
    success.value = "";
    const result = await emergencyStopModule(moduleName);
    success.value = `Emergency stop sent. ${result.canceled_runs} active framework run(s) were canceled.`;
    await loadModules();
    await loadSelectedModuleRuns(moduleName);
  } catch (err) {
    error.value = `Failed to emergency-stop module: ${String(err)}`;
    console.error(err);
  } finally {
    estoppingModule.value = null;
  }
}

async function grantAccess(moduleName: string, username: string) {
  if (!username.trim()) {
    error.value = "Username is required";
    return;
  }

  try {
    grantingAccess.value = { module: moduleName, username };
    await updateModuleAccess(moduleName, username, true);
    newAccessUsername.value = "";
    await loadModules();
  } catch (err) {
    error.value = `Failed to grant access: ${String(err)}`;
    console.error(err);
  } finally {
    grantingAccess.value = null;
  }
}

async function revokeAccess(moduleName: string, username: string) {
  try {
    grantingAccess.value = { module: moduleName, username };
    await updateModuleAccess(moduleName, username, false);
    await loadModules();
  } catch (err) {
    error.value = `Failed to revoke access: ${String(err)}`;
    console.error(err);
  } finally {
    grantingAccess.value = null;
  }
}

async function saveJob(moduleName: string, jobName: string) {
  const key = `${moduleName}/${jobName}`;
  const draft = jobDrafts.value[key];
  if (!draft) {
    return;
  }

  try {
    savingJob.value = key;
    error.value = "";
    success.value = "";
    await updateModuleJob(moduleName, jobName, {
      schedule_text: draft.scheduleText,
      timeout_seconds: draft.timeoutSeconds,
      enabled: draft.enabled,
    });
    success.value =
      "Schedule saved. Regenerate Jobs YAML and reload Toolforge jobs for the new interval.";
    await loadModules();
  } catch (err) {
    error.value = `Failed to update job: ${String(err)}`;
    console.error(err);
  } finally {
    savingJob.value = null;
  }
}

async function loadSelectedModuleRuns(moduleName: string) {
  try {
    const data = await fetchModuleJobs(moduleName);
    moduleRuns.value = data.runs;
  } catch (err) {
    error.value = `Failed to load module runs: ${String(err)}`;
    console.error(err);
  }
}

async function loadSelectedModuleConfig(moduleName: string) {
  try {
    error.value = "";
    const config = await fetchModuleConfig(moduleName);
    moduleConfigDraft.value = {
      ...defaultModuleConfig(moduleName),
      ...config,
    };
    selectedSitePreset.value = detectSitePreset(moduleConfigDraft.value);
    syncModuleConfigText();
    configLoadedFor.value = moduleName;
  } catch (err) {
    error.value = `Failed to load module config: ${String(err)}`;
    console.error(err);
  }
}

async function saveSelectedModuleConfig(moduleName: string) {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(moduleConfigText.value || "{}");
  } catch {
    error.value = "Module config must be valid JSON.";
    return;
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    error.value = "Module config must be a JSON object.";
    return;
  }

  try {
    savingConfig.value = true;
    error.value = "";
    success.value = "";
    const config = await updateModuleConfig(moduleName, parsed);
    moduleConfigDraft.value = {
      ...defaultModuleConfig(moduleName),
      ...config,
    };
    selectedSitePreset.value = detectSitePreset(moduleConfigDraft.value);
    syncModuleConfigText();
    success.value = "Module config saved.";
  } catch (err) {
    error.value = `Failed to save module config: ${String(err)}`;
    console.error(err);
  } finally {
    savingConfig.value = false;
  }
}

const selectedModuleData = computed(() => {
  return modules.value.find((m) => m.name === selectedModule.value) || null;
});

const canManageSelectedModule = computed(
  () => canManageModules.value || !!selectedModuleData.value?.can_manage
);

const canEstopSelectedModule = computed(
  () => canManageSelectedModule.value || !!selectedModuleData.value?.can_estop
);

const isFourAwardModule = computed(
  () => selectedModuleData.value?.name === "four_award"
);

function selectModule(moduleName: string) {
  selectedModule.value = moduleName;
  if (canManageModules.value) {
    loadSelectedModuleConfig(moduleName);
    loadSelectedModuleRuns(moduleName);
  }
}

function defaultModuleConfig(moduleName: string): Record<string, unknown> {
  if (moduleName !== "four_award") {
    return {};
  }

  return {
    wiki_code: "en",
    wiki_family: "wikipedia",
    wiki_api_url: "https://en.wikipedia.org/w/api.php",
    dry_run: true,
    enabled: true,
    max_nominations_per_run: 25,
    four_page: "Wikipedia:Four Award",
    records_page: "Wikipedia:Four Award/Records",
    leaderboard_page: "Wikipedia:Four Award/Leaderboard",
    dry_run_report_page: "User:Chuckbot/4awardhelper dry-run report",
    publish_dry_run_report: false,
    enable_replies: true,
    enable_records: true,
    enable_removal: true,
    enable_talk_notices: true,
    enable_article_history: true,
    allow_automated_approval: false,
  };
}

function syncModuleConfigText() {
  moduleConfigText.value = JSON.stringify(moduleConfigDraft.value, null, 2);
}

function detectSitePreset(config: Record<string, unknown>): string {
  const wikiCode = String(config.wiki_code ?? "");
  const wikiFamily = String(config.wiki_family ?? "");
  const apiUrl = String(config.wiki_api_url ?? "");
  if (
    wikiCode === "test" &&
    wikiFamily === "wikipedia" &&
    apiUrl === "https://test.wikipedia.org/w/api.php"
  ) {
    return "testwiki";
  }
  if (
    wikiCode === "en" &&
    wikiFamily === "wikipedia" &&
    apiUrl === "https://en.wikipedia.org/w/api.php"
  ) {
    return "enwiki";
  }
  return "custom";
}

function applySitePreset(presetValue: string) {
  selectedSitePreset.value = presetValue;
  const preset = sitePresets.find((item) => item.value === presetValue);
  if (!preset || preset.value === "custom") {
    return;
  }

  moduleConfigDraft.value = {
    ...moduleConfigDraft.value,
    ...preset.config,
  };
  syncModuleConfigText();
}

function setConfigValue(key: string, value: unknown) {
  moduleConfigDraft.value = {
    ...moduleConfigDraft.value,
    [key]: value,
  };
  selectedSitePreset.value = detectSitePreset(moduleConfigDraft.value);
  syncModuleConfigText();
}

function getStringConfig(key: string): string {
  return String(moduleConfigDraft.value[key] ?? "");
}

function getBooleanConfig(key: string, fallback = false): boolean {
  const value = moduleConfigDraft.value[key];
  return typeof value === "boolean" ? value : fallback;
}

function getNumberConfig(key: string, fallback: number): number {
  const value = Number(moduleConfigDraft.value[key] ?? fallback);
  return Number.isFinite(value) ? value : fallback;
}

function readInputValue(event: Event): string {
  const target = event.target as HTMLInputElement | HTMLSelectElement | null;
  return target?.value ?? "";
}

function readCheckboxValue(event: Event): boolean {
  const target = event.target as HTMLInputElement | null;
  return Boolean(target?.checked);
}

function readNumberValue(event: Event, fallback: number): number {
  const value = Number(readInputValue(event));
  return Number.isFinite(value) ? value : fallback;
}

function dryRunEditCount(run: ModuleRunItem): number {
  return run.result?.dry_run_edits?.length ?? 0;
}

function dryRunReportTitle(run: ModuleRunItem): string {
  return run.result?.dry_run_report?.published?.title || "";
}

function wikiPageUrl(title: string): string {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replaceAll(" ", "_"))}`;
}

function moduleRunReportUrl(runId: number): string {
  return `/modules/runs/${runId}/report`;
}

onMounted(() => {
  loadModules();
});
</script>

<template>
  <div class="modules-app">
    <h1>Module Management</h1>

    <div v-if="!canManageModules" class="cdx-message cdx-message--warning">
      <div class="cdx-message__content">
        You are not a maintainer and cannot manage modules.
      </div>
    </div>

    <div v-if="success" class="cdx-message cdx-message--success">
      <div class="cdx-message__content">{{ success }}</div>
      <button class="cdx-message__close-button" @click="success = ''" type="button">
        x
      </button>
    </div>

    <div v-if="error" class="cdx-message cdx-message--error">
      <div class="cdx-message__content">{{ error }}</div>
      <button class="cdx-message__close-button" @click="error = ''" type="button">
        x
      </button>
    </div>

    <CdxProgressBar v-if="loading" :animated="true" />

    <div v-else class="modules-container">
      <section class="modules-list">
        <h2>Modules</h2>
        <div v-if="modules.length === 0" class="no-modules">
          <p>No modules currently registered.</p>
        </div>
        <div v-else class="module-items">
          <button
            v-for="module in modules"
            :key="module.name"
            class="module-item"
            :class="{ active: selectedModule === module.name }"
            @click="selectModule(module.name)"
          >
            <span class="module-name">{{ module.title || module.name }}</span>
            <span
              class="module-status"
              :class="{ enabled: module.enabled, disabled: !module.enabled }"
            >
              {{ module.enabled ? "Enabled" : "Disabled" }}
            </span>
          </button>
        </div>
      </section>

      <section v-if="selectedModuleData" class="module-detail">
        <div class="detail-header">
          <h2>{{ selectedModuleData.title || selectedModuleData.name }}</h2>
          <div
            v-if="canManageSelectedModule || canEstopSelectedModule"
            class="detail-actions"
          >
            <CdxButton
              v-if="canManageSelectedModule"
              :disabled="togglingModule === selectedModuleData.name"
              @click="
                toggleModule(
                  selectedModuleData.name,
                  !selectedModuleData.enabled
                )
              "
            >
              {{
                togglingModule === selectedModuleData.name
                  ? "Updating..."
                  : selectedModuleData.enabled
                    ? "Disable"
                    : "Enable"
              }}
            </CdxButton>
            <CdxButton
              v-if="canEstopSelectedModule"
              class="estop-action"
              action="destructive"
              weight="primary"
              :disabled="estoppingModule === selectedModuleData.name"
              @click="estopModule(selectedModuleData.name)"
            >
              {{
                estoppingModule === selectedModuleData.name
                  ? "Stopping..."
                  : "E-STOP"
              }}
            </CdxButton>
          </div>
        </div>

        <div class="detail-info">
          <div class="info-row">
            <span class="label">Name:</span>
            <span class="value">{{ selectedModuleData.name }}</span>
          </div>
          <div class="info-row">
            <span class="label">Status:</span>
            <span
              class="value status"
              :class="{ enabled: selectedModuleData.enabled }"
            >
              {{ selectedModuleData.enabled ? "Enabled" : "Disabled" }}
            </span>
          </div>
          <div class="info-row">
            <span class="label">UI Enabled:</span>
            <span class="value">
              {{ selectedModuleData.ui_enabled ? "Yes" : "No" }}
            </span>
          </div>
          <div class="info-row">
            <span class="label">Redis Namespace:</span>
            <span class="value">{{ selectedModuleData.redis_namespace }}</span>
          </div>
          <div class="info-row">
            <span class="label">OAuth Consumer Mode:</span>
            <span class="value">{{ selectedModuleData.oauth_consumer_mode }}</span>
          </div>
        </div>

        <div v-if="selectedModuleData.cron_jobs.length > 0" class="cron-jobs">
          <h3>Cron Jobs</h3>
          <p class="help-text">
            Changes here update the framework registry and generated Jobs YAML.
            Toolforge still needs the repo's jobs.yaml updated and reloaded before
            a new interval starts running.
          </p>
          <div class="cron-table-scroll">
            <table class="cron-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Schedule</th>
                  <th>Runner</th>
                  <th>Timeout</th>
                  <th>Status</th>
                  <th v-if="canManageModules">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in selectedModuleData.cron_jobs" :key="job.name">
                  <td>{{ job.name }}</td>
                  <td>
                    <input
                      v-if="canManageModules"
                      v-model="jobDrafts[`${selectedModuleData.name}/${job.name}`].scheduleText"
                      class="schedule-input"
                      type="text"
                      placeholder="daily at 03:00"
                    />
                    <code v-else>{{ job.schedule_text || job.schedule }}</code>
                    <div class="cron-expression">
                      Cron: <code>{{ job.schedule }}</code>
                    </div>
                  </td>
                  <td class="runner-cell">
                    <code>{{ job.handler || job.endpoint || job.execution_mode }}</code>
                  </td>
                  <td>
                    <input
                      v-if="canManageModules"
                      v-model.number="jobDrafts[`${selectedModuleData.name}/${job.name}`].timeoutSeconds"
                      class="timeout-input"
                      type="number"
                      min="1"
                    />
                    <span v-else>{{ job.timeout_seconds }}s</span>
                  </td>
                  <td>
                    <label v-if="canManageModules" class="enabled-toggle">
                      <input
                        v-model="jobDrafts[`${selectedModuleData.name}/${job.name}`].enabled"
                        type="checkbox"
                      />
                      Enabled
                    </label>
                    <span v-else :class="{ enabled: job.enabled }">
                      {{ job.enabled ? "Enabled" : "Disabled" }}
                    </span>
                  </td>
                  <td v-if="canManageModules">
                    <CdxButton
                      :disabled="savingJob === `${selectedModuleData.name}/${job.name}`"
                      @click="saveJob(selectedModuleData.name, job.name)"
                    >
                      {{
                        savingJob === `${selectedModuleData.name}/${job.name}`
                          ? "Saving..."
                          : "Save"
                      }}
                    </CdxButton>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <section v-if="canManageModules" class="module-config">
          <h3>Module Config</h3>
          <p class="help-text">
            Non-secret module settings. Use the structured fields for common
            options, then save the generated config.
          </p>

          <div v-if="isFourAwardModule" class="structured-config">
            <div class="config-grid">
              <label class="config-field">
                <span>Site preset</span>
                <select
                  :value="selectedSitePreset"
                  @change="applySitePreset(readInputValue($event))"
                >
                  <option
                    v-for="preset in sitePresets"
                    :key="preset.value"
                    :value="preset.value"
                  >
                    {{ preset.label }}
                  </option>
                </select>
              </label>

              <label class="config-field">
                <span>Wiki code</span>
                <input
                  :value="getStringConfig('wiki_code')"
                  placeholder="test"
                  type="text"
                  @input="setConfigValue('wiki_code', readInputValue($event))"
                />
              </label>

              <label class="config-field">
                <span>Wiki family</span>
                <input
                  :value="getStringConfig('wiki_family')"
                  placeholder="wikipedia"
                  type="text"
                  @input="setConfigValue('wiki_family', readInputValue($event))"
                />
              </label>

              <label class="config-field wide">
                <span>API URL</span>
                <input
                  :value="getStringConfig('wiki_api_url')"
                  placeholder="https://test.wikipedia.org/w/api.php"
                  type="url"
                  @input="setConfigValue('wiki_api_url', readInputValue($event))"
                />
              </label>

              <label class="config-field wide">
                <span>Four Award page</span>
                <input
                  :value="getStringConfig('four_page')"
                  placeholder="Wikipedia:Four Award"
                  type="text"
                  @input="setConfigValue('four_page', readInputValue($event))"
                />
              </label>

              <label class="config-field wide">
                <span>Records page</span>
                <input
                  :value="getStringConfig('records_page')"
                  placeholder="Wikipedia:Four Award/Records"
                  type="text"
                  @input="setConfigValue('records_page', readInputValue($event))"
                />
              </label>

              <label class="config-field wide">
                <span>Leaderboard page</span>
                <input
                  :value="getStringConfig('leaderboard_page')"
                  placeholder="Wikipedia:Four Award/Leaderboard"
                  type="text"
                  @input="setConfigValue('leaderboard_page', readInputValue($event))"
                />
              </label>

              <label class="config-field wide">
                <span>Dry-run report page</span>
                <input
                  :value="getStringConfig('dry_run_report_page')"
                  placeholder="User:Chuckbot/4awardhelper dry-run report"
                  type="text"
                  @input="
                    setConfigValue('dry_run_report_page', readInputValue($event))
                  "
                />
              </label>

              <label class="config-field">
                <span>Max nominations per run</span>
                <input
                  :value="getNumberConfig('max_nominations_per_run', 25)"
                  min="1"
                  type="number"
                  @input="
                    setConfigValue(
                      'max_nominations_per_run',
                      readNumberValue($event, 25)
                    )
                  "
                />
              </label>
            </div>

            <div class="config-toggles">
              <label>
                <input
                  :checked="getBooleanConfig('enabled', true)"
                  type="checkbox"
                  @change="setConfigValue('enabled', readCheckboxValue($event))"
                />
                Module run enabled
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('dry_run', true)"
                  type="checkbox"
                  @change="setConfigValue('dry_run', readCheckboxValue($event))"
                />
                Dry run
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('publish_dry_run_report', false)"
                  type="checkbox"
                  @change="
                    setConfigValue('publish_dry_run_report', readCheckboxValue($event))
                  "
                />
                Publish dry-run report to userspace
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('enable_replies', true)"
                  type="checkbox"
                  @change="setConfigValue('enable_replies', readCheckboxValue($event))"
                />
                Replies
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('enable_records', true)"
                  type="checkbox"
                  @change="setConfigValue('enable_records', readCheckboxValue($event))"
                />
                Records
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('enable_removal', true)"
                  type="checkbox"
                  @change="setConfigValue('enable_removal', readCheckboxValue($event))"
                />
                Removal cleanup
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('enable_talk_notices', true)"
                  type="checkbox"
                  @change="
                    setConfigValue('enable_talk_notices', readCheckboxValue($event))
                  "
                />
                Talk notices
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('enable_article_history', true)"
                  type="checkbox"
                  @change="
                    setConfigValue(
                      'enable_article_history',
                      readCheckboxValue($event)
                    )
                  "
                />
                Article history
              </label>
              <label>
                <input
                  :checked="getBooleanConfig('allow_automated_approval', false)"
                  type="checkbox"
                  @change="
                    setConfigValue(
                      'allow_automated_approval',
                      readCheckboxValue($event)
                    )
                  "
                />
                Automated approval
              </label>
            </div>
          </div>

          <details class="advanced-config" :open="!isFourAwardModule">
            <summary>Advanced JSON</summary>
            <textarea
              v-model="moduleConfigText"
              class="config-json"
              spellcheck="false"
              @focus="
                selectedModuleData && configLoadedFor !== selectedModuleData.name
                  ? loadSelectedModuleConfig(selectedModuleData.name)
                  : null
              "
            ></textarea>
          </details>

          <div class="detail-actions">
            <CdxButton
              :disabled="savingConfig"
              @click="saveSelectedModuleConfig(selectedModuleData.name)"
            >
              {{ savingConfig ? "Saving..." : "Save Config" }}
            </CdxButton>
          </div>
        </section>

        <section v-if="canManageModules" class="module-access">
          <h3>Access Control</h3>
          <p class="help-text">
            Maintainers have access to all modules by default. Grant additional users
            access below.
          </p>
          <div class="access-form">
            <input
              v-model="newAccessUsername"
              type="text"
              placeholder="Username"
              class="username-input"
              @keyup.enter="grantAccess(selectedModuleData!.name, newAccessUsername)"
            />
            <CdxButton
              :disabled="
                !newAccessUsername.trim() ||
                grantingAccess?.module === selectedModuleData.name
              "
              @click="grantAccess(selectedModuleData!.name, newAccessUsername)"
            >
              {{
                grantingAccess?.module === selectedModuleData.name
                  ? "Granting..."
                  : "Grant Access"
              }}
            </CdxButton>
          </div>
        </section>

        <section v-if="canManageModules" class="module-runs">
          <h3>Recent Runs</h3>
          <p class="help-text">
            Dry-run runs include the proposed edit count and, when configured, a
            Buckbot-hosted output report.
          </p>
          <div v-if="moduleRuns.length === 0" class="no-modules">
            <p>No runs recorded yet.</p>
          </div>
          <div v-else class="runs-table-scroll">
            <table class="runs-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Result</th>
                  <th>Output</th>
                  <th>Wiki Report</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in moduleRuns.slice(0, 10)" :key="run.id">
                  <td>#{{ run.id }}</td>
                  <td>{{ run.status }}</td>
                  <td>
                    {{ run.result?.approved ?? 0 }} approved,
                    {{ run.result?.failed ?? 0 }} failed,
                    {{ run.result?.manual ?? 0 }} manual,
                    {{ dryRunEditCount(run) }} proposed edits
                  </td>
                  <td>
                    <a :href="moduleRunReportUrl(run.id)">View output</a>
                  </td>
                  <td>
                    <a
                      v-if="dryRunReportTitle(run)"
                      :href="wikiPageUrl(dryRunReportTitle(run))"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {{ dryRunReportTitle(run) }}
                    </a>
                    <span v-else>Not published</span>
                  </td>
                  <td>{{ run.finished_at || run.created_at || "" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </div>
  </div>
</template>

<style scoped lang="less">
.modules-app {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

h1 {
  font-size: 2em;
  margin-bottom: 20px;
}

h2 {
  font-size: 1.5em;
  margin-bottom: 15px;
}

h3 {
  font-size: 1.2em;
  margin-top: 20px;
  margin-bottom: 10px;
}

.modules-container {
  display: grid;
  grid-template-columns: 250px 1fr;
  gap: 20px;
  margin-top: 20px;
  align-items: start;
  min-width: 0;

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }
}

.modules-list {
  border: 1px solid #a7bde5;
  border-radius: 4px;
  padding: 15px;
  background-color: #f6f9ff;
  align-self: start;
}

.no-modules {
  padding: 20px;
  text-align: center;
  color: #666;
}

.module-items {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.module-item {
  padding: 10px 12px;
  border: 1px solid #c7d5ef;
  background: white;
  border-radius: 4px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  justify-content: space-between;
  align-items: center;

  &:hover {
    background: #eef5ff;
    border-color: #315fa8;
  }

  &.active {
    background: #001f4d;
    color: white;
    border-color: #001f4d;
  }
}

.module-name {
  font-weight: 500;
  flex: 1;
}

.module-status {
  font-size: 0.85em;
  padding: 2px 6px;
  border-radius: 3px;
  background: #f0f0f0;
  color: #333;

  &.enabled {
    background: #d4edda;
    color: #155724;
  }

  &.disabled {
    background: #f8d7da;
    color: #721c24;
  }
}

.module-detail {
  border: 1px solid #a7bde5;
  border-radius: 4px;
  padding: 20px;
  background: white;
  min-width: 0;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  border-bottom: 2px solid #d9e9ff;
  padding-bottom: 15px;
}

.detail-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.estop-action {
  background: #b32424;
  border-color: #7a1616;
  color: #fff;

  &:hover:not(:disabled) {
    background: #8f1c1c;
    border-color: #7a1616;
    color: #fff;
  }
}

.detail-info {
  margin-bottom: 25px;
}

.info-row {
  display: grid;
  grid-template-columns: 150px 1fr;
  padding: 10px 0;
  border-bottom: 1px solid #eee;

  .label {
    font-weight: 600;
    color: #333;
  }

  .value {
    color: #666;

    &.status {
      font-weight: 600;

      &.enabled {
        color: #155724;
      }
    }

    code {
      background: #f5f5f5;
      padding: 2px 4px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 0.9em;
    }
  }
}

.cron-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.cron-table {
  width: max(100%, 900px);
  border-collapse: collapse;
  margin-top: 10px;
  table-layout: fixed;

  th:nth-child(1) {
    width: 120px;
  }

  th:nth-child(2) {
    width: 220px;
  }

  th:nth-child(3) {
    width: auto;
  }

  th:nth-child(4) {
    width: 110px;
  }

  th:nth-child(5) {
    width: 120px;
  }

  th:nth-child(6) {
    width: 95px;
  }

  th {
    background: #f6f9ff;
    padding: 10px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #ddd;
  }

  td {
    padding: 10px;
    border-bottom: 1px solid #eee;

    code {
      display: inline-block;
      max-width: 100%;
      background: #f6f9ff;
      padding: 2px 4px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 0.9em;
      overflow-wrap: anywhere;
      white-space: normal;
    }

    &.enabled {
      color: #155724;
      font-weight: 600;
    }
  }
}

.runner-cell code {
  line-height: 1.35;
}

.schedule-input,
.timeout-input,
.config-json {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #a7bde5;
  border-radius: 4px;
  font: inherit;

  &:focus {
    outline: none;
    border-color: #315fa8;
    box-shadow: 0 0 0 2px rgba(49, 95, 168, 0.14);
  }
}

.timeout-input {
  max-width: 90px;
}

.cron-expression {
  margin-top: 4px;
  color: #54595d;
  font-size: 0.88em;
}

.enabled-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.module-config {
  border-top: 2px solid #d9e9ff;
  padding-top: 20px;
  margin-top: 25px;
}

.structured-config {
  border: 1px solid #c7d5ef;
  border-radius: 4px;
  background: #f6f9ff;
  padding: 16px;
  margin-bottom: 14px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;

  @media (max-width: 900px) {
    grid-template-columns: 1fr;
  }
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;

  &.wide {
    grid-column: 1 / -1;
  }

  span {
    color: #333;
    font-weight: 600;
  }

  input,
  select {
    width: 100%;
    box-sizing: border-box;
    min-height: 38px;
    padding: 8px 10px;
    border: 1px solid #a7bde5;
    border-radius: 4px;
    background: white;
    color: #202122;
    font: inherit;

    &:focus {
      outline: none;
      border-color: #315fa8;
      box-shadow: 0 0 0 2px rgba(49, 95, 168, 0.14);
    }
  }
}

.config-toggles {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin-top: 16px;

  @media (max-width: 700px) {
    grid-template-columns: 1fr;
  }

  label {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #202122;
    font-weight: 500;
  }
}

.advanced-config {
  margin-bottom: 10px;

  summary {
    color: #315fa8;
    cursor: pointer;
    font-weight: 600;
    margin-bottom: 8px;
  }
}

.config-json {
  min-height: 180px;
  font-family: monospace;
  resize: vertical;
}

.module-access {
  border-top: 2px solid #d9e9ff;
  padding-top: 20px;
  margin-top: 25px;
}

.module-runs {
  border-top: 2px solid #d9e9ff;
  padding-top: 20px;
  margin-top: 25px;
}

.runs-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.runs-table {
  width: max(100%, 760px);
  border-collapse: collapse;
  table-layout: fixed;

  th,
  td {
    padding: 10px;
    border-bottom: 1px solid #eee;
    text-align: left;
    vertical-align: top;
    overflow-wrap: anywhere;
  }

  th {
    background: #f6f9ff;
    border-bottom: 2px solid #ddd;
    font-weight: 600;
  }
}

.help-text {
  color: #666;
  font-size: 0.95em;
  margin-bottom: 15px;
}

.access-form {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}

.username-input {
  flex: 1;
  max-width: 300px;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 0.95em;

  &:focus {
    outline: none;
    border-color: #315fa8;
    box-shadow: 0 0 0 2px rgba(49, 95, 168, 0.14);
  }
}
</style>
