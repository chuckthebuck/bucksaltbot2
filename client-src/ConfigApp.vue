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
  | "estop_rollback"
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

type AutoGrantRoleKey = string;

interface GrantAdvisory {
  key: string;
  title: string;
  detail: string;
}

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
  { key: "rights_manager", label: "rights_manager", help: "Can manage framework groups for users." },
  { key: "module_operator", label: "module_operator", help: "Can manage modules and module jobs." },
  { key: "admin", label: "admin", help: "Broad rollback, jobs, and config rights." },
];

const builtInFrameworkGroupRights: Record<GrantGroupKey, GrantRightKey[]> = {
  basic: ["write"],
  read_only: [],
  tester: ["write", "view_all", "rollback_diff", "rollback_account", "rollback_batch"],
  viewer: ["view_all"],
  rollbacker: ["write", "rollback_diff", "rollback_account"],
  rollbacker_dry_run: ["write", "rollback_diff", "rollback_account", "rollback_diff_dry_run_only"],
  batch_runner: ["write", "rollback_batch"],
  jobs_moderator: ["approve_jobs", "force_dry_run", "cancel_any", "retry_any"],
  config_editor: ["edit_config"],
  rights_manager: ["manage_user_grants"],
  module_operator: ["manage_modules", "run_module_jobs", "edit_module_config"],
  admin: [
    "write",
    "view_all",
    "rollback_diff",
    "rollback_account",
    "rollback_batch",
    "estop_rollback",
    "approve_jobs",
    "autoapprove_jobs",
    "force_dry_run",
    "cancel_any",
    "retry_any",
    "edit_config",
    "manage_user_grants",
    "manage_modules",
    "run_module_jobs",
    "edit_module_config",
  ],
};

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
      {
        key: "estop_rollback",
        label: "estop_rollback",
        help: "Emergency-stop the bundled rollback module.",
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

const baseAutoGrantRoleFields: Array<{ key: AutoGrantRoleKey; label: string; help: string }> = [
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
const moduleRights = ref<Record<string, string[]>>({});
const projectGroupOptions = ref<Record<string, string[]>>({});
const globalGroupOptions = ref<string[]>([]);

const config = ref<RuntimeAuthzConfig>({
  ROLLBACK_CONTROL_JSON: {},
  ROLE_GRANTS_JSON: {
    commons_admin: ["group:basic"],
    commons_rollbacker: ["group:basic"],
  },
  CHUCKBOT_GROUPS_JSON: {},
  RATE_LIMIT_JOBS_PER_HOUR: 0,
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: 0,
});

const grantsJsonText = ref("{}");
const groupsJsonText = ref("{}");
const autoGrantsJsonText = ref("{}");

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
const projectGroups = ref<Record<string, string[]>>({});
const globalGroups = ref<string[]>([]);
const commonsGroupsFresh = ref(false);
const selectedAutoGrantRole = ref<AutoGrantRoleKey>("commons_admin");
const selectedAutoGrantSource = ref<"built_in" | "project" | "global">("project");
const selectedAutoGrantProject = ref("commons");
const newAutoGrantScope = ref<"project" | "global">("project");
const newAutoGrantProject = ref("commons");
const newAutoGrantGroup = ref("");
const selectedFrameworkGroup = ref<GrantGroupKey | string>("basic");
const newFrameworkGroup = ref("");

const implicitFlags = ref<Record<ImplicitFlagKey, boolean>>({
  authenticated: false,
  commons_admin: false,
  commons_rollbacker: false,
});

function emptyGroupChecks(): Record<GrantGroupKey, boolean> {
  return {
    basic: false,
    read_only: false,
    tester: false,
    viewer: false,
    rollbacker: false,
    rollbacker_dry_run: false,
    batch_runner: false,
    jobs_moderator: false,
    config_editor: false,
    rights_manager: false,
    module_operator: false,
    admin: false,
  };
}

function emptyRightChecks(): Record<GrantRightKey, boolean> {
  return {
    view_all: false,
    write: false,
    rollback_diff: false,
    rollback_account: false,
    rollback_diff_dry_run_only: false,
    rollback_batch: false,
    estop_rollback: false,
    approve_jobs: false,
    autoapprove_jobs: false,
    force_dry_run: false,
    edit_config: false,
    manage_user_grants: false,
    cancel_any: false,
    retry_any: false,
    manage_modules: false,
    run_module_jobs: false,
    edit_module_config: false,
  };
}

const userGroupChecks = ref<Record<string, boolean>>(emptyGroupChecks());
const userRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const autoGrantGroupChecks = ref<Record<string, boolean>>(emptyGroupChecks());
const autoGrantRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const autoGrantModuleRightChecks = ref<Record<string, boolean>>({});
const frameworkGroupRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const frameworkGroupModuleRightChecks = ref<Record<string, boolean>>({});

const rightRows = computed<ToggleFieldRow<GrantRightKey>[]>(() =>
  buildSectionedToggleRows(userGrantRightSections)
);
const autoGrantRoleFields = computed<Array<{ key: AutoGrantRoleKey; label: string; help: string }>>(() => {
  const baseByKey = new Map(baseAutoGrantRoleFields.map((field) => [field.key, field]));
  const roles = new Set<string>([
    ...baseAutoGrantRoleFields.map((field) => field.key),
    ...Object.keys(config.value.ROLE_GRANTS_JSON || {}),
  ]);

  return [...roles].sort().map((role) => {
    const base = baseByKey.get(role);
    if (base) return base;
    return {
      key: role,
      label: role,
      help: autoGrantRoleHelp(role),
    };
  });
});

const autoGrantProjects = computed(() => {
  const projects = new Set(["commons", "enwiki", ...Object.keys(projectGroupOptions.value)]);
  for (const role of Object.keys(config.value.ROLE_GRANTS_JSON || {})) {
    const parts = role.split(":");
    if (parts.length === 3 && parts[0] === "project" && parts[1]) {
      projects.add(parts[1]);
    }
  }
  const pendingProject = normalizeRolePart(newAutoGrantProject.value);
  if (pendingProject) {
    projects.add(pendingProject);
  }
  return [...projects].sort();
});

const newAutoGrantGroupOptions = computed(() => {
  if (newAutoGrantScope.value === "global") {
    return globalGroupOptions.value;
  }
  const project = normalizeRolePart(newAutoGrantProject.value);
  return projectGroupOptions.value[project] || [];
});

const filteredAutoGrantRoleFields = computed(() =>
  autoGrantRoleFields.value.filter((field) => autoGrantRoleMatchesSelection(field.key))
);

const frameworkGroupFields = computed<Array<{ key: string; label: string; help: string }>>(() => {
  const configured = Object.keys(config.value.CHUCKBOT_GROUPS_JSON || {});
  const groups = new Set<string>([
    ...userGrantGroupFields.map((field) => field.key),
    ...configured,
  ]);
  const baseByKey = new Map(userGrantGroupFields.map((field) => [field.key, field]));

  return [...groups].sort().map((group) => {
    const base = baseByKey.get(group as GrantGroupKey);
    return {
      key: group,
      label: group,
      help: base?.help || "Custom framework group.",
    };
  });
});

const groupRows = computed<ToggleFieldRow<string>[]>(() =>
  buildToggleRows(frameworkGroupFields.value)
);

const autoGrantRoleRows = computed<ToggleFieldRow<AutoGrantRoleKey>[]>(() =>
  buildToggleRows(autoGrantRoleFields.value)
);

const implicitFlagStatusRows = computed(() =>
  implicitFlagFields.map((field) => ({
    ...field,
    enabled: !!implicitFlags.value[field.key],
  }))
);

const groupColumns: TableColumn<ToggleFieldRow<string>>[] = [
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

const autoGroupColumns: TableColumn<ToggleFieldRow<string>>[] = [
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

function autoGrantRoleMatchesSelection(role: string): boolean {
  if (selectedAutoGrantSource.value === "built_in") {
    return role === "authenticated";
  }

  if (selectedAutoGrantSource.value === "global") {
    return role.startsWith("global:");
  }

  const selectedProject = normalizeRolePart(selectedAutoGrantProject.value);
  if (selectedProject === "commons" && ["commons_admin", "commons_rollbacker"].includes(role)) {
    return true;
  }
  const parts = role.split(":");
  return parts.length === 3 && parts[0] === "project" && parts[1] === selectedProject;
}

function selectFirstVisibleAutoGrantRole(): void {
  const first = filteredAutoGrantRoleFields.value[0]?.key;
  if (!first) return;
  selectedAutoGrantRole.value = first;
  loadSelectedAutoGrantRoleChecks();
}

function syncSelectedAutoGrantRoleVisibility(): void {
  if (!filteredAutoGrantRoleFields.value.some((field) => field.key === selectedAutoGrantRole.value)) {
    selectFirstVisibleAutoGrantRole();
  }
}

const autoGrantModuleRightRows = computed(() => {
  const rows: Array<{ key: string; label: string; help: string; moduleName: string }> = [];
  for (const [moduleName, rights] of Object.entries(moduleRights.value)) {
    for (const right of rights) {
      rows.push({
        key: `module:${moduleName}:${right}`,
        label: `module:${moduleName}:${right}`,
        help: `Grant ${right} for ${moduleName}.`,
        moduleName,
      });
    }
  }
  return rows.sort((a, b) => a.key.localeCompare(b.key));
});

const autoModuleRightColumns: TableColumn<{ key: string; label: string; help: string; moduleName: string }>[] = [
  toggleLabelColumn("Module right"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Auto-grant",
    (row) => !!autoGrantModuleRightChecks.value[row.key],
    (row, checked) => {
      autoGrantModuleRightChecks.value[row.key] = checked;
    },
    () => !canEditConfig.value || saving.value,
  ),
];

const frameworkGroupRows = computed<ToggleFieldRow<string>[]>(() =>
  buildToggleRows(frameworkGroupFields.value)
);

const frameworkGroupColumns: TableColumn<ToggleFieldRow<string>>[] = [
  toggleLabelColumn("Group"),
  toggleHelpColumn("Description"),
];

const frameworkGroupRightColumns: TableColumn<ToggleFieldRow<GrantRightKey>>[] = [
  toggleLabelColumn("Right"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Included",
    (row) => frameworkGroupRightChecks.value[row.key],
    (row, checked) => {
      frameworkGroupRightChecks.value[row.key] = checked;
    },
    () => !canEditConfig.value || saving.value,
  ),
];

const frameworkGroupModuleRightColumns: TableColumn<{ key: string; label: string; help: string; moduleName: string }>[] = [
  toggleLabelColumn("Module right"),
  toggleHelpColumn("Description"),
  toggleCheckboxColumn(
    "Included",
    (row) => !!frameworkGroupModuleRightChecks.value[row.key],
    (row, checked) => {
      frameworkGroupModuleRightChecks.value[row.key] = checked;
    },
    () => !canEditConfig.value || saving.value,
  ),
];

function frameworkGroupRowsForSelected(): ToggleFieldRow<string>[] {
  return frameworkGroupRows.value.filter((row) => row.key === selectedFrameworkGroup.value);
}

function checkedRights(checks: Record<GrantRightKey, boolean>): Set<GrantRightKey> {
  return new Set(
    userGrantRightFields
      .filter((field) => checks[field.key])
      .map((field) => field.key),
  );
}

function expandCheckedGroups(checks: Record<string, boolean>): Set<GrantRightKey> {
  const rights = new Set<GrantRightKey>();
  for (const field of userGrantGroupFields) {
    if (!checks[field.key]) continue;
    for (const right of builtInFrameworkGroupRights[field.key] || []) {
      rights.add(right);
    }
  }
  return rights;
}

function collectGrantAdvisories(rights: Set<GrantRightKey>): GrantAdvisory[] {
  const advisories: GrantAdvisory[] = [];
  const hasAnyRequestRight = [
    "write",
    "rollback_diff",
    "rollback_account",
    "rollback_batch",
  ].some((right) => rights.has(right as GrantRightKey));

  if (hasAnyRequestRight && rights.has("autoapprove_jobs")) {
    advisories.push({
      key: "request-autoapprove",
      title: "Request and auto-approve are combined",
      detail:
        "This grant can let the same role submit rollback work and bypass review for eligible requests. Use only for highly trusted operators or test-only flows.",
    });
  }

  if (rights.has("view_all") && rights.has("approve_jobs")) {
    advisories.push({
      key: "view-approve",
      title: "View-all and approve are combined",
      detail:
        "This is effectively a request moderator role: the user can inspect other users' requests and approve or reject them.",
    });
  }

  if (rights.has("approve_jobs") && !rights.has("view_all")) {
    advisories.push({
      key: "approve-without-view",
      title: "Approve without view-all",
      detail:
        "Approvers normally need broad request visibility. Without view_all, review screens may be incomplete or confusing.",
    });
  }

  if (rights.has("autoapprove_jobs") && rights.has("force_dry_run")) {
    advisories.push({
      key: "autoapprove-force-dry-run",
      title: "Auto-approve with force-dry-run",
      detail:
        "Requests may be auto-approved but still forced into dry-run mode. That can be useful for testing, but surprising in production.",
    });
  }

  if (rights.has("manage_user_grants") && rights.has("edit_config")) {
    advisories.push({
      key: "grant-admin-config",
      title: "Grant management and config editing are combined",
      detail:
        "This role can change both user grants and runtime authorization config, which is close to full access-control administration.",
    });
  }

  return advisories;
}

const selectedUserGrantAdvisories = computed(() => {
  const rights = checkedRights(userRightChecks.value);
  for (const right of expandCheckedGroups(userGroupChecks.value)) {
    rights.add(right);
  }
  return collectGrantAdvisories(rights);
});

const selectedAutoGrantAdvisories = computed(() => {
  const rights = checkedRights(autoGrantRightChecks.value);
  for (const right of expandCheckedGroups(autoGrantGroupChecks.value)) {
    rights.add(right);
  }
  return collectGrantAdvisories(rights);
});

const selectedFrameworkGroupAdvisories = computed(() =>
  collectGrantAdvisories(checkedRights(frameworkGroupRightChecks.value))
);

function clearAutoGrantChecks(): void {
  autoGrantGroupChecks.value = Object.fromEntries(
    groupRows.value.map((row) => [row.key, false]),
  );
  autoGrantRightChecks.value = emptyRightChecks();
  autoGrantModuleRightChecks.value = Object.fromEntries(
    autoGrantModuleRightRows.value.map((row) => [row.key, false]),
  );
}

function persistSelectedAutoGrantRoleChecks(): void {
  const role = selectedAutoGrantRole.value;
  const atoms: string[] = [];

  for (const field of groupRows.value) {
    if (autoGrantGroupChecks.value[field.key]) {
      atoms.push(`group:${field.key}`);
    }
  }

  for (const field of userGrantRightFields) {
    if (autoGrantRightChecks.value[field.key]) {
      atoms.push(field.key);
    }
  }

  for (const [atom, checked] of Object.entries(autoGrantModuleRightChecks.value)) {
    if (checked) {
      atoms.push(atom);
    }
  }

  const next = { ...(config.value.ROLE_GRANTS_JSON || {}) };
  if (atoms.length > 0) {
    next[role] = [...new Set(atoms)].sort();
  } else {
    delete next[role];
  }

  config.value.ROLE_GRANTS_JSON = next;
  autoGrantsJsonText.value = JSON.stringify(next, null, 2);
}

function loadSelectedAutoGrantRoleChecks(): void {
  clearAutoGrantChecks();
  const role = selectedAutoGrantRole.value;
  const atoms = config.value.ROLE_GRANTS_JSON?.[role] || [];

  for (const atom of atoms) {
    const normalized = String(atom || "").trim().toLowerCase();
    if (!normalized) continue;

    if (normalized.startsWith("group:")) {
      const groupName = normalized.split(":", 2)[1];
      autoGrantGroupChecks.value[groupName] = true;
      continue;
    }

    if (normalized in autoGrantRightChecks.value) {
      autoGrantRightChecks.value[normalized as GrantRightKey] = true;
      continue;
    }

    if (normalized.startsWith("module:")) {
      autoGrantModuleRightChecks.value[normalized] = true;
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

function onSelectedAutoGrantSourceChange(): void {
  persistSelectedAutoGrantRoleChecks();
  syncSelectedAutoGrantRoleVisibility();
}

function onSelectedAutoGrantProjectChange(): void {
  persistSelectedAutoGrantRoleChecks();
  syncSelectedAutoGrantRoleVisibility();
}

function autoGrantRoleHelp(role: string): string {
  if (role === "authenticated") return "Any logged-in user.";
  if (role === "commons_admin") return "Users in Commons sysop group.";
  if (role === "commons_rollbacker") return "Users in Commons rollbacker group.";
  if (role.startsWith("project:")) {
    const [, project, group] = role.split(":");
    return `Users in ${group || "this group"} on ${project || "this project"}.`;
  }
  if (role.startsWith("global:")) {
    return `Users in the global ${role.slice("global:".length)} group.`;
  }
  return "Custom auto-grant role.";
}

function normalizeRolePart(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

function addAutoGrantRole(): void {
  persistSelectedAutoGrantRoleChecks();
  const group = normalizeRolePart(newAutoGrantGroup.value);
  const project = normalizeRolePart(newAutoGrantProject.value);
  const role = newAutoGrantScope.value === "global"
    ? group ? `global:${group}` : ""
    : project && group ? `project:${project}:${group}` : "";

  if (!role) {
    errorMessage.value = "Enter a project/group or global group before adding an auto-grant role.";
    successMessage.value = "";
    return;
  }

  config.value.ROLE_GRANTS_JSON = {
    ...(config.value.ROLE_GRANTS_JSON || {}),
    [role]: config.value.ROLE_GRANTS_JSON?.[role] || [],
  };
  autoGrantsJsonText.value = JSON.stringify(config.value.ROLE_GRANTS_JSON, null, 2);
  selectedAutoGrantSource.value = newAutoGrantScope.value;
  if (newAutoGrantScope.value === "project") {
    selectedAutoGrantProject.value = role.split(":")[1] || newAutoGrantProject.value;
  }
  selectedAutoGrantRole.value = role;
  newAutoGrantGroup.value = "";
  loadSelectedAutoGrantRoleChecks();
  errorMessage.value = "";
  successMessage.value = `Added auto-grant role ${role}.`;
}

function removeSelectedAutoGrantRole(): void {
  const role = selectedAutoGrantRole.value;
  const next = { ...(config.value.ROLE_GRANTS_JSON || {}) };
  delete next[role];
  config.value.ROLE_GRANTS_JSON = next;
  autoGrantsJsonText.value = JSON.stringify(next, null, 2);
  syncSelectedAutoGrantRoleVisibility();
}

function normalizeFrameworkGroupName(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function clearFrameworkGroupChecks(): void {
  frameworkGroupRightChecks.value = emptyRightChecks();
  frameworkGroupModuleRightChecks.value = Object.fromEntries(
    autoGrantModuleRightRows.value.map((row) => [row.key, false]),
  );
}

function persistSelectedFrameworkGroupChecks(): void {
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  if (!group) return;

  const atoms: string[] = [];
  for (const field of userGrantRightFields) {
    if (frameworkGroupRightChecks.value[field.key]) {
      atoms.push(field.key);
    }
  }
  for (const [atom, checked] of Object.entries(frameworkGroupModuleRightChecks.value)) {
    if (checked) {
      atoms.push(atom);
    }
  }

  config.value.CHUCKBOT_GROUPS_JSON = {
    ...(config.value.CHUCKBOT_GROUPS_JSON || {}),
    [group]: [...new Set(atoms)].sort(),
  };
  groupsJsonText.value = JSON.stringify(config.value.CHUCKBOT_GROUPS_JSON, null, 2);
}

function loadSelectedFrameworkGroupChecks(): void {
  clearFrameworkGroupChecks();
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  const hasOverride = Object.prototype.hasOwnProperty.call(
    config.value.CHUCKBOT_GROUPS_JSON || {},
    group,
  );
  const atoms = hasOverride
    ? config.value.CHUCKBOT_GROUPS_JSON?.[group] || []
    : builtInFrameworkGroupRights[group as GrantGroupKey] || [];

  for (const atom of atoms) {
    const normalized = String(atom || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
    if (!normalized) continue;

    if (normalized in frameworkGroupRightChecks.value) {
      frameworkGroupRightChecks.value[normalized as GrantRightKey] = true;
      continue;
    }

    if (normalized.startsWith("module:")) {
      frameworkGroupModuleRightChecks.value[normalized] = true;
    }
  }
}

function onSelectedFrameworkGroupChange(event: Event): void {
  persistSelectedFrameworkGroupChecks();
  const target = event.target as HTMLSelectElement | null;
  if (!target) return;
  selectedFrameworkGroup.value = target.value;
  loadSelectedFrameworkGroupChecks();
}

function addFrameworkGroup(): void {
  persistSelectedFrameworkGroupChecks();
  const group = normalizeFrameworkGroupName(newFrameworkGroup.value);
  if (!group) {
    errorMessage.value = "Enter a framework group name before adding it.";
    successMessage.value = "";
    return;
  }

  config.value.CHUCKBOT_GROUPS_JSON = {
    ...(config.value.CHUCKBOT_GROUPS_JSON || {}),
    [group]: config.value.CHUCKBOT_GROUPS_JSON?.[group] || [],
  };
  groupsJsonText.value = JSON.stringify(config.value.CHUCKBOT_GROUPS_JSON, null, 2);
  selectedFrameworkGroup.value = group;
  newFrameworkGroup.value = "";
  loadSelectedFrameworkGroupChecks();
  errorMessage.value = "";
  successMessage.value = `Added framework group ${group}.`;
}

function removeSelectedFrameworkGroup(): void {
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  if (userGrantGroupFields.some((field) => field.key === group)) {
    errorMessage.value = "Built-in framework groups cannot be removed, but you can edit their included rights.";
    successMessage.value = "";
    return;
  }

  const next = { ...(config.value.CHUCKBOT_GROUPS_JSON || {}) };
  delete next[group];
  config.value.CHUCKBOT_GROUPS_JSON = next;
  groupsJsonText.value = JSON.stringify(next, null, 2);
  selectedFrameworkGroup.value = frameworkGroupFields.value[0]?.key || "basic";
  loadSelectedFrameworkGroupChecks();
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
  userGroupChecks.value = Object.fromEntries(
    groupRows.value.map((row) => [row.key, false]),
  );

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
  project_groups?: Record<string, string[]>;
  global_groups?: string[];
  commons_groups_refreshed?: boolean;
}): void {
  selectedGrantUser.value = payload.normalized_username;
  userGrantLoaded.value = true;
  clearUserGrantChecks();

  for (const group of payload.groups || []) {
    userGroupChecks.value[group] = true;
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
  projectGroups.value = { ...(payload.project_groups || {}) };
  globalGroups.value = [...(payload.global_groups || [])];
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
    const groups = groupRows.value
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
    CHUCKBOT_GROUPS_JSON: { ...(nextConfig.CHUCKBOT_GROUPS_JSON || {}) },
    RATE_LIMIT_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_JOBS_PER_HOUR || 0),
    RATE_LIMIT_TESTER_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_TESTER_JOBS_PER_HOUR || 0),
  };

  grantsJsonText.value = JSON.stringify(config.value.ROLLBACK_CONTROL_JSON || {}, null, 2);
  groupsJsonText.value = JSON.stringify(config.value.CHUCKBOT_GROUPS_JSON || {}, null, 2);
  autoGrantsJsonText.value = JSON.stringify(config.value.ROLE_GRANTS_JSON || {}, null, 2);
  loadSelectedAutoGrantRoleChecks();
  loadSelectedFrameworkGroupChecks();
}

function parseJsonObjectText(text: string, label: string): Record<string, string[]> {
  const trimmed = text.trim();
  if (!trimmed) return {};

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be an object`);
  }

  return parsed as Record<string, string[]>;
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
    moduleRights.value = response.module_rights || {};
    projectGroupOptions.value = response.project_group_options || {};
    globalGroupOptions.value = response.global_group_options || [];
    loadSelectedAutoGrantRoleChecks();
    loadSelectedFrameworkGroupChecks();
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
    config.value.CHUCKBOT_GROUPS_JSON = parseJsonObjectText(groupsJsonText.value, "Chuckbot groups JSON");
    persistSelectedFrameworkGroupChecks();
    config.value.CHUCKBOT_GROUPS_JSON = parseJsonObjectText(
      groupsJsonText.value,
      "Chuckbot groups JSON",
    );
    config.value.ROLE_GRANTS_JSON = parseJsonObjectText(
      autoGrantsJsonText.value,
      "Auto grants JSON",
    );

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
            placeholder="Search Wikimedia username"
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
          {{ userGrantRefreshing ? "Refreshing..." : "Refresh project rights" }}
        </CdxButton>
      </div>

      <div v-if="userGrantLoaded" class="runtime-rights-columns">
        <div>
          <h4>Project groups (live)</h4>
          <dl class="project-groups-list">
            <template v-for="(groups, project) in projectGroups" :key="project">
              <dt>{{ project }}</dt>
              <dd>
                {{ groups.length ? groups.join(", ") : "No explicit project groups found." }}
                <span v-if="project === 'commons' && commonsGroupsFresh"> (freshly queried)</span>
              </dd>
            </template>
          </dl>
          <h4>Global groups (live)</h4>
          <p class="runtime-config-help">
            {{ globalGroups.length ? globalGroups.join(", ") : "No global groups found." }}
          </p>

          <h4>Automatic eligibility</h4>
          <dl class="implicit-status-list">
            <template v-for="flag in implicitFlagStatusRows" :key="flag.key">
              <dt>{{ flag.label }}</dt>
              <dd>{{ flag.enabled ? "Yes" : "No" }}</dd>
            </template>
          </dl>
        </div>

        <div>
          <h4>Groups you can change</h4>
          <UnifiedTable
            :rows="groupRows"
            :columns="groupColumns"
            row-key="key"
            table-class="runtime-rights-table"
          />

          <ul v-if="selectedUserGrantAdvisories.length" class="grant-advisories">
            <li v-for="advisory in selectedUserGrantAdvisories" :key="advisory.key">
              <strong>{{ advisory.title }}</strong>
              <span>{{ advisory.detail }}</span>
            </li>
          </ul>

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
        <h3>Framework groups by user</h3>
        <p class="runtime-config-help">
          MediaWiki-style user rights storage: usernames map to framework groups,
          and groups provide rights. Prefer editing this through the user rights
          editor above.
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
          Configure eligibility rules from login status, project groups, or global
          groups. This does not change anyone's wiki userrights; it only says who
          receives Chuckbot framework permissions.
        </p>

        <div class="auto-role-builder">
          <label>
            <span>Source</span>
            <select v-model="newAutoGrantScope" :disabled="!canEditConfig || saving">
              <option value="project">Project group</option>
              <option value="global">Global group</option>
            </select>
          </label>
          <label v-if="newAutoGrantScope === 'project'">
            <span>Wiki</span>
            <select
              v-model="newAutoGrantProject"
              :disabled="!canEditConfig || saving"
            >
              <option v-for="project in autoGrantProjects" :key="project" :value="project">
                {{ project }}
              </option>
            </select>
          </label>
          <label>
            <span>Existing wiki group</span>
            <select
              v-if="newAutoGrantGroupOptions.length > 0"
              v-model="newAutoGrantGroup"
              :disabled="!canEditConfig || saving"
            >
              <option value="">Select a group</option>
              <option v-for="group in newAutoGrantGroupOptions" :key="group" :value="group">
                {{ group }}
              </option>
            </select>
            <input
              v-else
              v-model="newAutoGrantGroup"
              :disabled="!canEditConfig || saving"
              placeholder="group name"
              type="text"
              @keyup.enter="addAutoGrantRole"
            >
          </label>
          <CdxButton
            type="button"
            :disabled="!canEditConfig || saving"
            @click="addAutoGrantRole"
          >
            Add role
          </CdxButton>
        </div>

        <div class="auto-role-select-row">
          <label>
            <span>Role source</span>
            <select
              v-model="selectedAutoGrantSource"
              :disabled="!canEditConfig || saving"
              @change="onSelectedAutoGrantSourceChange"
            >
              <option value="project">Project group</option>
              <option value="global">Global group</option>
              <option value="built_in">Authenticated</option>
            </select>
          </label>
          <label v-if="selectedAutoGrantSource === 'project'">
            <span>Wiki</span>
            <select
              v-model="selectedAutoGrantProject"
              :disabled="!canEditConfig || saving"
              @change="onSelectedAutoGrantProjectChange"
            >
              <option v-for="project in autoGrantProjects" :key="project" :value="project">
                {{ project }}
              </option>
            </select>
          </label>
          <label for="auto-grant-role-select">
            <span>Role</span>
          <select
            id="auto-grant-role-select"
            :value="selectedAutoGrantRole"
            :disabled="!canEditConfig || saving"
            @change="onSelectedAutoGrantRoleChange"
          >
            <option v-for="role in filteredAutoGrantRoleFields" :key="role.key" :value="role.key">
              {{ role.label }}
            </option>
          </select>
          </label>
          <CdxButton
            type="button"
            weight="quiet"
            :disabled="!canEditConfig || saving || ['authenticated', 'commons_admin', 'commons_rollbacker'].includes(selectedAutoGrantRole)"
            @click="removeSelectedAutoGrantRole"
          >
            Remove role
          </CdxButton>
        </div>
        <p v-if="filteredAutoGrantRoleFields.length === 0" class="runtime-config-help">
          No auto-grant roles exist for this source yet. Add one above first.
        </p>

        <UnifiedTable
          v-if="filteredAutoGrantRoleFields.length > 0"
          :rows="autoGrantRoleRowsForSelected()"
          :columns="autoGrantRoleColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Framework groups assigned by this rule</h4>
        <UnifiedTable
          :rows="groupRows"
          :columns="autoGroupColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Framework rights assigned by this rule</h4>
        <UnifiedTable
          :rows="rightRows"
          :columns="autoRightColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Module rights assigned by this rule</h4>
        <div v-if="autoGrantModuleRightRows.length === 0" class="runtime-config-help">
          No modules currently declare rights.
        </div>
        <UnifiedTable
          v-else
          :rows="autoGrantModuleRightRows"
          :columns="autoModuleRightColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <ul v-if="selectedAutoGrantAdvisories.length" class="grant-advisories">
          <li v-for="advisory in selectedAutoGrantAdvisories" :key="advisory.key">
            <strong>{{ advisory.title }}</strong>
            <span>{{ advisory.detail }}</span>
          </li>
        </ul>

        <details class="advanced-config-json">
          <summary>Advanced auto grants JSON</summary>
          <p class="runtime-config-help">
            The form above writes this JSON for you. You can still use this for bulk edits.
          </p>
        <textarea
          v-model="autoGrantsJsonText"
          :disabled="!canEditConfig"
          rows="8"
        />
        </details>
      </section>

      <section class="runtime-config-card">
        <h3>Chuckbot framework groups</h3>
        <p class="runtime-config-help">
          Edit framework groups without changing code. These groups are what user
          grants and auto grants attach to.
        </p>

        <div class="framework-group-builder">
          <label>
            <span>New group</span>
            <input
              v-model="newFrameworkGroup"
              :disabled="!canEditConfig || saving"
              placeholder="four_award_operator"
              type="text"
              @keyup.enter="addFrameworkGroup"
            >
          </label>
          <CdxButton
            type="button"
            :disabled="!canEditConfig || saving"
            @click="addFrameworkGroup"
          >
            Add group
          </CdxButton>
        </div>

        <div class="framework-group-select-row">
          <label>
            <span>Group</span>
            <select
              :value="selectedFrameworkGroup"
              :disabled="!canEditConfig || saving"
              @change="onSelectedFrameworkGroupChange"
            >
              <option v-for="group in frameworkGroupFields" :key="group.key" :value="group.key">
                {{ group.label }}
              </option>
            </select>
          </label>
          <CdxButton
            type="button"
            weight="quiet"
            :disabled="!canEditConfig || saving || userGrantGroupFields.some((field) => field.key === selectedFrameworkGroup)"
            @click="removeSelectedFrameworkGroup"
          >
            Remove group
          </CdxButton>
        </div>

        <UnifiedTable
          :rows="frameworkGroupRowsForSelected()"
          :columns="frameworkGroupColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Included rights</h4>
        <UnifiedTable
          :rows="rightRows"
          :columns="frameworkGroupRightColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <h4>Included module rights</h4>
        <div v-if="autoGrantModuleRightRows.length === 0" class="runtime-config-help">
          No modules currently declare rights.
        </div>
        <UnifiedTable
          v-else
          :rows="autoGrantModuleRightRows"
          :columns="frameworkGroupModuleRightColumns"
          row-key="key"
          table-class="runtime-rights-table"
        />

        <ul v-if="selectedFrameworkGroupAdvisories.length" class="grant-advisories">
          <li v-for="advisory in selectedFrameworkGroupAdvisories" :key="advisory.key">
            <strong>{{ advisory.title }}</strong>
            <span>{{ advisory.detail }}</span>
          </li>
        </ul>

        <details class="advanced-config-json">
          <summary>Advanced framework groups JSON</summary>
          <p class="runtime-config-help">
            The group editor above writes this JSON for you. You can still use this for bulk edits.
          </p>
          <textarea
            v-model="groupsJsonText"
            :disabled="!canEditConfig"
            rows="10"
          />
        </details>
      </section>

      <section class="runtime-config-card">
        <h3>Module-declared rights</h3>
        <p class="runtime-config-help">
          Modules publish their framework rights here. Grant them with atoms like
          <code>module:four_award:run_jobs</code>; project/global roles only decide
          who receives those atoms.
        </p>
        <div v-if="Object.keys(moduleRights).length === 0" class="runtime-config-help">
          No modules currently declare rights.
        </div>
        <dl v-else class="module-rights-list">
          <template v-for="(rights, moduleName) in moduleRights" :key="moduleName">
            <dt>{{ moduleName }}</dt>
            <dd>
              <code v-for="right in rights" :key="right">module:{{ moduleName }}:{{ right }}</code>
            </dd>
          </template>
        </dl>
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
