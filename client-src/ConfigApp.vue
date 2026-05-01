<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CdxButton, CdxField, CdxLookup, CdxMessage } from "@wikimedia/codex";
import UnifiedTable from "./components/UnifiedTable.vue";
import { type TableColumn } from "./components/unifiedTable";
import {
  buildSectionedToggleRows,
  buildToggleRows,
  filterToggleRowsBySection,
  toggleCheckboxColumn,
  toggleHelpColumn,
  toggleLabelColumn,
  type ToggleFieldRow,
} from "./components/tableColumnFactories";
import {
  fetchRuntimeAuthzConfig,
  fetchRuntimeUserGrants,
  searchUsernames,
  updateRuntimeAuthzConfig,
  updateRuntimeUserGrants,
  type RuntimeAuthzConfig,
} from "./api";

type NumberConfigKey =
  | "RATE_LIMIT_JOBS_PER_HOUR"
  | "RATE_LIMIT_TESTER_JOBS_PER_HOUR";

interface ConfigInitialProps {
  username: string | null;
  can_edit_config: boolean;
}

type GrantGroupKey =
  | "basic"
  | "read_only"
  | "tester"
  | "viewer"
  | "rollbacker"
  | "rollbacker_dry_run"
  | "batch_runner"
  | "jobs_moderator"
  | "config_editor"
  | "rights_manager"
  | "module_operator"
  | "admin";

type GrantRightKey =
  | "view_all"
  | "write"
  | "rollback_diff"
  | "rollback_account"
  | "rollback_batch"
  | "rollback_diff_dry_run_only"
  | "approve_jobs"
  | "autoapprove_jobs"
  | "force_dry_run"
  | "edit_config"
  | "manage_user_grants"
  | "cancel_any"
  | "retry_any"
  | "manage_modules"
  | "run_module_jobs"
  | "edit_module_config";

type ImplicitFlagKey =
  | "authenticated"
  | "commons_admin"
  | "commons_rollbacker";

type AutoGrantRoleKey =
  | "authenticated"
  | "commons_admin"
  | "commons_rollbacker";

const userGrantGroupFields: Array<{ key: GrantGroupKey; label: string; help: string }> = [
  { key: "basic", label: "basic", help: "Can submit and manage their own rollback queue jobs." },
  { key: "read_only", label: "read_only", help: "Can only view their own jobs." },
  { key: "tester", label: "tester", help: "Can use rollback tools with tester rate limits and no cross-user moderation." },
  { key: "viewer", label: "viewer", help: "Can view all jobs." },
  {
    key: "rollbacker",
    label: "rollbacker",
    help: "Can submit rollback requests for diff and account endpoints.",
  },
  {
    key: "rollbacker_dry_run",
    label: "rollbacker_dry_run",
    help: "Rollbacker rights with dry-run-only enforcement.",
  },
  { key: "batch_runner", label: "batch_runner", help: "Can submit batch rollback requests." },
  {
    key: "jobs_moderator",
    label: "jobs_moderator",
    help: "Can approve/review jobs and perform moderation actions.",
  },
  { key: "config_editor", label: "config_editor", help: "Can edit runtime access configuration." },
  { key: "rights_manager", label: "rights_manager", help: "Can manage rollback-control groups for users." },
  { key: "module_operator", label: "module_operator", help: "Can manage modules and module jobs." },
  { key: "admin", label: "admin", help: "Broad rollback, jobs, and config rights." },
];

