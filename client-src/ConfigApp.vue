<script setup lang="ts">
import { onMounted, ref } from "vue";
import { CdxButton, CdxField, CdxLookup, CdxMessage } from "@wikimedia/codex";
import {
  fetchRuntimeAuthzConfig,
  searchUsernames,
  updateRuntimeAuthzConfig,
  type RuntimeAuthzConfig,
} from "./api";

type ListConfigKey =
  | "EXTRA_AUTHORIZED_USERS"
  | "USERS_READ_ONLY"
  | "USERS_TESTER"
  | "USERS_GRANTED_FROM_DIFF"
  | "USERS_GRANTED_VIEW_ALL"
  | "USERS_GRANTED_BATCH"
  | "USERS_GRANTED_CANCEL_ANY"
  | "USERS_GRANTED_RETRY_ANY";

type NumberConfigKey =
  | "RATE_LIMIT_JOBS_PER_HOUR"
  | "RATE_LIMIT_TESTER_JOBS_PER_HOUR";

interface ConfigInitialProps {
  username: string | null;
  can_edit_config: boolean;
}

const listFields: Array<{ key: ListConfigKey; label: string; help: string }> = [
  {
    key: "EXTRA_AUTHORIZED_USERS",
    label: "Extra authorized users",
    help: "Additional users with basic authorization.",
  },
  {
    key: "USERS_READ_ONLY",
    label: "Read-only users",
    help: "Users who can only view their own jobs.",
  },
  {
    key: "USERS_TESTER",
    label: "Tester tier",
    help: "Users with tester-level access.",
  },
  {
    key: "USERS_GRANTED_FROM_DIFF",
    label: "Granted: from-diff",
    help: "Users granted rollback-from-diff access.",
  },
  {
    key: "USERS_GRANTED_VIEW_ALL",
    label: "Granted: view all jobs",
    help: "Users granted all-jobs visibility.",
  },
  {
    key: "USERS_GRANTED_BATCH",
    label: "Granted: batch",
    help: "Users granted batch rollback access.",
  },
  {
    key: "USERS_GRANTED_CANCEL_ANY",
    label: "Granted: cancel any",
    help: "Users granted cross-user cancel permission.",
  },
  {
    key: "USERS_GRANTED_RETRY_ANY",
    label: "Granted: retry any",
    help: "Users granted cross-user retry permission.",
  },
];

const numberFields: Array<{ key: NumberConfigKey; label: string; help: string }> = [
  {
    key: "RATE_LIMIT_JOBS_PER_HOUR",
    label: "Regular jobs/hour limit",
    help: "0 disables regular-user rate limiting.",
  },
  {
    key: "RATE_LIMIT_TESTER_JOBS_PER_HOUR",
    label: "Tester jobs/hour limit",
    help: "0 disables tester rate limiting.",
  },
];

function parseInitialProps(): ConfigInitialProps {
  const el = document.getElementById("runtime-config-props");
  if (!el?.textContent) {
    return {
      username: null,
      can_edit_config: false,
    };
  }

  try {
    const parsed = JSON.parse(el.textContent);
    return {
      username: parsed.username ?? null,
      can_edit_config: !!parsed.can_edit_config,
    };
  } catch {
    return {
      username: null,
      can_edit_config: false,
    };
  }
}

const initialProps = parseInitialProps();

const loading = ref(true);
const saving = ref(false);
const errorMessage = ref("");
const successMessage = ref("");
const canEdit = ref(initialProps.can_edit_config);

const config = ref<RuntimeAuthzConfig>({
  EXTRA_AUTHORIZED_USERS: [],
  USERS_READ_ONLY: [],
  USERS_TESTER: [],
  USERS_GRANTED_FROM_DIFF: [],
  USERS_GRANTED_VIEW_ALL: [],
  USERS_GRANTED_BATCH: [],
  USERS_GRANTED_CANCEL_ANY: [],
  USERS_GRANTED_RETRY_ANY: [],
  RATE_LIMIT_JOBS_PER_HOUR: 0,
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: 0,
});

const listText = ref<Record<string, string>>({});
const lookupMenuItems = ref<Record<string, Array<{ label: string; value: string }>>>({});
const lookupSelected = ref<Record<string, string | number | null>>({});
const lookupRequestIds: Record<string, number> = {};

function normalizeUserList(raw: string): string[] {
  const users = raw
    .replace(/\n/g, ",")
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter((part) => part.length > 0);

  return [...new Set(users)].sort();
}

function syncTextFromConfig(): void {
  for (const field of listFields) {
    listText.value[field.key] = (config.value[field.key] || []).join(", ");
  }
}

function onListInput(key: ListConfigKey, event: Event): void {
  const target = event.target as HTMLTextAreaElement | null;
  if (!target) return;

  listText.value[key] = target.value;
  config.value[key] = normalizeUserList(target.value);
}

function onNumberInput(key: NumberConfigKey, event: Event): void {
  const target = event.target as HTMLInputElement | null;
  if (!target) return;

  const parsed = Number.parseInt(target.value || "0", 10);
  config.value[key] = Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
}

