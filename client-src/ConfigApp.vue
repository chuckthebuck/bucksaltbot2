<script setup lang="ts">
import { onMounted, ref } from "vue";
import { CdxButton, CdxField, CdxLookup, CdxMessage } from "@wikimedia/codex";
import {
  fetchRuntimeAuthzConfig,
  fetchRuntimeUserGrants,
  searchUsernames,
  updateRuntimeAuthzConfig,
  updateRuntimeUserGrants,
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

type GrantGroupKey =
  | "viewer"
  | "diff"
  | "diff_dry_run"
  | "batch"
  | "support"
  | "operator";

type GrantRightKey =
  | "view_all"
  | "from_diff"
  | "from_diff_dry_run_only"
  | "batch"
  | "cancel_any"
  | "retry_any";

type ImplicitFlagKey =
  | "bot_admin"
  | "maintainer"
  | "tester"
  | "read_only"
  | "extra_authorized";

const userGrantGroupFields: Array<{ key: GrantGroupKey; label: string; help: string }> = [
  { key: "viewer", label: "viewer", help: "Can view all jobs." },
  { key: "diff", label: "diff", help: "Can use from-diff." },
  { key: "diff_dry_run", label: "diff_dry_run", help: "From-diff in dry-run mode only." },
  { key: "batch", label: "batch", help: "Can use batch rollback." },
  { key: "support", label: "support", help: "View-all + retry-any support role." },
  { key: "operator", label: "operator", help: "Full operator rights." },
];

const userGrantRightFields: Array<{ key: GrantRightKey; label: string; help: string }> = [
  { key: "view_all", label: "view_all", help: "Read every user's jobs." },
  { key: "from_diff", label: "from_diff", help: "Use rollback-from-diff." },
  {
    key: "from_diff_dry_run_only",
    label: "from_diff_dry_run_only",
    help: "Allow from-diff only when dry_run=true.",
  },
  { key: "batch", label: "batch", help: "Use batch rollback UI." },
  { key: "cancel_any", label: "cancel_any", help: "Cancel regular users' jobs." },
  { key: "retry_any", label: "retry_any", help: "Retry jobs across users." },
];

const implicitFlagFields: Array<{ key: ImplicitFlagKey; label: string }> = [
  { key: "bot_admin", label: "bot admin" },
  { key: "maintainer", label: "maintainer" },
  { key: "tester", label: "tester" },
  { key: "read_only", label: "read only" },
  { key: "extra_authorized", label: "extra authorized" },
];

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
  USER_GRANTS_JSON: {},
  RATE_LIMIT_JOBS_PER_HOUR: 0,
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: 0,
});

const listText = ref<Record<string, string>>({});
const grantsJsonText = ref("{}");
const lookupMenuItems = ref<Record<string, Array<{ label: string; value: string }>>>({});
const lookupSelected = ref<Record<string, string | number | null>>({});
const lookupInputValue = ref<Record<string, string>>({});
const lookupRequestIds: Record<string, number> = {};

const userSearchLookupItems = ref<Array<{ label: string; value: string }>>([]);
const userSearchSelected = ref<string | number | null>(null);
const userSearchInputValue = ref("");
const userSearchRequestId = ref(0);

const selectedGrantUser = ref("");
const userGrantLoaded = ref(false);
const userGrantSaving = ref(false);
const userGrantReason = ref("");

const implicitFlags = ref<Record<ImplicitFlagKey, boolean>>({
  bot_admin: false,
  maintainer: false,
  tester: false,
  read_only: false,
  extra_authorized: false,
});

const userGroupChecks = ref<Record<GrantGroupKey, boolean>>({
  viewer: false,
  diff: false,
  diff_dry_run: false,
  batch: false,
  support: false,
  operator: false,
});

const userRightChecks = ref<Record<GrantRightKey, boolean>>({
  view_all: false,
  from_diff: false,
  from_diff_dry_run_only: false,
  batch: false,
  cancel_any: false,
  retry_any: false,
});