const userGrantRightSections: Array<{
  title: string;
  fields: Array<{ key: GrantRightKey; label: string; help: string }>;
}> = [
  {
    title: "Rollback rights",
    fields: [
      { key: "rollback_diff", label: "rollback_diff", help: "Use rollback-from-diff." },
      {
        key: "rollback_account",
        label: "rollback_account",
        help: "Use rollback-from-account.",
      },
      { key: "rollback_batch", label: "rollback_batch", help: "Submit batch rollback requests." },
      {
        key: "rollback_diff_dry_run_only",
        label: "rollback_diff_dry_run_only",
        help: "Enforce dry_run=true for diff/account rollback requests.",
      },
    ],
  },
  {
    title: "Jobs rights",
    fields: [
      { key: "approve_jobs", label: "approve_jobs", help: "Approve or reject pending rollback requests." },
      {
        key: "autoapprove_jobs",
        label: "autoapprove_jobs",
        help: "Allow test-mode requests to auto-approve when enabled.",
      },
      { key: "force_dry_run", label: "force_dry_run", help: "Force pending requests to dry-run mode." },
      { key: "cancel_any", label: "cancel_any", help: "Cancel regular users' jobs." },
      { key: "retry_any", label: "retry_any", help: "Retry jobs across users." },
    ],
  },
  {
    title: "Administration rights",
    fields: [
      { key: "view_all", label: "view_all", help: "Read every user's jobs." },
      { key: "write", label: "write", help: "Submit standard rollback queue jobs." },
      { key: "edit_config", label: "edit_config", help: "Edit runtime authz config values." },
      {
        key: "manage_user_grants",
        label: "manage_user_grants",
        help: "Manage user-centric grant atoms and groups.",
      },
      { key: "manage_modules", label: "manage_modules", help: "Enable, disable, and emergency-stop modules." },
      { key: "run_module_jobs", label: "run_module_jobs", help: "Run or restart module jobs." },
      { key: "edit_module_config", label: "edit_module_config", help: "Edit non-secret module configuration." },
    ],
  },
];

const userGrantRightFields = userGrantRightSections.flatMap((section) => section.fields);

const implicitFlagFields: Array<{ key: ImplicitFlagKey; label: string }> = [
  { key: "authenticated", label: "authenticated" },
  { key: "commons_admin", label: "commons admin (sysop)" },
  { key: "commons_rollbacker", label: "commons rollbacker" },
];

