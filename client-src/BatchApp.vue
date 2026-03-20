<script setup lang="ts">
import { ref, computed } from "vue";
import {
  CdxButton,
  CdxTextArea,
  CdxMessage
} from "@wikimedia/codex";

/* ---------------- props ---------------- */

const props = JSON.parse(
  document.getElementById("batch-props")!.textContent!
);

/* ---------------- state ---------------- */

const input = ref("");
const parsed = ref<any[]>([]);
const errors = ref<string[]>([]);
const result = ref("");

const dryRun = ref(false);
const importUser = ref("");
const batchNumber = ref("");

/* ---------------- parsing ---------------- */

function parseInput() {
  errors.value = [];

  const lines = input.value
    .split("\n")
    .map(l => l.trim())
    .filter(Boolean);

  const items = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const parts = line.split("|");

    if (parts.length < 2) {
      errors.value.push(`Line ${i + 1}: must be title|user`);
      continue;
    }

    const [title, user, summary] = parts;

    if (!title || !user) {
      errors.value.push(`Line ${i + 1}: missing title or user`);
      continue;
    }

    items.push({
      title: title.trim(),
      user: user.trim(),
      summary: summary?.trim() || null,
      selected: true
    });
  }

  parsed.value = items;
}

/* ---------------- contrib import ---------------- */

async function loadContribs() {
  if (!importUser.value) return;

  errors.value = [];

  const url =
    "https://commons.wikimedia.org/w/api.php?origin=*&format=json" +
    "&action=query" +
    "&list=usercontribs" +
    "&uclimit=500" +
    "&ucprop=title|comment|timestamp" +
    "&ucuser=" + encodeURIComponent(importUser.value);

  try {
    const r = await fetch(url);
    const data = await r.json();

    const contribs = data?.query?.usercontribs || [];

    if (!contribs.length) {
      errors.value = ["No contributions found"];
      return;
    }

    const seen = new Set();

    parsed.value = contribs
      .filter((c: any) => {
        if (seen.has(c.title)) return false;
        seen.add(c.title);
        return true;
      })
      .map((c: any) => ({
        title: c.title,
        user: importUser.value,
        summary: c.comment || null,
        selected: true
      }));

  } catch {
    errors.value = ["Failed to fetch contributions"];
  }
}

/* ---------------- JSON upload ---------------- */

function handleFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;

  const reader = new FileReader();

  reader.onload = () => {
    try {
      const json = JSON.parse(reader.result as string);

      if (!Array.isArray(json.items)) {
        throw new Error();
      }

      parsed.value = json.items.map((i: any) => ({
        ...i,
        selected: true
      }));

      errors.value = [];

    } catch {
      errors.value = ["Invalid JSON file"];
    }
  };

  reader.readAsText(file);
}

/* ---------------- selection helpers ---------------- */

function selectAll(val: boolean) {
  parsed.value.forEach(i => i.selected = val);
}

function invertSelection() {
  parsed.value.forEach(i => i.selected = !i.selected);
}

const selectedCount = computed(() =>
  parsed.value.filter(i => i.selected).length
);

/* ---------------- submit ---------------- */

async function submit() {
  if (!parsed.value.length) {
    alert("No items");
    return;
  }

  const items = parsed.value
    .filter(i => i.selected)
    .map(({ selected, ...rest }) => rest);

  if (!items.length) {
    alert("No items selected");
    return;
  }

  const trimmedBatch = batchNumber.value.trim();
  const batchId = trimmedBatch ? Number(trimmedBatch) : undefined;

  if (batchId !== undefined && (!Number.isInteger(batchId) || batchId <= 0)) {
    errors.value = ["Batch number must be a positive integer"];
    return;
  }

  const r = await fetch("/api/v1/rollback/jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      requested_by: props.username,
      dry_run: dryRun.value,
      batch_id: batchId,
      items
    })
  });

  const data = await r.json();
  result.value = JSON.stringify(data, null, 2);
}
</script>

<template>
  <div class="container">

    <!-- instructions -->
    <CdxMessage>
      Enter one item per line:
      <br>
      <code>Title|User|Optional summary</code>
    </CdxMessage>

    <!-- textarea -->
    <CdxTextArea
      v-model="input"
      rows="8"
      placeholder="File:Example.jpg|Username|Optional summary"
    />

    <br><br>

    <!-- file upload -->
    <label>
      Upload JSON:
      <input type="file" accept=".json" @change="handleFile">
    </label>

    <br><br>

    <!-- contrib import -->
    <div>
      <input
        v-model="importUser"
        placeholder="Import from user contributions"
        style="padding:6px; width:250px"
      />

      <CdxButton type="button" @click="loadContribs">
        Import
      </CdxButton>
    </div>

    <br>

    <label style="display:flex; flex-direction:column; gap:4px; max-width:250px; margin-top:8px">
      Batch number (optional)
      <input
        v-model="batchNumber"
        type="number"
        min="1"
        placeholder="Auto-generated if blank"
        style="padding:6px"
      />
    </label>

    <br>

    <!-- dry run -->
    <label style="display:flex; align-items:center; gap:8px">
      <input type="checkbox" v-model="dryRun">
      Dry run (no actual rollback)
    </label>

    <br>

    <!-- buttons -->
    <CdxButton type="button" @click="parseInput">
      Preview
    </CdxButton>

    <CdxButton type="button" action="progressive" weight="primary" @click="submit">
      Submit batch job
    </CdxButton>

    <!-- errors -->
    <div v-if="errors.length" style="color:red; margin-top:10px">
      <div v-for="e in errors" :key="e">{{ e }}</div>
    </div>

    <!-- selection controls -->
    <div v-if="parsed.length" style="margin-top:10px">
      <CdxButton type="button" @click="selectAll(true)">Select all</CdxButton>
      <CdxButton type="button" @click="selectAll(false)">Select none</CdxButton>
      <CdxButton type="button" @click="invertSelection()">Invert</CdxButton>

      <span style="margin-left:10px">
        {{ selectedCount }} / {{ parsed.length }} selected
      </span>
    </div>

    <!-- item list -->
    <div v-if="parsed.length" style="margin-top:10px">

      <div
        v-for="(item, i) in parsed"
        :key="i"
        :style="{ opacity: item.selected ? 1 : 0.4 }"
        style="
          display:grid;
          grid-template-columns: 30px 1fr 1fr;
          gap:10px;
          padding:6px;
          border-bottom:1px solid #eee;
          align-items:center;
        "
      >

        <input type="checkbox" v-model="item.selected" />

        <div>
          <b>{{ item.title }}</b>
        </div>

        <div style="font-size:12px; color:#54595d">
          {{ item.user }}
          <br>
          <i>{{ item.summary }}</i>
        </div>

      </div>

    </div>

    <!-- result -->
    <pre v-if="result">{{ result }}</pre>

  </div>
</template>
