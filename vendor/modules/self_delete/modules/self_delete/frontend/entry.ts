import "@wikimedia/codex/dist/codex.style.css";
import { createApp } from "vue";
import SelfDeleteApp from "./SelfDeleteApp.vue";
import "./style.css";

const mount = document.getElementById("self-delete-app");

if (mount && mount.dataset.vueMounted !== "true") {
  mount.dataset.vueMounted = "true";
  createApp(SelfDeleteApp).mount(mount);
}