const autoGrantRoleFields: Array<{ key: AutoGrantRoleKey; label: string; help: string }> = [
  { key: "authenticated", label: "authenticated", help: "Any logged-in user." },
  { key: "commons_admin", label: "commons admin", help: "Users in Commons sysop group." },
  {
    key: "commons_rollbacker",
    label: "commons rollbacker",
    help: "Users in Commons rollbacker group.",
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
const canEditConfig = ref(initialProps.can_edit_config);
const canManageUserGrants = ref(initialProps.can_edit_config);

const config = ref<RuntimeAuthzConfig>({
  ROLLBACK_CONTROL_JSON: {},
  ROLE_GRANTS_JSON: {
    commons_admin: ["group:basic"],
    commons_rollbacker: ["group:basic"],
  },
  RATE_LIMIT_JOBS_PER_HOUR: 0,
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: 0,
});

const grantsJsonText = ref("{}");

const userSearchLookupItems = ref<Array<{ label: string; value: string }>>([]);
const userSearchSelected = ref<string | number | null>(null);
const userSearchInputValue = ref("");
const userSearchRequestId = ref(0);

const selectedGrantUser = ref("");
const userGrantLoaded = ref(false);
const userGrantSaving = ref(false);
const userGrantRefreshing = ref(false);
const userGrantReason = ref("");
const commonsGroups = ref<string[]>([]);
const commonsGroupsFresh = ref(false);
const selectedAutoGrantRole = ref<AutoGrantRoleKey>("commons_admin");

const implicitFlags = ref<Record<ImplicitFlagKey, boolean>>({
  authenticated: false,
  bot_admin: false,
  maintainer: false,
  commons_admin: false,
  commons_rollbacker: false,
  tester: false,
  read_only: false,
  extra_authorized: false,
});

function emptyGroupChecks(): Record<GrantGroupKey, boolean> {
  return {
    viewer: false,
    rollbacker: false,
    rollbacker_dry_run: false,
    batch_runner: false,
    jobs_moderator: false,
    admin: false,
  };
}

function emptyRightChecks(): Record<GrantRightKey, boolean> {
  return {
    view_all: false,
    rollback_diff: false,
    rollback_account: false,
    rollback_diff_dry_run_only: false,
    rollback_batch: false,
    approve_jobs: false,
    autoapprove_jobs: false,
    force_dry_run: false,
    edit_config: false,
    manage_user_grants: false,
    cancel_any: false,
    retry_any: false,
  };
}

const userGroupChecks = ref<Record<GrantGroupKey, boolean>>(emptyGroupChecks());
const userRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const autoGrantGroupChecks = ref<Record<GrantGroupKey, boolean>>(emptyGroupChecks());
const autoGrantRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());

const implicitFlagRows = computed<ToggleFieldRow<ImplicitFlagKey>[]>(() =>
  buildToggleRows(implicitFlagFields)
);
const groupRows = computed<ToggleFieldRow<GrantGroupKey>[]>(() =>
  buildToggleRows(userGrantGroupFields)
);
const rightRows = computed<ToggleFieldRow<GrantRightKey>[]>(() =>
  buildSectionedToggleRows(userGrantRightSections)
);
const autoGrantRoleRows = computed<ToggleFieldRow<AutoGrantRoleKey>[]>(() =>
  buildToggleRows(autoGrantRoleFields)
);

const implicitFlagColumns: TableColumn<ToggleFieldRow<ImplicitFlagKey>>[] = [
  toggleLabelColumn("Flag"),
  toggleCheckboxColumn(
    "Enabled",
    (row) => implicitFlags.value[row.key],
    () => {
      // implicit flags are read-only
    },
    () => true,
  ),
];

const groupColumns: TableColumn<ToggleFieldRow<GrantGroupKey>>[] = [
  toggleLabelColumn("Group"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Enabled",
    (row) => userGroupChecks.value[row.key],
    (row, checked) => {
      userGroupChecks.value[row.key] = checked;
    },
    () => !canManageUserGrants.value || userGrantSaving.value,
  ),
];

const rightColumns: TableColumn<ToggleFieldRow<GrantRightKey>>[] = [
  toggleLabelColumn("Right"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Enabled",
    (row) => userRightChecks.value[row.key],
    (row, checked) => {
      userRightChecks.value[row.key] = checked;
    },
    () => !canManageUserGrants.value || userGrantSaving.value,
  ),
];

const autoGrantRoleColumns: TableColumn<ToggleFieldRow<AutoGrantRoleKey>>[] = [
  toggleLabelColumn("Role"),
  toggleHelpColumn("Meaning"),
];

const autoGroupColumns: TableColumn<ToggleFieldRow<GrantGroupKey>>[] = [
  toggleLabelColumn("Group"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Auto-grant",
    (row) => autoGrantGroupChecks.value[row.key],
    (row, checked) => {
      autoGrantGroupChecks.value[row.key] = checked;
    },
    () => !canEditConfig.value || saving.value,
  ),
];

const autoRightColumns: TableColumn<ToggleFieldRow<GrantRightKey>>[] = [
  toggleLabelColumn("Right"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Auto-grant",
    (row) => autoGrantRightChecks.value[row.key],
    (row, checked) => {
      autoGrantRightChecks.value[row.key] = checked;
    },
    () => !canEditConfig.value || saving.value,
  ),
];

function rightsRowsForSection(sectionTitle: string): ToggleFieldRow<GrantRightKey>[] {
  return filterToggleRowsBySection(rightRows.value, sectionTitle);
}

function autoGrantRoleRowsForSelected(): ToggleFieldRow<AutoGrantRoleKey>[] {
  return autoGrantRoleRows.value.filter((row) => row.key === selectedAutoGrantRole.value);
}

function clearAutoGrantChecks(): void {
  autoGrantGroupChecks.value = emptyGroupChecks();
  autoGrantRightChecks.value = emptyRightChecks();
}

function persistSelectedAutoGrantRoleChecks(): void {
  const role = selectedAutoGrantRole.value;
  const atoms: string[] = [];

  for (const field of userGrantGroupFields) {
    if (autoGrantGroupChecks.value[field.key]) {
      atoms.push(`group:${field.key}`);
    }
  }

  for (const field of userGrantRightFields) {
    if (autoGrantRightChecks.value[field.key]) {
      atoms.push(field.key);
    }
  }

  const next = { ...(config.value.ROLE_GRANTS_JSON || {}) };
  if (atoms.length > 0) {
    next[role] = [...new Set(atoms)].sort();
  } else {
    delete next[role];
  }

  config.value.ROLE_GRANTS_JSON = next;
}

function loadSelectedAutoGrantRoleChecks(): void {
  clearAutoGrantChecks();
  const role = selectedAutoGrantRole.value;
  const atoms = config.value.ROLE_GRANTS_JSON?.[role] || [];

  for (const atom of atoms) {
    const normalized = String(atom || "").trim().toLowerCase();
    if (!normalized) continue;

    if (normalized.startsWith("group:")) {
      const groupName = normalized.split(":", 2)[1] as GrantGroupKey;
      if (groupName in autoGrantGroupChecks.value) {
        autoGrantGroupChecks.value[groupName] = true;
      }
      continue;
    }

    if (normalized in autoGrantRightChecks.value) {
      autoGrantRightChecks.value[normalized as GrantRightKey] = true;
    }
  }
}

function onSelectedAutoGrantRoleChange(event: Event): void {
  persistSelectedAutoGrantRoleChecks();
  const target = event.target as HTMLSelectElement | null;
  if (!target) return;
  selectedAutoGrantRole.value = target.value as AutoGrantRoleKey;
  loadSelectedAutoGrantRoleChecks();
}

function onNumberInput(key: NumberConfigKey, event: Event): void {
  const target = event.target as HTMLInputElement | null;
  if (!target) return;

  const parsed = Number.parseInt(target.value || "0", 10);
  config.value[key] = Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
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
  commons_groups?: string[];
  commons_groups_refreshed?: boolean;
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

  commonsGroups.value = [...(payload.commons_groups || [])];
  commonsGroupsFresh.value = !!payload.commons_groups_refreshed;

  const nextMap = { ...(config.value.ROLLBACK_CONTROL_JSON || {}) };
  nextMap[payload.normalized_username] = payload.atoms || [];
  config.value.ROLLBACK_CONTROL_JSON = nextMap;
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
    const payload = await fetchRuntimeUserGrants(rawUser, { refreshCommons: true });
    applyUserGrantPayload(payload);
    successMessage.value = `Loaded rights for ${payload.normalized_username}.`;
    errorMessage.value = "";
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to load user grants";
    successMessage.value = "";
  }
}

