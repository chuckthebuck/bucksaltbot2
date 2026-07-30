/// <reference types="vite/client" />

// Let the standalone module type-check Vue single-file component imports.
declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}