function normalizeUserList(raw: string): string[] {
  const users = raw
    .replace(/\n/g, ",")
    .split(",")
    .map((part) => part.trim())
    .map((part) => {
      let cleaned = part;

      if (cleaned.toLowerCase().startsWith("user:")) {
        cleaned = cleaned.slice(5).trim();
      }

      if (
        cleaned.length >= 2 &&
        ((cleaned.startsWith('"') && cleaned.endsWith('"')) ||
          (cleaned.startsWith("'") && cleaned.endsWith("'")))
      ) {
        cleaned = cleaned.slice(1, -1).trim();
      }

      cleaned = cleaned.replace(/_/g, " ").replace(/\s+/g, " ").trim();

      return cleaned.toLowerCase();
    })
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
  lookupInputValue.value[key] = query;
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

async function addLookupSelection(key: ListConfigKey): Promise<void> {
  const selected = lookupSelected.value[key];
  const typed = (lookupInputValue.value[key] || "").trim();

  // Codex lookup sets "selected" only when a menu item is chosen.
  // If the user types a complete username and clicks Add directly,
  // use the typed value so the button still performs the expected action.
  const rawCandidate =
    selected !== null && selected !== undefined && String(selected).trim()
      ? String(selected).trim()
      : typed;

  const candidate = rawCandidate.toLowerCase();
  if (!candidate) return;

  const next = new Set(config.value[key] || []);
  next.add(candidate);
  config.value[key] = [...next].sort();
  listText.value[key] = config.value[key].join(", ");

  lookupSelected.value[key] = null;
  lookupInputValue.value[key] = "";
  lookupMenuItems.value[key] = [];

  // Persist immediately for button-driven adds so the backend table updates
  // without requiring a separate click on the global Save button.
  if (!canEdit.value) return;

  try {
    const response = await updateRuntimeAuthzConfig({
      [key]: config.value[key],
    });
    applyServerConfig(response.config);
    successMessage.value = `Updated ${key}.`;
    errorMessage.value = "";
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to save config";
    successMessage.value = "";
  }
}

async function onUserSearchLookupInput(value: string | number): Promise<void> {
  const query = String(value || "").trim();
  userSearchInputValue.value = query;

  const requestId = userSearchRequestId.value + 1;
  userSearchRequestId.value = requestId;

  if (!query) {
    userSearchLookupItems.value = [];
    return;
  }

  try {
    const users = await searchUsernames(query);
    if (userSearchRequestId.value !== requestId) return;
    userSearchLookupItems.value = users;
  } catch {
    if (userSearchRequestId.value !== requestId) return;
    userSearchLookupItems.value = [];
  }
}

function clearUserGrantChecks(): void {
  for (const field of userGrantGroupFields) {
    userGroupChecks.value[field.key] = false;
  }

  for (const field of userGrantRightFields) {
    userRightChecks.value[field.key] = false;
  }
}

function applyUserGrantPayload(payload: {
  normalized_username: string;
  groups: string[];
  rights: string[];
  implicit: Record<string, boolean>;
  atoms: string[];
}): void {
  selectedGrantUser.value = payload.normalized_username;
  userGrantLoaded.value = true;
  clearUserGrantChecks();

  for (const group of payload.groups || []) {
    if (group in userGroupChecks.value) {
      userGroupChecks.value[group as GrantGroupKey] = true;
    }
  }

  for (const right of payload.rights || []) {
    if (right in userRightChecks.value) {
      userRightChecks.value[right as GrantRightKey] = true;
    }
  }

  for (const field of implicitFlagFields) {
    implicitFlags.value[field.key] = !!payload.implicit?.[field.key];
  }

  const nextMap = { ...(config.value.USER_GRANTS_JSON || {}) };
  nextMap[payload.normalized_username] = payload.atoms || [];
  config.value.USER_GRANTS_JSON = nextMap;
  grantsJsonText.value = JSON.stringify(nextMap, null, 2);
}

async function loadSelectedUserGrants(): Promise<void> {
  const selected = userSearchSelected.value;
  const typed = userSearchInputValue.value;
  const rawUser =
    selected !== null && selected !== undefined && String(selected).trim()
      ? String(selected).trim()
      : String(typed || "").trim();

  if (!rawUser) {
    errorMessage.value = "Select or type a username to load user rights.";
    successMessage.value = "";
    return;
  }

  try {
    const payload = await fetchRuntimeUserGrants(rawUser);
    applyUserGrantPayload(payload);
    successMessage.value = `Loaded rights for ${payload.normalized_username}.`;
    errorMessage.value = "";
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to load user grants";
    successMessage.value = "";
  }
}

async function saveSelectedUserGrants(): Promise<void> {
  if (!canEdit.value || !selectedGrantUser.value) return;

  userGrantSaving.value = true;
  errorMessage.value = "";
  successMessage.value = "";

  try {
    const groups = userGrantGroupFields
      .filter((field) => userGroupChecks.value[field.key])
      .map((field) => field.key);
    const rights = userGrantRightFields
      .filter((field) => userRightChecks.value[field.key])
      .map((field) => field.key);

    const payload = await updateRuntimeUserGrants(selectedGrantUser.value, {
      groups,
      rights,
      reason: userGrantReason.value,
    });

    applyUserGrantPayload(payload);
    successMessage.value = `Saved user grants for ${payload.normalized_username}.`;
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to save user grants";
  } finally {
    userGrantSaving.value = false;
  }
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
    USER_GRANTS_JSON: { ...(nextConfig.USER_GRANTS_JSON || {}) },
    RATE_LIMIT_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_JOBS_PER_HOUR || 0),
    RATE_LIMIT_TESTER_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_TESTER_JOBS_PER_HOUR || 0),
  };

  syncTextFromConfig();
  grantsJsonText.value = JSON.stringify(config.value.USER_GRANTS_JSON || {}, null, 2);
}

