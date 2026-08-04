<script setup lang="ts">
/**
 * Runtime authorization configuration and user-grant editor.
 *
 * This surface maintains several synchronized views of the same server config:
 * guided checkboxes, human-readable summaries, and bulk JSON editors. User grants
 * have their own immediate-save endpoint; group/role/rate-limit edits remain local
 * until the page-level save. Client capability flags only hide or disable controls
 * and never replace authorization in either API.
 */
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
type ConfigTabKey = "users" | "groups" | "auto_grants" | "module_rights" | "advanced";

interface GrantAdvisory {
  key: string;
  title: string;
  detail: string;
}

// These field catalogs are the UI schema: labels, help text, and table ordering.
// The API's recognized atoms and authorization checks remain authoritative.
const userGrantGroupFields: Array<{ key: GrantGroupKey; label: string; help: string }> = [
  { key: "basic", label: "Basic submitter", help: "Can submit and manage their own rollback queue jobs." },
  { key: "read_only", label: "Read only", help: "Can only view their own jobs." },
  { key: "tester", label: "Tester", help: "Can use rollback tools with tester rate limits and no cross-user moderation." },
  { key: "viewer", label: "Job viewer", help: "Can view all jobs." },
  {
    key: "rollbacker",
    label: "Rollback requester",
    help: "Can submit rollback requests for diff and account endpoints.",
  },
  {
    key: "rollbacker_dry_run",
    label: "Dry-run rollback requester",
    help: "Rollbacker rights with dry-run-only enforcement.",
  },
  { key: "batch_runner", label: "Batch requester", help: "Can submit batch rollback requests." },
  {
    key: "jobs_moderator",
    label: "Job moderator",
    help: "Can approve/review jobs and perform moderation actions.",
  },
  { key: "config_editor", label: "Config editor", help: "Can edit runtime access configuration." },
  { key: "rights_manager", label: "Rights manager", help: "Can manage framework groups for users." },
  {
    key: "module_operator",
    label: "Module operator",
    help: "Full authority over every module, including sensitive live-apply rights.",
  },
  {
    key: "admin",
    label: "Administrator",
    help: "Broad rollback, jobs, config, user-grant, and full module authority.",
  },
];

// Built-in expansion supports effective-right previews and supplies defaults when
// a built-in framework group has no runtime override.
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

// Direct rights are grouped for presentation only; submitted payloads are flat atoms.
const userGrantRightSections: Array<{
  title: string;
  fields: Array<{ key: GrantRightKey; label: string; help: string }>;
}> = [
  {
    title: "Rollback rights",
    fields: [
      { key: "rollback_diff", label: "Rollback from diff", help: "Use rollback-from-diff." },
      {
        key: "rollback_account",
        label: "Rollback by account",
        help: "Use rollback-from-account.",
      },
      { key: "rollback_batch", label: "Batch rollback", help: "Submit batch rollback requests." },
      {
        key: "rollback_diff_dry_run_only",
        label: "Dry-run only",
        help: "Force diff/account rollback requests to preview mode.",
      },
      {
        key: "estop_rollback",
        label: "Emergency-stop rollback",
        help: "Emergency-stop the bundled rollback module.",
      },
    ],
  },
  {
    title: "Jobs rights",
    fields: [
      { key: "approve_jobs", label: "Approve jobs", help: "Approve or reject pending rollback requests." },
      {
        key: "autoapprove_jobs",
        label: "Auto-approve eligible jobs",
        help: "Allow test-mode requests to auto-approve when enabled.",
      },
      { key: "force_dry_run", label: "Force dry run", help: "Force pending requests to preview mode." },
      { key: "cancel_any", label: "Cancel others' jobs", help: "Cancel regular users' jobs." },
      { key: "retry_any", label: "Retry others' jobs", help: "Retry jobs across users." },
    ],
  },
  {
    title: "Administration rights",
    fields: [
      { key: "view_all", label: "View all jobs", help: "Read every user's jobs." },
      { key: "write", label: "Submit rollback jobs", help: "Submit standard rollback queue jobs." },
      { key: "edit_config", label: "Edit config", help: "Edit runtime authz config values." },
      {
        key: "manage_user_grants",
        label: "Manage user rights",
        help: "Manage user-specific rights and framework groups.",
      },
      {
        key: "manage_modules",
        label: "Manage modules",
        help: "Full authority over every module right, including sensitive live actions.",
      },
      { key: "run_module_jobs", label: "Run module jobs", help: "Run or restart module jobs." },
      { key: "edit_module_config", label: "Edit module config", help: "Edit non-secret module configuration." },
    ],
  },
];

const userGrantRightFields = userGrantRightSections.flatMap((section) => section.fields);