async function onLookupInput(key: ListConfigKey, value: string | number): Promise<void> {
  const query = String(value || "").trim();
  const requestId = (lookupRequestIds[key] || 0) + 1;
  lookupRequestIds[key] = requestId;

  if (!query) {
    lookupMenuItems.value[key] = [];
    return;
  }

  try {
    const users = await searchUsernames(query);
    if (lookupRequestIds[key] !== requestId) return;
    lookupMenuItems.value[key] = users;
  } catch {
    if (lookupRequestIds[key] !== requestId) return;
    lookupMenuItems.value[key] = [];
  }
}

function addLookupSelection(key: ListConfigKey): void {
  const selected = lookupSelected.value[key];
  if (selected === null || selected === undefined) return;

  const candidate = String(selected).trim().toLowerCase();
  if (!candidate) return;

  const next = new Set(config.value[key] || []);
  next.add(candidate);
  config.value[key] = [...next].sort();
  listText.value[key] = config.value[key].join(", ");

  lookupSelected.value[key] = null;
  lookupMenuItems.value[key] = [];
}

function applyServerConfig(nextConfig: RuntimeAuthzConfig): void {
  config.value = {
    ...nextConfig,
    EXTRA_AUTHORIZED_USERS: [...(nextConfig.EXTRA_AUTHORIZED_USERS || [])],
    USERS_READ_ONLY: [...(nextConfig.USERS_READ_ONLY || [])],
    USERS_TESTER: [...(nextConfig.USERS_TESTER || [])],
    USERS_GRANTED_FROM_DIFF: [...(nextConfig.USERS_GRANTED_FROM_DIFF || [])],
    USERS_GRANTED_VIEW_ALL: [...(nextConfig.USERS_GRANTED_VIEW_ALL || [])],
    USERS_GRANTED_BATCH: [...(nextConfig.USERS_GRANTED_BATCH || [])],
    USERS_GRANTED_CANCEL_ANY: [...(nextConfig.USERS_GRANTED_CANCEL_ANY || [])],
    USERS_GRANTED_RETRY_ANY: [...(nextConfig.USERS_GRANTED_RETRY_ANY || [])],
    RATE_LIMIT_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_JOBS_PER_HOUR || 0),
    RATE_LIMIT_TESTER_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_TESTER_JOBS_PER_HOUR || 0),
  };

  syncTextFromConfig();
}

async function loadConfig(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";

  try {
    const response = await fetchRuntimeAuthzConfig();
    applyServerConfig(response.config);
    canEdit.value = !!response.can_edit;
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to load config";
  } finally {
    loading.value = false;
  }
}

async function saveConfig(): Promise<void> {
  if (!canEdit.value) return;

  saving.value = true;
  errorMessage.value = "";
  successMessage.value = "";

  try {
    const response = await updateRuntimeAuthzConfig(config.value);
    applyServerConfig(response.config);
    successMessage.value = "Runtime config updated.";
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to save config";
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void loadConfig();
});
</script>

<template>
  <div class="container runtime-config-container">
    <CdxMessage v-if="!canEdit" type="warning" class="top-message">
      You can view runtime settings, but only chuckbot can save changes.
    </CdxMessage>

    <CdxMessage v-if="errorMessage" type="error" class="top-message">
      {{ errorMessage }}
    </CdxMessage>

    <CdxMessage v-if="successMessage" type="success" class="top-message">
      {{ successMessage }}
    </CdxMessage>

    <div v-if="loading">Loading runtime config...</div>

    <div v-else class="runtime-config-grid">
      <section v-for="field in listFields" :key="field.key" class="runtime-config-card">
        <h3>{{ field.label }}</h3>
        <p class="runtime-config-help">{{ field.help }}</p>

        <CdxField>
          <CdxLookup
            v-model:selected="lookupSelected[field.key]"
            :menu-items="lookupMenuItems[field.key] || []"
            :disabled="!canEdit"
            placeholder="Search Commons username"
            @input="(value) => onLookupInput(field.key, value)"
          />
        </CdxField>

        <div class="runtime-config-actions">
          <CdxButton type="button" :disabled="!canEdit" @click="addLookupSelection(field.key)">
            Add selected user
          </CdxButton>
        </div>

        <textarea
          :value="listText[field.key] || ''"
          :disabled="!canEdit"
          rows="3"
          @input="(event) => onListInput(field.key, event)"
        />
      </section>
    </div>

    <div v-if="!loading" class="runtime-config-grid runtime-config-grid--numbers">
      <section v-for="field in numberFields" :key="field.key" class="runtime-config-card">
        <h3>{{ field.label }}</h3>
        <p class="runtime-config-help">{{ field.help }}</p>
        <input
          type="number"
          min="0"
          :disabled="!canEdit"
          :value="config[field.key]"
          @input="(event) => onNumberInput(field.key, event)"
        />
      </section>
    </div>

    <div class="runtime-config-save">
      <CdxButton
        action="progressive"
        weight="primary"
        type="button"
        :disabled="!canEdit || loading || saving"
        @click="saveConfig"
      >
        {{ saving ? "Saving..." : "Save runtime config" }}
      </CdxButton>
    </div>
  </div>
</template>
