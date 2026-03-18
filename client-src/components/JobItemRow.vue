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
const fieldRef = ref<any>(null);

const canEmit = computed(() => {
  return !!selected.value && typeof selected.value === "object" && !!selected.value.value && !!selectedUser.value;
});

onMounted(() => {
  // Try to find the input element inside CdxField and listen directly
  setTimeout(() => {
    const fieldEl = fieldRef.value?.$el as HTMLElement | null;
    if (fieldEl) {
      const input = fieldEl.querySelector('input') as HTMLInputElement | null;
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

        // Listen for menu item clicks/selection
        input.addEventListener('keydown', (e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter') {
            console.log("🔥 keydown:", e.key, "menu items:", menuItems.value.length);
          }
        });

        // Listen for blur to capture selection
        input.addEventListener('blur', async (e) => {
          const value = (e.target as HTMLInputElement).value;
          console.log("🔥 blur with value:", value);
          
          // Check if value matches a menu item
          const match = menuItems.value.find(item => item.label === value);
          if (match) {
            console.log("🔥 matched menu item, loading editors");
            selected.value = match;
            await onSelectionChanged(match);
          }
        });
      }
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
  console.log("🔥 onSelectionChanged called with:", v);
  
  if (!v || typeof v !== "object" || !v.value) {
    users.value = [];
    selectedUser.value = "";
    meta.value = "";
    emit("update", null);
    return;
  }

  console.log("🔥 loading editors for:", v.value);
  const editorData = await loadEditorsForTitle(v.value);
  console.log("🔥 loaded editors:", editorData);
  
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
    <CdxField ref="fieldRef">
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