function parseUserGrantsJsonText(): Record<string, string[]> {
  const trimmed = grantsJsonText.value.trim();
  if (!trimmed) return {};

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("User-centric grants JSON must be an object");
  }

  return parsed as Record<string, string[]>;
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
    const parsedUserGrants = parseUserGrantsJsonText();
    config.value.USER_GRANTS_JSON = parsedUserGrants;

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

    <section v-if="!loading" class="runtime-config-card runtime-rights-editor">
      <h3>User rights editor</h3>
      <p class="runtime-config-help">
        Edit rights in a Special:ChangeUserRights style flow: pick a user, review implicit groups,
        toggle grant groups/rights, and save.
      </p>

      <div class="runtime-user-picker">
        <CdxField>
          <CdxLookup
            v-model:selected="userSearchSelected"
            :menu-items="userSearchLookupItems"
            :disabled="!canEdit"
            placeholder="Search Commons username"
            @input="onUserSearchLookupInput"
          />
        </CdxField>
        <CdxButton type="button" :disabled="!canEdit" @click="() => void loadSelectedUserGrants()">
          Load user rights
        </CdxButton>
      </div>

      <div v-if="userGrantLoaded" class="runtime-rights-columns">
        <div>
          <h4>Groups you cannot change</h4>
          <label
            v-for="flag in implicitFlagFields"
            :key="flag.key"
            class="runtime-checkbox-row runtime-checkbox-row--disabled"
          >
            <input type="checkbox" :checked="implicitFlags[flag.key]" disabled>
            <span>{{ flag.label }}</span>
          </label>
        </div>

        <div>
          <h4>Groups you can change</h4>
          <label
            v-for="group in userGrantGroupFields"
            :key="group.key"
            class="runtime-checkbox-row"
          >
            <input v-model="userGroupChecks[group.key]" type="checkbox" :disabled="!canEdit || userGrantSaving">
            <span>
              {{ group.label }}
              <small>{{ group.help }}</small>
            </span>
          </label>

          <h4>Rights you can change</h4>
          <label
            v-for="right in userGrantRightFields"
            :key="right.key"
            class="runtime-checkbox-row"
          >
            <input v-model="userRightChecks[right.key]" type="checkbox" :disabled="!canEdit || userGrantSaving">
            <span>
              {{ right.label }}
              <small>{{ right.help }}</small>
            </span>
          </label>

          <label class="runtime-reason-label">Reason</label>
          <input
            v-model="userGrantReason"
            type="text"
            :disabled="!canEdit || userGrantSaving"
            placeholder="Optional reason"
          >

          <div class="runtime-config-actions">
            <CdxButton
              action="progressive"
              weight="primary"
              type="button"
              :disabled="!canEdit || userGrantSaving"
              @click="() => void saveSelectedUserGrants()"
            >
              {{ userGrantSaving ? "Saving..." : "Save user groups" }}
            </CdxButton>
          </div>
        </div>
      </div>
    </section>

    <div v-if="!loading" class="runtime-config-grid">
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
          <CdxButton type="button" :disabled="!canEdit" @click="() => void addLookupSelection(field.key)">
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
      <section class="runtime-config-card">
        <h3>User-centric grants (by username)</h3>
        <p class="runtime-config-help">
          Optional JSON map of username to grants. Supports rights and groups.
          Rights: view_all, from_diff, from_diff_dry_run_only, batch, cancel_any, retry_any.
          Groups: viewer, diff, diff_dry_run, batch, support, operator.
        </p>
        <textarea
          v-model="grantsJsonText"
          :disabled="!canEdit"
          rows="8"
        />
      </section>

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
