<script setup lang="ts">
/**
 * Batch rollback request authoring surface.
 *
 * Multiple import formats converge on one selectable preview list. Submission
 * creates an approval-gated request; this component never executes rollbacks.
 */
import { ref, computed, onMounted, watch } from "vue";
import {
  CdxButton,
  CdxTextArea,
  CdxMessage
} from "@wikimedia/codex";
import {
  parseQuarryText,
  parseQuarryJson,
  quarryResultUrl
} from "./batchImport";
import { loadDraft, saveDraft } from "./draft";

/* ---------------- server context ---------------- */

const props = JSON.parse(
  document.getElementById("batch-props")!.textContent!
);

/* ---------------- draft and normalized preview state ---------------- */

const input = ref("");
const parsed = ref<any[]>([]);
const errors = ref<string[]>([]);
const result = ref("");

const dryRun = ref(false);
const rollbackThroughBots = ref(false);
const importUser = ref("");
const quarryInput = ref("");
const batchNumber = ref("");

// Draft storage is scoped by username so accounts sharing a browser do not
// overwrite each other's manual input.
const draftKey = `buckbot:batchDraft:${props.username ?? "anon"}`;

// Restore only into an untouched form; an already initialized value wins.
onMounted(() => {
  const saved = loadDraft(draftKey);
  if (saved && !input.value) {
    input.value = saved;
  }
});

// Persist manual text continuously. Imported previews remain transient because
// they can be recreated from their source and may contain large datasets.
watch(input, (value) => {
  saveDraft(draftKey, value);
});

/* ---------------- parsing ---------------- */

/** Parse manual lines while preserving selection for unchanged item identities. */
function parseInput() {
  errors.value = [];

  const lines = input.value
    .split("\n")
    .map(l => l.trim())
    .filter(Boolean);

  // Don't clobber imported/uploaded preview data when there is no text input.
  if (!lines.length) {
    return;
  }

  // Identity includes the optional summary: changing it creates a newly
  // selected request item instead of inheriting a possibly stale deselection.
  const existingSelection = new Map(
    parsed.value.map(i => [
      `${i.title}|${i.user}|${i.summary ?? ""}`,
      Boolean(i.selected)
    ])
  );

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

    const normalizedTitle = title.trim();
    const normalizedUser = user.trim();
    const normalizedSummary = summary?.trim() || null;
    const key = `${normalizedTitle}|${normalizedUser}|${normalizedSummary ?? ""}`;

    items.push({
      title: normalizedTitle,
      user: normalizedUser,
      summary: normalizedSummary,
      selected: existingSelection.get(key) ?? true
    });
  }

  parsed.value = items;
}

/* ---------------- contrib import ---------------- */

/** Replace the preview with first-seen unique contributions for one user.
 *
 * Import calls are not canceled or request-ID guarded; if an operator starts
 * several imports, the last response to finish becomes the visible preview.
 */
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
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) {
      throw new Error(`HTTP ${r.status}`);
    }
    const data = await r.json();

    const contribs = data?.query?.usercontribs || [];

    if (!contribs.length) {
      errors.value = ["No contributions found"];
      return;
    }

    // Preserve API order while collapsing repeated edits to the same title.
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

/* ---------------- Quarry import ---------------- */

/** Atomically replace imported preview rows, retaining the old list on empty input. */
function setImportedItems(items: any[], emptyMessage: string) {
  if (!items.length) {
    errors.value = [emptyMessage];
    return;
  }

  parsed.value = items;
  errors.value = [];
}

/** Resolve an allowlisted Quarry reference and replace the normalized preview. */
async function loadQuarry() {
  const url = quarryResultUrl(quarryInput.value);

  if (!url) {
    errors.value = [
      "Enter a Quarry query URL, run URL, query ID, query:ID, or run:ID"
    ];
    return;
  }

  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) {
      throw new Error(`HTTP ${r.status}`);
    }

    const data = await r.json();
    setImportedItems(
      parseQuarryJson(data),
      "No rollback items found. Quarry output needs title/file and user columns."
    );
  } catch {
    errors.value = ["Failed to fetch or parse Quarry results"];
  }
}

/* ---------------- file upload ---------------- */

