<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { CdxButton, CdxField, CdxLookup, CdxSelect, CdxTextInput } from "@wikimedia/codex";
import { loadEditorsForTitle, searchTitles } from "../api";

const props = defineProps<{
  namespaceId: string;
}>();

const emit = defineEmits<{
  remove: [];
  update: [
    {
      title: string;
      user: string;
      summary: string | null;
    } | null
  ];
}>();

const selected = ref<string | number | null>(null);
const menuItems = ref<Array<{ label: string; value: string }>>([]);
const users = ref<string[]>([]);
const selectedUser = ref<string | number | null>(null);
const summary = ref("");
const meta = ref("");
let lookupRequestId = 0;
let editorsRequestId = 0;

const canEmit = computed(() => {
  return selected.value !== null && selectedUser.value !== null;
});

async function onLookupInput(value: string | number) {
  const query = String(value || "").trim();
  const requestId = ++lookupRequestId;

  if (!query) {
    menuItems.value = [];
    return;
  }

  try {
    const results = await searchTitles(query, props.namespaceId);
    if (requestId !== lookupRequestId) return;
    menuItems.value = results;
  } catch {
    if (requestId !== lookupRequestId) return;
    menuItems.value = [];
  }
}


async function onSelectionChanged(v: string | number | null) {
  const title = v === null ? "" : String(v);
  const requestId = ++editorsRequestId;

  if (!title) {
    users.value = [];
    selectedUser.value = null;
    meta.value = "";
    emit("update", null);
    return;
  }

  try {
    const editorData = await loadEditorsForTitle(title);
    if (requestId !== editorsRequestId) return;

    users.value = editorData.users;

    const fallbackUser = editorData.users[0] || null;
    selectedUser.value = editorData.latestUser || fallbackUser;

    if (!summary.value) {
      summary.value = editorData.latestComment || "";
    }

    meta.value = editorData.latestUser ? `Latest editor: ${editorData.latestUser}` : "No contributors found";
  } catch {
    if (requestId !== editorsRequestId) return;
    users.value = [];
    selectedUser.value = null;
    meta.value = "Failed to load contributors";
    emit("update", null);
  }
}

watch(selected, onSelectionChanged);

watch([selected, selectedUser, summary], () => {
  if (!canEmit.value) {
    emit("update", null);
    return;
  }

  emit("update", {
    title: String(selected.value),
    user: String(selectedUser.value),
    summary: summary.value || null,
  });
});
</script>

<template>
  <div class="job-item-row">
    <CdxField>
      <CdxLookup
        v-model:selected="selected"
        :menu-items="menuItems"
        placeholder="Search page"
        @input="onLookupInput"
      />
      <div class="lookup-meta">{{ meta }}</div>
    </CdxField>

    <CdxField>
      <CdxSelect
        v-model:selected="selectedUser"
        :menu-items="users.map(u => ({ label: u, value: u }))"
        default-label="Select contributor"
        class="lookup-user"
      />
    </CdxField>

    <CdxTextInput
      v-model="summary"
      class="item-summary"
      placeholder="Summary (optional)"
    />

    <CdxButton action="destructive" weight="normal" @click="emit('remove')">
      Remove
    </CdxButton>
  </div>
</template>
