console.log("🔥 ENTRY FILE RUNNING 🔥");
import * as Vue from "vue";
import * as Codex from "@wikimedia/codex";
import "@wikimedia/codex/dist/codex.style.css";
import "./styles.less"

(window as any).Vue = Vue;
(window as any).Codex = Codex;
