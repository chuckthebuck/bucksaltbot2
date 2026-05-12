import "@wikimedia/codex/dist/codex.style.css";
import { createApp } from "vue";
import FourAwardApp from "./FourAwardApp.vue";

const mount = document.getElementById("four-award-app");

if (mount && mount.dataset.vueMounted !== "true") {
  mount.dataset.vueMounted = "true";
  createApp(FourAwardApp).mount(mount);
}
