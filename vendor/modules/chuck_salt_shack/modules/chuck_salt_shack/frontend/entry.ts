import { createApp } from "vue";
import App from "./SaltShackApp.vue";
import "./style.css";

// The framework owns the page shell; this bundle owns only its declared mount.
const mount = document.getElementById("chuck-salt-shack-app");

if (mount) {
  createApp(App).mount(mount);
}
