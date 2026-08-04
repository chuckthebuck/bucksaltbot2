import { createApp } from "vue";
import App from "./FileChangerApp.vue";
import "./style.css";

// The framework owns the surrounding page shell and declares this mount ID in
// module.toml. A missing mount is valid on non-module routes, so setup is a no-op.
const mount = document.getElementById("chuck-file-changer-app");

if (mount) {
  createApp(App).mount(mount);
}