/** Read one local JSON/CSV/TSV file and normalize it entirely in the browser. */
function handleFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;

  const reader = new FileReader();

  reader.onload = () => {
    try {
      setImportedItems(
        parseQuarryText(reader.result as string),
        "No rollback items found in uploaded file"
      );

    } catch {
      errors.value = ["Invalid uploaded file"];
    }
  };

  reader.readAsText(file);
}

/* ---------------- selection helpers ---------------- */

/** Set every preview row's submission flag. */
function selectAll(val: boolean) {
  parsed.value.forEach(i => i.selected = val);
}

/** Toggle every preview row's submission flag in place. */
function invertSelection() {
  parsed.value.forEach(i => i.selected = !i.selected);
}

// Derive the counter from row flags so imports and bulk actions cannot desync it.
const selectedCount = computed(() =>
  parsed.value.filter(i => i.selected).length
);

/* ---------------- submit ---------------- */

/** Submit only selected rows as an approval-gated batch request. */
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

  // Server-side authentication, batch-ID policy, and execution rights remain
  // authoritative; requested_by and dry-run values are request data, not grants.
  const r = await fetch("/api/v1/rollback/jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      requested_by: props.username,
      dry_run: dryRun.value,
      rollback_through_bots: rollbackThroughBots.value,
      batch_id: batchId,
      request_type: "batch",
      items
    })
  });

  const data = await r.json();
  result.value = JSON.stringify(data, null, 2);
}
</script>

<template>
  <div class="container">

    <!-- Explain the approval boundary and manual interchange format first. -->
    <CdxMessage>
      Enter one item per line to submit a batch request (admin approval required before execution):
      <br>
      <code>Title|User|Optional summary</code>
    </CdxMessage>

    <!-- Manual text is draft-persisted; imports populate the preview directly. -->
    <CdxTextArea
      v-model="input"
      rows="8"
      placeholder="File:Example.jpg|Username|Optional summary"
    />

    <br><br>

    <!-- File parsing stays local; only selected normalized rows are submitted. -->
    <label>
      Upload Quarry/JSON/CSV:
      <input type="file" accept=".json,.csv,.tsv,text/csv,text/tab-separated-values,application/json" @change="handleFile">
    </label>

    <br><br>

    <!-- Remote import helpers replace, rather than merge into, preview state. -->
    <div>
      <input
        v-model="quarryInput"
        placeholder="Import from Quarry query/run URL or ID"
        style="padding:6px; width:320px"
      />

      <CdxButton type="button" @click.prevent="loadQuarry">
        Import Quarry
      </CdxButton>
    </div>

    <br>

    <!-- contrib import -->
    <div>
      <input
        v-model="importUser"
        placeholder="Import from user contributions"
        style="padding:6px; width:250px"
      />

      <CdxButton type="button" @click.prevent="loadContribs">
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

    <!-- These are requested execution options and are revalidated server-side. -->
    <label style="display:flex; align-items:center; gap:8px">
      <input type="checkbox" v-model="dryRun">
      Dry run (no actual rollback)
    </label>

    <label style="display:flex; align-items:center; gap:8px">
      <input type="checkbox" v-model="rollbackThroughBots">
      Roll back through top bot edits
    </label>

    <br>

    <!-- Preview parses local text; Submit sends the current selected preview. -->
    <CdxButton type="button" @click.prevent="parseInput">
      Preview
    </CdxButton>

    <CdxButton type="button" action="progressive" weight="primary" @click.prevent="submit">
      Submit batch request
    </CdxButton>

    <!-- errors -->
    <div v-if="errors.length" style="color:red; margin-top:10px">
      <div v-for="e in errors" :key="e">{{ e }}</div>
    </div>

    <!-- Selection helpers mutate the same flags used to construct the payload. -->
    <div v-if="parsed.length" style="margin-top:10px">
      <CdxButton type="button" @click="selectAll(true)">Select all</CdxButton>
      <CdxButton type="button" @click="selectAll(false)">Select none</CdxButton>
      <CdxButton type="button" @click="invertSelection()">Invert</CdxButton>

      <span style="margin-left:10px">
        {{ selectedCount }} / {{ parsed.length }} selected
      </span>
    </div>

    <!-- Normalized preview rows expose exactly what will be included/excluded. -->
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

    <!-- Raw server response is retained for request IDs and troubleshooting. -->
    <pre v-if="result">{{ result }}</pre>

  </div>
</template>