async function refreshSelectedUserCommonsRights(): Promise<void> {
  if (!selectedGrantUser.value) return;

  userGrantRefreshing.value = true;
  errorMessage.value = "";

  try {
    const payload = await fetchRuntimeUserGrants(selectedGrantUser.value, {
      refreshCommons: true,
    });
    applyUserGrantPayload(payload);
    successMessage.value = `Refreshed Commons rights for ${payload.normalized_username}.`;
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to refresh Commons rights";
    successMessage.value = "";
  } finally {
    userGrantRefreshing.value = false;
  }
}

async function saveSelectedUserGrants(): Promise<void> {
  if (!canManageUserGrants.value || !selectedGrantUser.value) return;

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
    ROLLBACK_CONTROL_JSON: { ...(nextConfig.ROLLBACK_CONTROL_JSON || {}) },
    ROLE_GRANTS_JSON: { ...(nextConfig.ROLE_GRANTS_JSON || {}) },
    RATE_LIMIT_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_JOBS_PER_HOUR || 0),
    RATE_LIMIT_TESTER_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_TESTER_JOBS_PER_HOUR || 0),
  };

  grantsJsonText.value = JSON.stringify(config.value.ROLLBACK_CONTROL_JSON || {}, null, 2);
  loadSelectedAutoGrantRoleChecks();
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
    canEditConfig.value = !!response.can_edit;
    canManageUserGrants.value = !!response.can_manage_user_grants;
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : "Failed to load config";
  } finally {
    loading.value = false;
  }
}

