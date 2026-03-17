console.log("🔥 ENTRY FILE RUNNING 🔥");

import { createApp } from "vue";
import App from "./App.vue";
import BatchApp from "./BatchApp.vue";
import "@wikimedia/codex/dist/codex.style.css";

if (document.getElementById("batch-props")) {
  createApp(BatchApp).mount("#app");
} else {
  createApp(App).mount("#app");
}
