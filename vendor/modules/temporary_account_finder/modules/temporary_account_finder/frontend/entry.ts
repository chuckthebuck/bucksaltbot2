import { createApp } from "vue";
import App from "./TemporaryAccountFinderApp.vue";
import "./style.css";

const mount = document.getElementById("temporary-account-finder-app");

if (mount) {
  createApp(App).mount(mount);
}
