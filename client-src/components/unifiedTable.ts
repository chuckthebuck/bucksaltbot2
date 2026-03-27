import type { Component } from "vue";

export type TableAlign = "left" | "center" | "right";

export interface TableCellComponent {
  component: string | Component;
  props?: Record<string, unknown>;
  children?: string | number | null;
  key?: string | number;
}

export type TableCellRenderable = string | number | boolean | null | undefined | TableCellComponent;

export interface TableColumn<T = unknown> {
  key: string;
  label: string;
  render: (row: T) => TableCellRenderable | TableCellRenderable[];
  width?: string;
  align?: TableAlign;
  class?: string | ((row: T) => string | undefined);
  headerClass?: string;
  visible?: (row: T) => boolean;
  noWrap?: boolean;
}

export function actionColumn<T = unknown>(
  key: string,
  label: string,
  render: (row: T) => TableCellRenderable | TableCellRenderable[],
  options?: {
    width?: string;
    class?: string;
    headerClass?: string;
    visible?: (row: T) => boolean;
  }
): TableColumn<T> {
  return {
    key,
    label,
    render,
    width: options?.width ?? "1%",
    align: "center",
    noWrap: true,
    class: options?.class,
    headerClass: options?.headerClass,
    visible: options?.visible,
  };
}
