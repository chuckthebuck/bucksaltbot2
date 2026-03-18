<script setup lang="ts">
import { computed, ref, watch, onMounted } from "vue";
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

const selected = ref<any>(null);
const menuItems = ref<Array<{ label: string; value: string }>>([]);
const users = ref<string[]>([]);
const selectedUser = ref("");
const summary = ref("");
const meta = ref("");
const inputValue = ref("");
const inputRef = ref<HTMLInputElement | null>(null);

const canEmit = computed(() => {
  return !!selected.value && typeof selected.value === "object" && !!selected.value.value && !!selectedUser.value;
});

onMounted(() => {
  // Try to find the input element inside CdxLookup and listen directly
  setTimeout(() => {
    const input = inputRef.value?.querySelector('input') as HTMLInputElement | null;
    if (input) {
      input.addEventListener('input', async (e) => {
        const value = (e.target as HTMLInputElement).value;
        console.log("🔥 direct input:", value);
        
        if (!value || !value.trim()) {
          menuItems.value = [];
          return;
        }

        menuItems.value = await searchTitles(value, props.namespaceId);
      });
    }
  }, 100);
});

watch(inputValue, async (value) => {
  console.log("🔥 watch inputValue:", value);

  if (!value || !value.trim()) {
    menuItems.value = [];
    return;
  }

  menuItems.value = await searchTitles(value, props.namespaceId);
});


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
    <CdxField ref="inputRef">
      <CdxLookup
        :selected="selected"
        v-model:input-value="inputValue"
        :menu-items="menuItems"
        placeholder="Search page"
        @update:selected="selected = $event"
      />
      <div class="lookup-meta">{{ meta }}</div>
    </CdxField>

    <CdxField>
      <CdxSelect
        :selected="selectedUser"
        :menu-items="users.map(u => ({ label: u, value: u }))"
        @update:selected="selectedUser = $event"
        class="lookup-user"
      />
    </CdxField>

    <CdxTextInput
      v-model="summary"
      class="item-summary"
      placeholder="Summary (optional)"
    />

    <CdxButton action="destructive" weight="quiet" @click="emit('remove')">
      Remove
    </CdxButton>
  </div>
</template>
