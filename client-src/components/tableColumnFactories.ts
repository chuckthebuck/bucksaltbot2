import type { TableCellComponent, TableColumn } from "./unifiedTable";

export interface ToggleFieldRow<K extends string = string> {
  key: K;
  label: string;
  help?: string;
  section?: string;
}

export const DEFAULT_ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "resolving",
  "staging",
  "pending_approval",
]);

/** Map a job status to the shared Codex tag presentation. */
export function defaultStatusClass(
  status: string,
  activeStatuses: Set<string> = DEFAULT_ACTIVE_STATUSES
): string {
  if (status === "completed") return "cdx-tag--status-success";
  if (status === "failed") return "cdx-tag--status-error";
  if (status === "canceled") return "cdx-tag--status-muted";
  if (activeStatuses.has(status)) return "cdx-tag--status-warning";
  return "cdx-tag--status-muted";
}

/** Map dry-run/live/mixed state to the shared mode tag presentation. */
export function defaultModeClass(dryRun: boolean | null): string {
  if (dryRun === null) return "cdx-tag--mode-mixed";
  return dryRun ? "cdx-tag--mode-dry-run" : "cdx-tag--mode-live";
}

/** Return a configurable human label for dry-run/live/mixed state. */
export function modeLabel(
  dryRun: boolean | null,
  labels: { dry: string; live: string; mixed?: string } = {
    dry: "Dry run",
    live: "Live",
    mixed: "Mixed",
  }
): string {
  if (dryRun === null) return labels.mixed ?? "Mixed";
  return dryRun ? labels.dry : labels.live;
}

/** Summarize terminal item count against the job total. */
export function progressSummary(row: { total: number; completed: number; failed: number }): string {
  const done = (row.completed || 0) + (row.failed || 0);
  return `${done}/${row.total || 0}`;
}

/** Convert terminal item counts into a whole-number progress percentage. */
export function progressPercent(row: { total: number; completed: number; failed: number }): number {
  const done = (row.completed || 0) + (row.failed || 0);
  return row.total ? Math.round((done / row.total) * 100) : 0;
}

/** Build a plain text/number table column from a row accessor. */
export function textColumn<T>(
  key: string,
  label: string,
  getText: (row: T) => string | number,
  options?: Pick<TableColumn<T>, "class" | "align" | "width">
): TableColumn<T> {
  return {
    key,
    label,
    render: getText,
    class: options?.class,
    align: options?.align,
    width: options?.width,
  };
}

/** Build a status tag column while allowing module-specific class mapping. */
export function statusTagColumn<T>(
  key: string,
  label: string,
  getStatus: (row: T) => string,
  getClass: (status: string) => string = defaultStatusClass
): TableColumn<T> {
  return {
    key,
    label,
    render: (row) => {
      const status = getStatus(row);
      return {
        component: "span",
        props: {
          class: ["cdx-tag", getClass(status)],
        },
        children: status,
      };
    },
  };
}

/** Build a dry-run/live/mixed tag column. */
export function dryRunModeColumn<T>(
  key: string,
  label: string,
  getDryRun: (row: T) => boolean | null,
  getLabel: (dryRun: boolean | null) => string = (dryRun) => modeLabel(dryRun),
  getClass: (dryRun: boolean | null) => string = defaultModeClass
): TableColumn<T> {
  return {
    key,
    label,
    render: (row) => {
      const dryRun = getDryRun(row);
      return {
        component: "span",
        props: {
          class: ["cdx-tag", getClass(dryRun)],
        },
        children: getLabel(dryRun),
      };
    },
  };
}

/** Describe a link cell for the generic Vue table renderer. */
export function linkCell(
  text: string | number,
  href: string,
  options?: {
    target?: string;
    rel?: string;
    onClick?: (event: Event) => void;
  }
): TableCellComponent {
  return {
    component: "a",
    props: {
      href,
      ...(options?.target ? { target: options.target } : {}),
      ...(options?.rel ? { rel: options.rel } : {}),
      ...(options?.onClick ? { onClick: options.onClick } : {}),
    },
    children: text,
  };
}

/** Describe a Codex-compatible button cell for the generic table renderer. */
export function buttonCell(
  component: unknown,
  text: string,
  onClick: () => void,
  options?: {
    key?: string;
    size?: "small" | "medium" | "large";
    action?: "default" | "progressive" | "destructive";
    weight?: "normal" | "primary" | "quiet";
    disabled?: boolean;
    extraProps?: Record<string, unknown>;
  }
): TableCellComponent {
  return {
    component: component as TableCellComponent["component"],
    key: options?.key,
    props: {
      type: "button",
      size: options?.size ?? "small",
      action: options?.action ?? "default",
      weight: options?.weight ?? "quiet",
      disabled: options?.disabled,
      onClick,
      ...(options?.extraProps || {}),
    },
    children: text,
  };
}

/** Add a common section label to toggle-field metadata. */
export function buildToggleRows<K extends string>(
  fields: Array<{ key: K; label: string; help?: string }>,
  section?: string
): ToggleFieldRow<K>[] {
  return fields.map((field) => ({
    key: field.key,
    label: field.label,
    help: field.help,
    section,
  }));
}

/** Flatten named toggle sections while preserving their display order. */
export function buildSectionedToggleRows<K extends string>(
  sections: Array<{ title: string; fields: Array<{ key: K; label: string; help?: string }> }>
): ToggleFieldRow<K>[] {
  return sections.flatMap((section) => buildToggleRows(section.fields, section.title));
}

/** Select toggle rows belonging to one rendered section. */
export function filterToggleRowsBySection<K extends string>(
  rows: ToggleFieldRow<K>[],
  sectionTitle: string
): ToggleFieldRow<K>[] {
  return rows.filter((row) => row.section === sectionTitle);
}

/** Build the standard toggle-name text column. */
export function toggleLabelColumn<T extends { label: string }>(label = "Name"): TableColumn<T> {
  return {
    key: "label",
    label,
    render: (row) => row.label,
  };
}

/** Build the standard optional toggle-description column. */
export function toggleHelpColumn<T extends { help?: string }>(
  label = "Description"
): TableColumn<T> {
  return {
    key: "help",
    label,
    render: (row) => row.help || "",
  };
}

/** Build an accessible checkbox column backed by caller-owned state. */
export function toggleCheckboxColumn<T extends { key: string }>(
  label = "Enabled",
  getChecked: (row: T) => boolean,
  setChecked: (row: T, checked: boolean) => void,
  isDisabled: () => boolean,
  options?: { width?: string }
): TableColumn<T> {
  return {
    key: "enabled",
    label,
    align: "center",
    width: options?.width ?? "1%",
    noWrap: true,
    render: (row) => ({
      component: "input",
      props: {
        type: "checkbox",
        checked: getChecked(row),
        disabled: isDisabled(),
        onChange: (event: Event) => {
          const target = event.target as HTMLInputElement | null;
          if (!target) return;
          setChecked(row, target.checked);
        },
      },
    }),
  };
}
