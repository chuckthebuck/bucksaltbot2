console.log("🔥 ENTRY FILE RUNNING 🔥");
import "@wikimedia/codex/dist/codex.style.css";
import "./styles.less"; // 👈 you already have this file, USE IT
import { createApp } from "vue";
import App from "./App.vue";
import BatchApp from "./BatchApp.vue";
import AllJobsApp from "./AllJobsApp.vue";
import FromDiffApp from "./FromDiffApp.vue";
import AccountRollbackApp from "./AccountRollbackApp.vue";
import ConfigApp from "./ConfigApp.vue";
import RequestReviewApp from "./RequestReviewApp.vue";
import ModulesApp from "./ModulesApp.vue";
import JobsYamlApp from "./JobsYamlApp.vue";
import FourAwardApp from "./FourAwardApp.vue";

if (document.getElementById("batch-props")) {
  createApp(BatchApp).mount("#app");
} else if (document.getElementById("all-jobs-props")) {
  createApp(AllJobsApp).mount("#app");
} else if (document.getElementById("from-diff-props")) {
  createApp(FromDiffApp).mount("#app");
} else if (document.getElementById("from-account-props")) {
  createApp(AccountRollbackApp).mount("#app");
} else if (document.getElementById("runtime-config-props")) {
  createApp(ConfigApp).mount("#app");
} else if (document.getElementById("request-review-props")) {
  createApp(RequestReviewApp).mount("#app");
} else if (document.getElementById("modules-props")) {
  createApp(ModulesApp).mount("#modules-container");
} else if (document.getElementById("jobs-yaml-props")) {
  createApp(JobsYamlApp).mount("#app");
} else if (document.getElementById("four-award-props")) {
  createApp(FourAwardApp).mount("#app");
} else if (document.getElementById("rollback-queue-props")) {
  createApp(App).mount("#app");
}
