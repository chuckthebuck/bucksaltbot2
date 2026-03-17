console.log("🔥 ENTRY FILE RUNNING 🔥");

import * as Vue from "vue";
import * as Codex from "@wikimedia/codex";
import "@wikimedia/codex/dist/codex.style.css";
import "./styles.less";

import { createApp, ref, watch } from "vue";
import { CdxLookup } from "@wikimedia/codex";

// expose for debugging if needed
(window as any).Vue = Vue;
(window as any).Codex = Codex;

/* ---------------- helpers ---------------- */

function mwApi(params: string) {
  return "https://commons.wikimedia.org/w/api.php?origin=*&format=json&" + params;
}

/* ---------------- codex lookup ---------------- */

function mountLookup(row: HTMLElement) {
  const container = row.querySelector(".lookup-title") as HTMLElement;
  const meta = row.querySelector(".lookup-meta") as HTMLElement;
  const userSelect = row.querySelector(".lookup-user") as HTMLSelectElement;
  const summary = row.querySelector(".item-summary") as HTMLInputElement;

  createApp({
    components: { CdxLookup },

    setup() {
      const selected = ref("");
      const menuItems = ref<any[]>([]);

      async function search(value: string) {
        if (!value) {
          menuItems.value = [];
          return;
        }

        const ns = (document.getElementById("namespace-select") as HTMLSelectElement)?.value;
        const nsParam = ns ? "&namespace=" + ns : "";

        const r = await fetch(
          mwApi(
            "action=opensearch" +
              "&limit=10" +
              nsParam +
              "&search=" +
              encodeURIComponent(value)
          )
        );

        const d = await r.json();

        menuItems.value = (d[1] || []).map((t: string) => ({
          label: t,
          value: t,
        }));
      }

      async function loadEditor(title: string) {
        row.dataset.title = title;

        userSelect.innerHTML = "";
        meta.textContent = "";

        const r = await fetch(
          mwApi(
            "action=query" +
              "&prop=revisions" +
              "&titles=" +
              encodeURIComponent(title) +
              "&rvprop=user|comment" +
              "&rvlimit=10"
          )
        );

        const data = await r.json();
        const pages = data.query.pages;

        let revisions: any[] = [];

        for (let id in pages) {
          if (pages[id].revisions) {
            revisions = pages[id].revisions;
            break;
          }
        }

        if (!revisions.length) return;

        const latest = revisions[0];
        const users = [...new Set(revisions.map((r: any) => r.user))];

        users.forEach((u: string) => {
          const opt = document.createElement("option");
          opt.value = u;
          opt.textContent = u;
          userSelect.appendChild(opt);
        });

        userSelect.value = latest.user;

        if (!summary.value) summary.value = latest.comment || "";

        meta.textContent = "Latest editor: " + latest.user;
      }

      watch(selected, (v: any) => {
        const title = typeof v === "string" ? v : v?.value;
        if (title) loadEditor(title);
      });

      return { selected, menuItems, search };
    },

    template: `
      <cdx-lookup
        v-model:selected="selected"
        :menu-items="menuItems"
        placeholder="Search page"
        @input="search"
      />
    `,
  }).mount(container);
}

/* ---------------- item rows ---------------- */

function createItemRow() {
  const row = document.createElement("div");

  row.className = "job-item-row";

  row.innerHTML = `
    <div>
      <div class="lookup-title"></div>
      <div class="lookup-meta"></div>
    </div>
    <select class="lookup-user"></select>
    <input class="item-summary" placeholder="Summary (optional)">
    <button type="button">Remove</button>
  `;

  row.querySelector("button")!.onclick = () => row.remove();

  document.getElementById("job-items")!.appendChild(row);

  mountLookup(row);

  return row;
}

/* ---------------- expose globals for inline HTML ---------------- */

(window as any).toggle = async function (id: number) {
  const el = document.getElementById(`details-${id}`)!;

  if (el.style.display === "block") {
    el.style.display = "none";
    return;
  }

  const r = await fetch(`/api/v1/rollback/jobs/${id}`);
  const d = await r.json();

  el.style.display = "block";

  el.innerHTML = `
    <b>Status:</b> ${d.status}<br>
    <b>Total:</b> ${d.total}<br>
    <b>Completed:</b> ${d.completed}<br>
    <b>Failed:</b> ${d.failed}<br>
    <pre>${JSON.stringify(d.items, null, 2)}</pre>
  `;
};

(window as any).retry = async function (id: number) {
  if (!confirm("Retry job " + id + "?")) return;

  await fetch(`/api/v1/rollback/jobs/${id}/retry`, {
    method: "POST",
  });
};

(window as any).cancelJob = async function (id: number) {
  if (!confirm("Cancel job " + id + "?")) return;

  await fetch(`/api/v1/rollback/jobs/${id}`, {
    method: "DELETE",
  });
};

/* ---------------- init ---------------- */

function init() {
  console.log("🚀 INIT RUNNING");

  const addBtn = document.getElementById("add-item");

  if (addBtn) {
    addBtn.onclick = createItemRow;
  }

  createItemRow();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
