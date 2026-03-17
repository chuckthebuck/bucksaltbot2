console.log("🔥 ENTRY FILE RUNNING 🔥");

import { createApp } from "vue";
import App from "./App.vue";
import "@wikimedia/codex/dist/codex.style.css";
import "./styles.less";

createApp(App).mount("#app");
