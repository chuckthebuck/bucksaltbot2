console.log("🔥 ENTRY FILE RUNNING 🔥");

import { createApp } from "vue";
import App from "./App.vue";
import BatchApp from "./BatchApp.vue";

if (document.getElementById("batch-props")) {
  createApp(BatchApp).mount("#app");
} else {
  createApp(App).mount("#app");
}
