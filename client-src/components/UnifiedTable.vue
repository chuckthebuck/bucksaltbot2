<script setup lang="ts">
// Generic table renderer shared by rollback, authorization, and module pages.
// Callers provide inert render descriptions; this component owns Vue rendering.
import { computed, useSlots } from "vue";
import type { TableCellComponent, TableCellRenderable, TableColumn } from "./unifiedTable";

const props = defineProps<{
  rows: unknown[];
  columns: TableColumn<any>[];
  rowKey: string | ((row: unknown, index: number) => string | number);
  expanded?: (row: unknown) => boolean;
  tableClass?: string;
  emptyText?: string;
}>();

const slots = useSlots();

const visibleColumns = computed(() =>
  // A conditional column remains visible if it applies to any current row,
  // preventing headers from shifting independently row by row.
  props.columns.filter((col) => {
    if (!col.visible) return true;
    return props.rows.some((row) => col.visible!(row));
  })
);

const hasExpandedSlot = computed(() => Boolean(slots.expanded));

function rowKeyFor(row: unknown, idx: number): string | number {
  /** Resolve a stable caller key and fall back to position for malformed rows. */
  if (typeof props.rowKey === "function") return props.rowKey(row, idx);

  if (row && typeof row === "object") {
    const value = (row as Record<string, unknown>)[props.rowKey];
    if (typeof value === "string" || typeof value === "number") {
      return value;
    }
  }

  return idx;
}

function asItems(
  value: TableCellRenderable | TableCellRenderable[]
): TableCellRenderable[] {
  /** Normalize scalar and optional cell output into one renderable list. */
  if (Array.isArray(value)) {
    return value.filter((item) => item !== null && item !== undefined);
  }

  if (value === null || value === undefined) {
    return [];
  }

  return [value];
}

function cellItems(col: TableColumn<any>, row: unknown): TableCellRenderable[] {
  /** Evaluate and normalize one caller-defined cell renderer. */
  return asItems(col.render(row));
}

function isComponentCell(item: TableCellRenderable): item is TableCellComponent {
  /** Narrow a cell description before passing it to Vue's dynamic component. */
  return Boolean(item && typeof item === "object" && "component" in item);
}

function cellClass(col: TableColumn<any>, row: unknown): string | undefined {
  /** Resolve static or row-dependent cell class metadata. */
  if (typeof col.class === "function") {
    return col.class(row);
  }

  return col.class;
}

function cellStyle(col: TableColumn<any>): Record<string, string> {
  /** Convert alignment/width metadata into Vue style bindings. */
  return {
    ...(col.align ? { textAlign: col.align } : {}),
    ...(col.width ? { width: col.width } : {}),
  };
}

function headerStyle(col: TableColumn<any>): Record<string, string> {
  /** Keep an explicitly sized header aligned with its body cells. */
  return col.width ? { width: col.width } : {};
}
</script>

<template>
  <table :class="['wikitable', 'unified-table', tableClass]">
    <thead>
      <tr>
        <th
          v-for="col in visibleColumns"
          :key="col.key"
          :class="col.headerClass"
          :style="headerStyle(col)"
        >
          {{ col.label }}
        </th>
      </tr>
    </thead>

    <tbody>
      <template v-for="(row, rowIndex) in rows" :key="rowKeyFor(row, rowIndex)">
        <tr>
          <td
            v-for="col in visibleColumns"
            :key="col.key"
            :class="cellClass(col, row)"
            :style="cellStyle(col)"
          >
            <div
              :class="[
                'unified-table__cell-items',
                col.noWrap ? 'unified-table__cell-items--nowrap' : ''
              ]"
            >
              <template
                v-for="(item, itemIndex) in cellItems(col, row)"
                :key="isComponentCell(item) ? (item.key ?? itemIndex) : itemIndex"
              >
                <component
                  :is="item.component"
                  v-if="isComponentCell(item)"
                  v-bind="item.props"
                >
                  {{ item.children }}
                </component>
                <template v-else>
                  {{ item }}
                </template>
              </template>
            </div>
          </td>
        </tr>

        <tr v-if="hasExpandedSlot && expanded?.(row)">
          <td :colspan="visibleColumns.length">
            <slot name="expanded" :row="row" :colspan="visibleColumns.length" />
          </td>
        </tr>
      </template>

      <tr v-if="!rows.length">
        <td :colspan="visibleColumns.length" class="unified-table__empty">
          {{ emptyText || 'No rows found.' }}
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.unified-table {
  width: 100%;
}

.unified-table__cell-items {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
}

.unified-table__cell-items--nowrap {
  white-space: nowrap;
}

.unified-table__empty {
  text-align: center;
  color: var(--color-subtle, #54595d);
  padding: 20px;
}
</style>