async function saveConfig(): Promise<void> {
  if (!canEditConfig.value) return;

  saving.value = true;
  errorMessage.value = "";
  successMessage.value = "";

  try {
    const parsedUserGrants = parseUserGrantsJsonText();
    config.value.ROLLBACK_CONTROL_JSON = parsedUserGrants;
    persistSelectedAutoGrantRoleChecks();

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
    <CdxMessage v-if="!canEditConfig" type="warning" class="top-message">
      You can view runtime settings, but only chuckbot can save changes.
    </CdxMessage>

    <CdxMessage
      v-if="!canManageUserGrants"
      type="warning"
      class="top-message"
    >
      You can view grants, but need manage_user_grants to edit user-centric grants.
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
            :disabled="!canManageUserGrants"
            placeholder="Search Commons username"
            @input="onUserSearchLookupInput"
          />
        </CdxField>
        <CdxButton
          type="button"
          :disabled="!canManageUserGrants"
          @click="() => void loadSelectedUserGrants()"
        >
          Load user rights
        </CdxButton>
        <CdxButton
          type="button"
          weight="quiet"
          :disabled="!canManageUserGrants || !selectedGrantUser || userGrantRefreshing"
          @click="() => void refreshSelectedUserCommonsRights()"
        >
          {{ userGrantRefreshing ? "Refreshing..." : "Refresh Commons rights" }}
        </CdxButton>
      </div>

      <div v-if="userGrantLoaded" class="runtime-rights-columns">
        <div>
          <h4>Commons groups (live)</h4>
          <p class="runtime-config-help">
            {{ commonsGroups.length ? commonsGroups.join(", ") : "No explicit Commons groups found." }}
            <span v-if="commonsGroupsFresh"> (freshly queried)</span>
          </p>

          <h4>Groups you cannot change</h4>
          <UnifiedTable
            :rows="implicitFlagRows"
            :columns="implicitFlagColumns"
            row-key="key"
            table-class="runtime-rights-table"
          />
        </div>

        <div>
          <h4>Groups you can change</h4>
          <UnifiedTable
            :rows="groupRows"
            :columns="groupColumns"
            row-key="key"
            table-class="runtime-rights-table"
          />

          <label class="runtime-reason-label">Reason</label>
          <input
            v-model="userGrantReason"
            type="text"
            :disabled="!canManageUserGrants || userGrantSaving"
            placeholder="Optional reason"
          >

          <div class="runtime-config-actions">
            <CdxButton
              action="progressive"
              weight="primary"
              type="button"
              :disabled="!canManageUserGrants || userGrantSaving"
              @click="() => void saveSelectedUserGrants()"
            >
              {{ userGrantSaving ? "Saving..." : "Save user groups" }}
            </CdxButton>
          </div>
        </div>
      </div>
    </section>

    <div v-if="!loading" class="runtime-config-grid runtime-config-grid--numbers">
      <section class="runtime-config-card">
        <h3>Rollback control groups by user</h3>
        <p class="runtime-config-help">
          MediaWiki-style user rights storage: usernames map to groups, and groups
          provide rights. Prefer editing this through the user rights editor above.
        </p>
        <textarea
          v-model="grantsJsonText"
          :disabled="!canEditConfig"
          rows="8"
        />
      </section>

      <section class="runtime-config-card">
        <h3>Auto grants by implicit role</h3>
        <p class="runtime-config-help">
          Configure grants automatically based on implicit roles.
          Commons admin maps to Commons <b>sysop</b>; Commons rollbacker maps to Commons <b>rollbacker</b>.
        </p>

        <label class="runtime-reason-label" for="auto-grant-role-select">Role</label>
        <select
          id="auto-grant-role-select"
          :value="selectedAutoGrantRole"
          :disabled="!canEditConfig || saving"
          @change="onSelectedAutoGrantRoleChange"
        >
          <option v-for="role in autoGrantRoleFields" :key="role.key" :value="role.key">
            {{ role.label }}
          </option>
        </select>

        <UnifiedTable
          :rows="autoGrantRoleRowsForSelected()"
          :columns="autoGrantRoleColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Auto-granted groups</h4>
        <UnifiedTable
          :rows="groupRows"
          :columns="autoGroupColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

      </section>

      <section v-for="field in numberFields" :key="field.key" class="runtime-config-card">
        <h3>{{ field.label }}</h3>
        <p class="runtime-config-help">{{ field.help }}</p>
        <input
          type="number"
          min="0"
          :disabled="!canEditConfig"
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
        :disabled="!canEditConfig || loading || saving"
        @click="saveConfig"
      >
        {{ saving ? "Saving..." : "Save runtime config" }}
      </CdxButton>
    </div>
  </div>
</template>