const implicitFlagFields: Array<{ key: ImplicitFlagKey; label: string }> = [
  { key: "authenticated", label: "Logged in" },
  { key: "commons_admin", label: "Commons administrator" },
  { key: "commons_rollbacker", label: "Commons rollbacker" },
];

const baseAutoGrantRoleFields: Array<{ key: AutoGrantRoleKey; label: string; help: string }> = [
  { key: "authenticated", label: "Any logged-in user", help: "Any logged-in user." },
  { key: "commons_admin", label: "Commons administrators", help: "Users in Commons sysop group." },
  {
    key: "commons_rollbacker",
    label: "Commons rollbackers",
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

const groupLabelByKey = new Map(userGrantGroupFields.map((field) => [field.key, field.label]));
const rightLabelByKey = new Map(userGrantRightFields.map((field) => [field.key, field.label]));

/** Turn persisted atom syntax into a readable fallback label. */
function titleCaseAtom(value: string): string {
  return value
    .replace(/^module:/, "")
    .replace(/[_:-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Prefer product spelling for known modules, with a generic atom fallback. */
function friendlyModuleLabel(moduleName: string): string {
  if (moduleName === "four_award") return "Four Award";
  return titleCaseAtom(moduleName);
}

/** Resolve a framework group label, including runtime-defined groups. */
function friendlyGroupLabel(group: string): string {
  return groupLabelByKey.get(group as GrantGroupKey) || titleCaseAtom(group);
}

/** Resolve a framework right label, including forward-compatible unknown atoms. */
function friendlyRightLabel(right: string): string {
  return rightLabelByKey.get(right as GrantRightKey) || titleCaseAtom(right);
}

/** Explain built-in, project, and global implicit role identifiers. */
function friendlyRoleLabel(role: string): string {
  if (role === "authenticated") return "Any logged-in user";
  if (role === "commons_admin") return "Commons administrators";
  if (role === "commons_rollbacker") return "Commons rollbackers";
  if (role.startsWith("project:")) {
    const [, project, group] = role.split(":");
    return `${titleCaseAtom(group || "group")} on ${project || "project"}`;
  }
  if (role.startsWith("global:")) {
    return `Global ${titleCaseAtom(role.slice("global:".length))}`;
  }
  return titleCaseAtom(role);
}

/** Format a ``module:<name>:<right>`` atom without changing its stored value. */
function friendlyModuleRightLabel(atom: string): string {
  const parts = atom.split(":");
  if (parts.length === 3 && parts[0] === "module") {
    return `${friendlyModuleLabel(parts[1])}: ${friendlyRightLabel(parts[2])}`;
  }
  return titleCaseAtom(atom);
}

/** Route any persisted grant atom to the appropriate display formatter. */
function friendlyAtomLabel(atom: string): string {
  if (atom.startsWith("group:")) {
    return `Group: ${friendlyGroupLabel(atom.slice("group:".length))}`;
  }
  if (atom.startsWith("module:")) {
    return friendlyModuleRightLabel(atom);
  }
  return friendlyRightLabel(atom);
}

/**
 * Parse server-rendered bootstrap hints defensively.
 *
 * The subsequent config fetch replaces these provisional capabilities with the
 * endpoint's current ``can_edit`` and ``can_manage_user_grants`` values.
 */
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

// Page lifecycle and server-advertised editor gates. The two permissions are
// distinct after load even though the bootstrap uses edit-config as a fallback.
const loading = ref(true);
const saving = ref(false);
const errorMessage = ref("");
const successMessage = ref("");
const canEditConfig = ref(initialProps.can_edit_config);
const canManageUserGrants = ref(initialProps.can_edit_config);
const activeConfigTab = ref<ConfigTabKey>("users");
const moduleRights = ref<Record<string, string[]>>({});
const projectGroupOptions = ref<Record<string, string[]>>({});
const globalGroupOptions = ref<string[]>([]);

// Canonical in-memory config submitted by saveConfig. Object members are copied
// on load so structured editors never mutate a retained response object.
const config = ref<RuntimeAuthzConfig>({
  ROLLBACK_CONTROL_JSON: {},
  ROLE_GRANTS_JSON: {
    commons_admin: ["group:basic"],
    commons_rollbacker: ["group:basic"],
  },
  CHUCKBOT_GROUPS_JSON: {},
  CHUCKBOT_GROUP_DESCRIPTIONS_JSON: {},
  RATE_LIMIT_JOBS_PER_HOUR: 0,
  RATE_LIMIT_TESTER_JOBS_PER_HOUR: 0,
});

// Advanced JSON text is intentionally separate from ``config`` so users may hold
// incomplete or invalid text while editing; parsing happens at the save boundary.
const grantsJsonText = ref("{}");
const groupsJsonText = ref("{}");
const groupDescriptionsJsonText = ref("{}");
const autoGrantsJsonText = ref("{}");

// Username suggestions are request-versioned so a slow old lookup cannot replace
// results for newer input.
const userSearchLookupItems = ref<Array<{ label: string; value: string }>>([]);
const userSearchSelected = ref<string | number | null>(null);
const userSearchInputValue = ref("");
const userSearchRequestId = ref(0);

// User-grant state comes from a separate per-user endpoint and includes live wiki
// membership snapshots used to explain implicit grant eligibility.
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
const newFrameworkGroupDescription = ref("");
const selectedFrameworkGroupDescription = ref("");

// Implicit flags are server-derived, read-only facts; saving explicit grants does
// not modify Wikimedia project or global group membership.
const implicitFlags = ref<Record<ImplicitFlagKey, boolean>>({
  authenticated: false,
  commons_admin: false,
  commons_rollbacker: false,
});

/** Return a fresh built-in group selection map for an editor projection. */
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

/** Return a fresh direct-right selection map. */
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

// Each editor owns an independent checkbox projection. Changing an auto-grant
// role or framework group must not alter the currently loaded user's draft.
const userGroupChecks = ref<Record<string, boolean>>(emptyGroupChecks());
const userRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const autoGrantGroupChecks = ref<Record<string, boolean>>(emptyGroupChecks());
const autoGrantRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const autoGrantModuleRightChecks = ref<Record<string, boolean>>({});
const frameworkGroupRightChecks = ref<Record<GrantRightKey, boolean>>(emptyRightChecks());
const frameworkGroupModuleRightChecks = ref<Record<string, boolean>>({});

// Table rows combine static right metadata with runtime-defined roles/groups so
// configured identities remain visible alongside the built-in catalogs.
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
      label: friendlyRoleLabel(role),
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
  const descriptions = config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {};
  const groups = new Set<string>([
    ...userGrantGroupFields.map((field) => field.key),
    ...configured,
  ]);
  const baseByKey = new Map(userGrantGroupFields.map((field) => [field.key, field]));

  return [...groups].sort().map((group) => {
    const base = baseByKey.get(group as GrantGroupKey);
    return {
      key: group,
      label: base?.label || friendlyGroupLabel(group),
      help: descriptions[group] || base?.help || "Custom framework group.",
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

// Checkbox columns share capability-aware disabled callbacks. Disabling a control
// improves the editor UX; the corresponding API still enforces the same right.
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

/** Return the presentation rows belonging to one direct-right section. */
function rightsRowsForSection(sectionTitle: string): ToggleFieldRow<GrantRightKey>[] {
  return filterToggleRowsBySection(rightRows.value, sectionTitle);
}

/** Limit the role summary table to the currently edited implicit role. */
function autoGrantRoleRowsForSelected(): ToggleFieldRow<AutoGrantRoleKey>[] {
  return autoGrantRoleRows.value.filter((row) => row.key === selectedAutoGrantRole.value);
}

/** Test whether a stored role belongs to the selected built-in/project/global filter. */
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

/** Select the first role visible under the active source filter, if one exists. */
function selectFirstVisibleAutoGrantRole(): void {
  const first = filteredAutoGrantRoleFields.value[0]?.key;
  if (!first) return;
  selectedAutoGrantRole.value = first;
  loadSelectedAutoGrantRoleChecks();
}

/** Keep selection valid when source/project filtering removes the current role. */
function syncSelectedAutoGrantRoleVisibility(): void {
  if (!filteredAutoGrantRoleFields.value.some((field) => field.key === selectedAutoGrantRole.value)) {
    selectFirstVisibleAutoGrantRole();
  }
}

// Module rights are declared by modules at runtime and stored as fully qualified
// atoms so names cannot collide with framework-global rights.
const autoGrantModuleRightRows = computed(() => {
  const rows: Array<{ key: string; label: string; help: string; moduleName: string }> = [];
  for (const [moduleName, rights] of Object.entries(moduleRights.value)) {
    for (const right of rights) {
      rows.push({
        key: `module:${moduleName}:${right}`,
        label: friendlyModuleRightLabel(`module:${moduleName}:${right}`),
        help: `Grant ${friendlyRightLabel(right)} for ${friendlyModuleLabel(moduleName)}.`,
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

/** Return the one-row identity table for the framework group being edited. */
function frameworkGroupRowsForSelected(): ToggleFieldRow<string>[] {
  return frameworkGroupRows.value.filter((row) => row.key === selectedFrameworkGroup.value);
}

/** Convert direct-right checkboxes into a set for union/diagnostic operations. */
function checkedRights(checks: Record<GrantRightKey, boolean>): Set<GrantRightKey> {
  return new Set(
    userGrantRightFields
      .filter((field) => checks[field.key])
      .map((field) => field.key),
  );
}

/** Expand selected built-in groups into their effective global framework rights. */
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

/**
 * Produce non-blocking warnings for combinations that deserve human review.
 * Advisories explain risk only; they neither grant rights nor prevent submission.
 */
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
        "Approvers normally need broad request visibility. Without View all jobs, review screens may be incomplete or confusing.",
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

// The loaded-user summaries deliberately separate stored group/direct atoms from
// their client-side effective-right expansion so reviewers can inspect both.
const selectedUserGroups = computed(() =>
  groupRows.value
    .filter((field) => userGroupChecks.value[field.key])
    .map((field) => field.key)
    .sort()
);

const selectedUserDirectRights = computed(() =>
  userGrantRightFields
    .filter((field) => userRightChecks.value[field.key])
    .map((field) => field.key)
    .sort()
);

const selectedUserEffectiveRights = computed(() => {
  const rights = checkedRights(userRightChecks.value);
  for (const right of expandCheckedGroups(userGroupChecks.value)) {
    rights.add(right);
  }
  return [...rights].sort();
});

const selectedUserGrantAtomsPreview = computed(() => [
  ...selectedUserGroups.value.map((group) => `group:${group}`),
  ...selectedUserDirectRights.value,
]);

/** Format a readable group list while retaining a meaningful empty state. */
function summarizeGroups(values: string[], emptyText: string): string {
  return values.length ? values.map(friendlyGroupLabel).join(", ") : emptyText;
}

/** Format a readable right list while retaining a meaningful empty state. */
function summarizeRights(values: string[], emptyText: string): string {
  return values.length ? values.map(friendlyRightLabel).join(", ") : emptyText;
}

/** Reset all projections before loading another role's stored atoms. */
function clearAutoGrantChecks(): void {
  autoGrantGroupChecks.value = Object.fromEntries(
    groupRows.value.map((row) => [row.key, false]),
  );
  autoGrantRightChecks.value = emptyRightChecks();
  autoGrantModuleRightChecks.value = Object.fromEntries(
    autoGrantModuleRightRows.value.map((row) => [row.key, false]),
  );
}

/**
 * Materialize the current role checkboxes into ``ROLE_GRANTS_JSON`` and its text
 * mirror. This is local draft persistence; saveConfig performs the API write.
 */
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

/** Rebuild auto-grant checkbox projections from the selected role's atom list. */
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

/** Preserve the previous role draft before switching the editor projection. */
function onSelectedAutoGrantRoleChange(event: Event): void {
  persistSelectedAutoGrantRoleChecks();
  const target = event.target as HTMLSelectElement | null;
  if (!target) return;
  selectedAutoGrantRole.value = target.value as AutoGrantRoleKey;
  loadSelectedAutoGrantRoleChecks();
}

/** Preserve the current draft, then repair selection after changing source type. */
function onSelectedAutoGrantSourceChange(): void {
  persistSelectedAutoGrantRoleChecks();
  syncSelectedAutoGrantRoleVisibility();
}

/** Preserve the current draft, then repair selection after changing project. */
function onSelectedAutoGrantProjectChange(): void {
  persistSelectedAutoGrantRoleChecks();
  syncSelectedAutoGrantRoleVisibility();
}

/** Describe the live identity source represented by an implicit role. */
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

/** Canonicalize user-entered role components for persisted atom syntax. */
function normalizeRolePart(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

/** Add an empty project/global role to the local config draft and select it. */
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
  successMessage.value = `Added auto-grant role ${friendlyRoleLabel(role)}.`;
}

/** Remove the selected custom role from the local config draft. */
function removeSelectedAutoGrantRole(): void {
  const role = selectedAutoGrantRole.value;
  const next = { ...(config.value.ROLE_GRANTS_JSON || {}) };
  delete next[role];
  config.value.ROLE_GRANTS_JSON = next;
  autoGrantsJsonText.value = JSON.stringify(next, null, 2);
  syncSelectedAutoGrantRoleVisibility();
}

/** Canonicalize a user-entered framework group name for persisted keys. */
function normalizeFrameworkGroupName(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

/** Built-ins may be overridden but cannot be removed from the UI catalog. */
function frameworkGroupIsBuiltIn(group: string): boolean {
  return userGrantGroupFields.some((field) => field.key === group);
}

/** Mirror one custom description into the config draft and Advanced JSON text. */
function persistSelectedFrameworkGroupDescription(): void {
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  if (!group || frameworkGroupIsBuiltIn(group)) return;

  const descriptions = {
    ...(config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {}),
  };
  const description = selectedFrameworkGroupDescription.value.trim();
  if (description) {
    descriptions[group] = description;
  } else {
    delete descriptions[group];
  }
  config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON = descriptions;
  groupDescriptionsJsonText.value = JSON.stringify(descriptions, null, 2);
}

/** Reset global and module-right projections before loading another group. */
function clearFrameworkGroupChecks(): void {
  frameworkGroupRightChecks.value = emptyRightChecks();
  frameworkGroupModuleRightChecks.value = Object.fromEntries(
    autoGrantModuleRightRows.value.map((row) => [row.key, false]),
  );
}

/**
 * Materialize the selected group's checkbox and description projections into the
 * local config/JSON mirrors. The page-level save performs the server mutation.
 */
function persistSelectedFrameworkGroupChecks(): void {
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  if (!group) return;
  persistSelectedFrameworkGroupDescription();

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

/** Load a runtime override, or built-in defaults when no override exists. */
function loadSelectedFrameworkGroupChecks(): void {
  clearFrameworkGroupChecks();
  const group = normalizeFrameworkGroupName(String(selectedFrameworkGroup.value));
  selectedFrameworkGroupDescription.value =
    config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON?.[group] || "";
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

/** Preserve the previous group draft before switching the editor projection. */
function onSelectedFrameworkGroupChange(event: Event): void {
  persistSelectedFrameworkGroupChecks();
  const target = event.target as HTMLSelectElement | null;
  if (!target) return;
  selectedFrameworkGroup.value = target.value;
  loadSelectedFrameworkGroupChecks();
}

/** Add and select an empty custom framework group in the local config draft. */
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
  if (newFrameworkGroupDescription.value.trim()) {
    config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON = {
      ...(config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {}),
      [group]: newFrameworkGroupDescription.value.trim(),
    };
    groupDescriptionsJsonText.value = JSON.stringify(
      config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON,
      null,
      2,
    );
  }
  groupsJsonText.value = JSON.stringify(config.value.CHUCKBOT_GROUPS_JSON, null, 2);
  selectedFrameworkGroup.value = group;
  newFrameworkGroup.value = "";
  newFrameworkGroupDescription.value = "";
  loadSelectedFrameworkGroupChecks();
  errorMessage.value = "";
  successMessage.value = `Added framework group ${friendlyGroupLabel(group)}.`;
}

/** Remove a custom group and description; built-in catalog entries are retained. */
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
  const descriptions = { ...(config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {}) };
  delete descriptions[group];
  config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON = descriptions;
  groupsJsonText.value = JSON.stringify(next, null, 2);
  groupDescriptionsJsonText.value = JSON.stringify(descriptions, null, 2);
  selectedFrameworkGroup.value = frameworkGroupFields.value[0]?.key || "basic";
  loadSelectedFrameworkGroupChecks();
}

/** Clamp rate-limit fields to non-negative integers before submission. */
function onNumberInput(key: NumberConfigKey, event: Event): void {
  const target = event.target as HTMLInputElement | null;
  if (!target) return;

  const parsed = Number.parseInt(target.value || "0", 10);
  config.value[key] = Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
}

/**
 * Fetch username suggestions with a monotonically increasing request token.
 * Only the response matching the newest input is allowed to update the menu.
 */
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

/** Clear explicit group/right projections without changing live implicit flags. */
function clearUserGrantChecks(): void {
  userGroupChecks.value = Object.fromEntries(
    groupRows.value.map((row) => [row.key, false]),
  );

  for (const field of userGrantRightFields) {
    userRightChecks.value[field.key] = false;
  }
}

/**
 * Apply one normalized user-grant response to guided controls and JSON mirrors.
 * Project/global memberships are displayed as read-only evidence from the server.
 */
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

/**
 * Resolve the selected or typed identity and fetch current explicit/implicit rights.
 * Explicit load clicks are not request-versioned, so if callers overlap them the
 * last response to finish becomes the selected user.
 */
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

/** Re-query live wiki memberships for the already normalized selected identity. */
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

/**
 * Persist one user's explicit groups and direct rights through the dedicated API.
 * The Manage user rights capability disables this path in the UI; the endpoint is
 * still the authoritative authorization and identity-normalization boundary.
 */
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

/**
 * Replace the canonical server snapshot, regenerate every Advanced JSON mirror,
 * and rehydrate the currently selected guided editor projections.
 */
function applyServerConfig(nextConfig: RuntimeAuthzConfig): void {
  config.value = {
    ...nextConfig,
    ROLLBACK_CONTROL_JSON: { ...(nextConfig.ROLLBACK_CONTROL_JSON || {}) },
    ROLE_GRANTS_JSON: { ...(nextConfig.ROLE_GRANTS_JSON || {}) },
    CHUCKBOT_GROUPS_JSON: { ...(nextConfig.CHUCKBOT_GROUPS_JSON || {}) },
    CHUCKBOT_GROUP_DESCRIPTIONS_JSON: {
      ...(nextConfig.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {}),
    },
    RATE_LIMIT_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_JOBS_PER_HOUR || 0),
    RATE_LIMIT_TESTER_JOBS_PER_HOUR: Number(nextConfig.RATE_LIMIT_TESTER_JOBS_PER_HOUR || 0),
  };

  grantsJsonText.value = JSON.stringify(config.value.ROLLBACK_CONTROL_JSON || {}, null, 2);
  groupsJsonText.value = JSON.stringify(config.value.CHUCKBOT_GROUPS_JSON || {}, null, 2);
  groupDescriptionsJsonText.value = JSON.stringify(
    config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON || {},
    null,
    2,
  );
  autoGrantsJsonText.value = JSON.stringify(config.value.ROLE_GRANTS_JSON || {}, null, 2);
  loadSelectedAutoGrantRoleChecks();
  loadSelectedFrameworkGroupChecks();
}

/** Parse an object-valued JSON editor used for atom-array maps. */
function parseJsonObjectText(text: string, label: string): Record<string, string[]> {
  const trimmed = text.trim();
  if (!trimmed) return {};

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be an object`);
  }

  return parsed as Record<string, string[]>;
}

/** Parse and string-normalize the custom framework-group description map. */
function parseJsonStringMapText(text: string, label: string): Record<string, string> {
  const trimmed = text.trim();
  if (!trimmed) return {};

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be an object`);
  }

  return Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>).map(([key, value]) => [
      key,
      String(value || ""),
    ]),
  );
}

/** Parse the bulk per-user grant map while preserving atom arrays for the API. */
function parseUserGrantsJsonText(): Record<string, string[]> {
  const trimmed = grantsJsonText.value.trim();
  if (!trimmed) return {};

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("User-centric grants JSON must be an object");
  }

  return parsed as Record<string, string[]>;
}

/**
 * Fetch the current config, rights catalogs, and independent editor capabilities.
 * Bootstrap permissions are replaced only after this authoritative read succeeds.
 */
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

/**
 * Commit all structured drafts into their JSON mirrors, parse every bulk editor,
 * then submit one coherent runtime config snapshot. Invalid JSON aborts the write.
 * The edit-config API repeats authorization regardless of the client-side gate.
 */
async function saveConfig(): Promise<void> {
  if (!canEditConfig.value) return;

  saving.value = true;
  errorMessage.value = "";
  successMessage.value = "";

  try {
    const parsedUserGrants = parseUserGrantsJsonText();
    config.value.ROLLBACK_CONTROL_JSON = parsedUserGrants;
    persistSelectedAutoGrantRoleChecks();
    persistSelectedFrameworkGroupChecks();
    config.value.CHUCKBOT_GROUPS_JSON = parseJsonObjectText(
      groupsJsonText.value,
      "Chuckbot groups JSON",
    );
    config.value.CHUCKBOT_GROUP_DESCRIPTIONS_JSON = parseJsonStringMapText(
      groupDescriptionsJsonText.value,
      "Chuckbot group descriptions JSON",
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

// Initial load hydrates both structured editors before any save is possible.
onMounted(() => {
  void loadConfig();
});
</script>

<template>
  <div class="container runtime-config-container">
    <!-- Capability notices describe editor affordances; API authz remains authoritative. -->
    <CdxMessage v-if="!canEditConfig" type="warning" class="top-message">
      You can view runtime settings, but only chuckbot can save changes.
    </CdxMessage>

    <CdxMessage
      v-if="!canManageUserGrants"
      type="warning"
      class="top-message"
    >
      You can view grants, but need Manage user rights to edit user-specific grants.
    </CdxMessage>

    <CdxMessage v-if="errorMessage" type="error" class="top-message">
      {{ errorMessage }}
    </CdxMessage>

    <CdxMessage v-if="successMessage" type="success" class="top-message">
      {{ successMessage }}
    </CdxMessage>

    <div v-if="loading">Loading runtime config...</div>

    <!-- Tabs partition one shared config draft; changing tabs does not save it. -->
    <div
      v-if="!loading"
      class="runtime-tablist runtime-config-level-tabs"
      role="tablist"
      aria-label="Runtime config sections"
    >
      <button
        type="button"
        :class="{ 'is-active': activeConfigTab === 'users' }"
        @click="activeConfigTab = 'users'"
      >
        User grants
      </button>
      <button
        type="button"
        :class="{ 'is-active': activeConfigTab === 'groups' }"
        @click="activeConfigTab = 'groups'"
      >
        Framework groups
      </button>
      <button
        type="button"
        :class="{ 'is-active': activeConfigTab === 'auto_grants' }"
        @click="activeConfigTab = 'auto_grants'"
      >
        Wiki auto-grants
      </button>
      <button
        type="button"
        :class="{ 'is-active': activeConfigTab === 'module_rights' }"
        @click="activeConfigTab = 'module_rights'"
      >
        Module grant list
      </button>
      <button
        type="button"
        :class="{ 'is-active': activeConfigTab === 'advanced' }"
        @click="activeConfigTab = 'advanced'"
      >
        Advanced JSON
      </button>
    </div>

    <!-- User grants use their own load/save endpoint and separate permission gate. -->
    <section
      v-if="!loading && activeConfigTab === 'users'"
      class="runtime-config-card runtime-rights-editor"
    >
      <h3>User rights editor</h3>
      <p class="runtime-config-help">
        Start here for normal access changes. Load a user, pick framework groups,
        review the effective rights, then save. Use direct rights only when no
        group matches the job.
      </p>
      <ol class="rights-flow">
        <li><strong>Load</strong><span>Find the Wikimedia account and refresh live wiki groups.</span></li>
        <li><strong>Grant</strong><span>Prefer framework groups; they bundle common permissions.</span></li>
        <li><strong>Review</strong><span>Check the effective rights summary before saving.</span></li>
      </ol>

      <!-- Search suggestions are stale-response protected; loading resolves the identity server-side. -->
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
          <h4>{{ selectedGrantUser }}</h4>
          <p class="runtime-config-help">
            Live wiki groups are read-only here. They may trigger auto grants, but
            they are not changed by saving Chuckbot framework rights.
          </p>

          <!-- Live Wikimedia membership is evidence for auto grants, not editable state. -->
          <h4>Live wiki groups</h4>
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

          <h4>Automatic grant eligibility</h4>
          <dl class="implicit-status-list">
            <template v-for="flag in implicitFlagStatusRows" :key="flag.key">
              <dt>{{ flag.label }}</dt>
              <dd>{{ flag.enabled ? "Yes" : "No" }}</dd>
            </template>
          </dl>

          <!-- Stored atoms and expanded effective rights are shown separately for review. -->
          <section class="rights-summary-card" aria-label="Selected user rights summary">
            <h4>What will be saved</h4>
            <dl>
              <dt>Framework groups</dt>
              <dd>{{ summarizeGroups(selectedUserGroups, "No explicit groups selected.") }}</dd>
              <dt>Direct rights</dt>
              <dd>{{ summarizeRights(selectedUserDirectRights, "No direct rights selected.") }}</dd>
              <dt>Effective rights</dt>
              <dd>{{ summarizeRights(selectedUserEffectiveRights, "No framework rights selected.") }}</dd>
              <dt>Saved permissions</dt>
              <dd>
                <span v-if="selectedUserGrantAtomsPreview.length" class="atom-chip-list">
                  <span
                    v-for="atom in selectedUserGrantAtomsPreview"
                    :key="atom"
                    class="atom-chip"
                  >
                    <span>{{ friendlyAtomLabel(atom) }}</span>
                    <code>{{ atom }}</code>
                  </span>
                </span>
                <span v-else>No permissions will be stored for this user.</span>
              </dd>
            </dl>
          </section>
        </div>

        <div>
          <!-- Framework groups are preferred; direct rights remain an explicit advanced path. -->
          <h4>Recommended: framework groups</h4>
          <p class="runtime-config-help">
            Groups are easier to audit than one-off rights. Most users should
            only need one or two of these.
          </p>
          <UnifiedTable
            :rows="groupRows"
            :columns="groupColumns"
            row-key="key"
            table-class="runtime-rights-table"
          />

          <details class="advanced-config-json">
            <summary>Advanced direct rights</summary>
            <p class="runtime-config-help">
              Direct rights are saved on this user only. Prefer editing a group
              when several people need the same capability.
            </p>
            <section
              v-for="section in userGrantRightSections"
              :key="section.title"
              class="rights-section"
            >
              <h5>{{ section.title }}</h5>
              <UnifiedTable
                :rows="rightsRowsForSection(section.title)"
                :columns="rightColumns"
                row-key="key"
                table-class="runtime-rights-table"
              />
            </section>
          </details>

          <!-- Advisories are informational and never silently rewrite the selected rights. -->
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
              {{ userGrantSaving ? "Saving..." : "Save user rights" }}
            </CdxButton>
          </div>
        </div>
      </div>
    </section>

    <!-- Remaining tabs edit the shared runtime config and save together at page level. -->
    <section
      v-if="!loading && activeConfigTab !== 'users'"
      class="runtime-config-card runtime-management-panel"
    >
      <!-- Framework group forms project into CHUCKBOT_GROUPS_JSON and descriptions. -->
      <section v-if="activeConfigTab === 'groups'" class="runtime-management-section">
        <h3>Chuckbot framework groups</h3>
        <p class="runtime-config-help">
          Edit framework groups without changing code. These are the reusable
          bundles users and wiki auto-grants attach to.
        </p>

        <div class="framework-group-builder">
          <label>
            <span>New group</span>
            <input
              v-model="newFrameworkGroup"
              :disabled="!canEditConfig || saving"
              placeholder="Four Award operator"
              type="text"
              @keyup.enter="addFrameworkGroup"
            >
          </label>
          <label>
            <span>Description</span>
            <input
              v-model="newFrameworkGroupDescription"
              :disabled="!canEditConfig || saving"
              placeholder="Can run and review Four Award jobs"
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
          <label>
            <span>Description</span>
            <input
              v-model="selectedFrameworkGroupDescription"
              :disabled="!canEditConfig || saving || frameworkGroupIsBuiltIn(String(selectedFrameworkGroup))"
              placeholder="Custom group description"
              type="text"
              @input="persistSelectedFrameworkGroupDescription"
            >
          </label>
          <CdxButton
            type="button"
            weight="quiet"
            :disabled="!canEditConfig || saving || frameworkGroupIsBuiltIn(String(selectedFrameworkGroup))"
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
      </section>

      <!-- Auto-grant roles map external identity facts to internal grant atoms. -->
      <section v-if="activeConfigTab === 'auto_grants'" class="runtime-management-section">
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

      </section>

      <!-- Module atoms are a read-only catalog populated by registered modules. -->
      <section v-if="activeConfigTab === 'module_rights'" class="runtime-management-section">
        <h3>Module-declared rights</h3>
        <p class="runtime-config-help">
          Modules publish their framework rights here. Project/global roles only
          decide who receives those rights.
        </p>
        <div v-if="Object.keys(moduleRights).length === 0" class="runtime-config-help">
          No modules currently declare rights.
        </div>
        <dl v-else class="module-rights-list">
          <template v-for="(rights, moduleName) in moduleRights" :key="moduleName">
            <dt>{{ friendlyModuleLabel(moduleName) }}</dt>
            <dd>
              <span
                v-for="right in rights"
                :key="right"
                class="atom-chip"
              >
                <span>{{ friendlyModuleRightLabel(`module:${moduleName}:${right}`) }}</span>
                <code>module:{{ moduleName }}:{{ right }}</code>
              </span>
            </dd>
          </template>
        </dl>
      </section>

      <!-- Bulk editors intentionally allow invalid intermediate text until Save validates it. -->
      <section v-if="activeConfigTab === 'advanced'" class="runtime-management-section">
        <h3>Advanced configuration</h3>
        <p class="runtime-config-help">
          These controls are for bulk cleanup, migration, and rate-limit changes.
          Day-to-day user grants and group edits should use the forms above.
        </p>

        <div class="runtime-number-grid">
          <label v-for="field in numberFields" :key="field.key" class="runtime-number-field">
            <span>{{ field.label }}</span>
            <p class="runtime-config-help">{{ field.help }}</p>
            <input
              type="number"
              min="0"
              :disabled="!canEditConfig"
              :value="config[field.key]"
              @input="(event) => onNumberInput(field.key, event)"
            />
          </label>
        </div>

        <details class="advanced-config-json">
          <summary>Bulk user grants JSON</summary>
          <textarea
            v-model="grantsJsonText"
            :disabled="!canEditConfig"
            rows="8"
          />
        </details>
        <details class="advanced-config-json">
          <summary>Framework groups JSON</summary>
          <textarea
            v-model="groupsJsonText"
            :disabled="!canEditConfig"
            rows="8"
          />
        </details>
        <details class="advanced-config-json">
          <summary>Framework group descriptions JSON</summary>
          <textarea
            v-model="groupDescriptionsJsonText"
            :disabled="!canEditConfig"
            rows="8"
          />
        </details>
        <details class="advanced-config-json">
          <summary>Wiki auto-grants JSON</summary>
          <textarea
            v-model="autoGrantsJsonText"
            :disabled="!canEditConfig"
            rows="8"
          />
        </details>
      </section>
    </section>

    <!-- Bulk config saves here; the Users tab has a separate per-user save path. -->
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
