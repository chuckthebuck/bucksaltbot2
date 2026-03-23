console.log("🔥 ENTRY FILE RUNNING 🔥");
import "@wikimedia/codex/dist/codex.style.css";
import "./styles.less"; // 👈 you already have this file, USE IT
import { createApp } from "vue";
import App from "./App.vue";
import BatchApp from "./BatchApp.vue";
import AllJobsApp from "./AllJobsApp.vue";
import FromDiffApp from "./FromDiffApp.vue";

if (document.getElementById("batch-props")) {
  createApp(BatchApp).mount("#app");
} else if (document.getElementById("all-jobs-props")) {
  createApp(AllJobsApp).mount("#app");
} else if (document.getElementById("from-diff-props")) {
  createApp(FromDiffApp).mount("#app");
} else if (document.getElementById("rollback-queue-props")) {
  createApp(App).mount("#app");
}
