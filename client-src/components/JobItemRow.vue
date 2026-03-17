<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { CdxButton, CdxField, CdxLookup, CdxTextInput } from "@wikimedia/codex";
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

const selected = ref<any>(null);
const menuItems = ref<Array<{ label: string; value: string }>>([]);
const users = ref<string[]>([]);
const selectedUser = ref("");
const summary = ref("");
const meta = ref("");
const inputValue = ref("");

const canEmit = computed(() => {
  return !!selected.value && typeof selected.value === "object" && !!selected.value.value && !!selectedUser.value;
});

async function onInputValue(value: string) {
  inputValue.value = value;
  menuItems.value = await searchTitles(value, props.namespaceId);
}

async function onSelectionChanged(v: any) {
  if (!v || typeof v !== "object" || !v.value) {
    users.value = [];
    selectedUser.value = "";
    meta.value = "";
    emit("update", null);
    return;
  }

  const editorData = await loadEditorsForTitle(v.value);
  users.value = editorData.users;
  selectedUser.value = editorData.latestUser;
  if (!summary.value) summary.value = editorData.latestComment;
  meta.value = editorData.latestUser ? `Latest editor: ${editorData.latestUser}` : "";
}

watch(selected, onSelectionChanged);

watch([selected, selectedUser, summary], () => {
  if (!canEmit.value) {
    emit("update", null);
    return;
  }

  emit("update", {
    title: selected.value.value,
    user: selectedUser.value,
    summary: summary.value || null,
  });
});
</script>

<template>
  <div class="job-item-row">
    <div>
      <cdx-lookup
        v-model:selected="selected"
        :input-value="inputValue"
        :menu-items="menuItems"
        placeholder="Search page"
        @update:input-value="onInputValue"
      />
      <div class="lookup-meta">{{ meta }}</div>
    </div>

    <cdx-field>
      <select class="lookup-user" v-model="selectedUser">
        <option value="" disabled>Select user</option>
        <option v-for="u in users" :key="u" :value="u">
          {{ u }}
        </option>
      </select>
    </cdx-field>

    <cdx-text-input
      v-model="summary"
      class="item-summary"
      placeholder="Summary (optional)"
    />

    <cdx-button action="destructive" weight="quiet" @click="emit('remove')">
      Remove
    </cdx-button>
  </div>
</template>
