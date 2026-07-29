import { createApp } from "vue";
import App from "./SaltlickApp.vue";
import "./style.css";

const mount = document.getElementById("saltlick-app");

if (mount) {
  createApp(App).mount(mount);
}
