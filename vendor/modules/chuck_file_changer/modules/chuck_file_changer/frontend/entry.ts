import { createApp } from "vue";
import App from "./FileChangerApp.vue";
import "./style.css";

const mount = document.getElementById("chuck-file-changer-app");

if (mount) {
  createApp(App).mount(mount);
}
