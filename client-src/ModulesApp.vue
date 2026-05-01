<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CdxButton, CdxProgressBar } from "@wikimedia/codex";
import { getInitialProps, fetchModules, toggleModuleEnabled, updateModuleAccess } from "./api";

interface Module {
  name: string;
  title: string;
  enabled: boolean;
  ui_enabled: boolean;
  has_access: boolean;
  redis_namespace: string;
  oauth_consumer_mode: string;
  cron_jobs: Array<{
    name: string;
    schedule: string;
    endpoint: string;
    timeout_seconds: number;
    enabled: boolean;
  }>;
}

const props = getInitialProps();
const canManageModules = computed(
  () => props.can_manage_modules ?? props.is_maintainer
);

const modules = ref<Module[]>([]);
const loading = ref(true);
const error = ref("");
const selectedModule = ref<string | null>(null);
const togglingModule = ref<string | null>(null);
const grantingAccess = ref<{ module: string; username: string } | null>(null);
const newAccessUsername = ref("");

async function loadModules() {
  try {
    loading.value = true;
    error.value = "";
    const data = await fetchModules();
    modules.value = data;
  } catch (err) {
    error.value = `Failed to load modules: ${String(err)}`;
    console.error(err);
  } finally {
    loading.value = false;
  }
}

async function toggleModule(moduleName: string, enabled: boolean) {
  try {
    togglingModule.value = moduleName;
    await toggleModuleEnabled(moduleName, enabled);
    await loadModules();
  } catch (err) {
    error.value = `Failed to toggle module: ${String(err)}`;
    console.error(err);
  } finally {
    togglingModule.value = null;
  }
}

async function grantAccess(moduleName: string, username: string) {
  if (!username.trim()) {
    error.value = "Username is required";
    return;
  }

  try {
    grantingAccess.value = { module: moduleName, username };
    await updateModuleAccess(moduleName, username, true);
    newAccessUsername.value = "";
    await loadModules();
  } catch (err) {
    error.value = `Failed to grant access: ${String(err)}`;
    console.error(err);
  } finally {
    grantingAccess.value = null;
  }
}

async function revokeAccess(moduleName: string, username: string) {
  try {
    grantingAccess.value = { module: moduleName, username };
    await updateModuleAccess(moduleName, username, false);
    await loadModules();
  } catch (err) {
    error.value = `Failed to revoke access: ${String(err)}`;
    console.error(err);
  } finally {
    grantingAccess.value = null;
  }
}

const selectedModuleData = computed(() => {
  return modules.value.find((m) => m.name === selectedModule.value) || null;
});

onMounted(() => {
  loadModules();
});
</script>

<template>
  <div class="modules-app">
    <h1>Module Management</h1>

    <div v-if="!canManageModules" class="cdx-message cdx-message--warning">
      <div class="cdx-message__content">
        You are not a maintainer and cannot manage modules.
      </div>
    </div>

    <div v-if="error" class="cdx-message cdx-message--error">
      <div class="cdx-message__content">{{ error }}</div>
      <button class="cdx-message__close-button" @click="error = ''" type="button">
        ✕
      </button>
    </div>

    <CdxProgressBar v-if="loading" :animated="true" />

    <div v-else class="modules-container">
      <section class="modules-list">
        <h2>Modules</h2>
        <div v-if="modules.length === 0" class="no-modules">
          <p>No modules currently registered.</p>
        </div>
        <div v-else class="module-items">
          <button
            v-for="module in modules"
            :key="module.name"
            class="module-item"
            :class="{ active: selectedModule === module.name }"
            @click="selectedModule = module.name"
          >
            <span class="module-name">{{ module.title || module.name }}</span>
            <span
              class="module-status"
              :class="{ enabled: module.enabled, disabled: !module.enabled }"
            >
              {{ module.enabled ? "Enabled" : "Disabled" }}
            </span>
          </button>
        </div>
      </section>

      <section v-if="selectedModuleData" class="module-detail">
        <div class="detail-header">
          <h2>{{ selectedModuleData.title || selectedModuleData.name }}</h2>
          <div v-if="isMaintainer" class="detail-actions">
            <CdxButton
              :disabled="togglingModule === selectedModuleData.name"
              @click="
                toggleModule(
                  selectedModuleData.name,
                  !selectedModuleData.enabled
                )
              "
            >
              {{
                togglingModule === selectedModuleData.name
                  ? "Updating..."
                  : selectedModuleData.enabled
                    ? "Disable"
                    : "Enable"
              }}
            </CdxButton>
          </div>
        </div>

        <div class="detail-info">
          <div class="info-row">
            <span class="label">Name:</span>
            <span class="value">{{ selectedModuleData.name }}</span>
          </div>
          <div class="info-row">
            <span class="label">Status:</span>
            <span
              class="value status"
              :class="{ enabled: selectedModuleData.enabled }"
            >
              {{ selectedModuleData.enabled ? "Enabled" : "Disabled" }}
            </span>
          </div>
          <div class="info-row">
            <span class="label">UI Enabled:</span>
            <span class="value">
              {{ selectedModuleData.ui_enabled ? "Yes" : "No" }}
            </span>
          </div>
          <div class="info-row">
            <span class="label">Redis Namespace:</span>
            <span class="value">{{ selectedModuleData.redis_namespace }}</span>
          </div>
          <div class="info-row">
            <span class="label">OAuth Consumer Mode:</span>
            <span class="value">{{ selectedModuleData.oauth_consumer_mode }}</span>
          </div>
        </div>

        <div v-if="selectedModuleData.cron_jobs.length > 0" class="cron-jobs">
          <h3>Cron Jobs</h3>
          <table class="cron-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Schedule</th>
                <th>Endpoint</th>
                <th>Timeout</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="job in selectedModuleData.cron_jobs" :key="job.name">
                <td>{{ job.name }}</td>
                <td><code>{{ job.schedule }}</code></td>
                <td><code>{{ job.endpoint }}</code></td>
                <td>{{ job.timeout_seconds }}s</td>
                <td :class="{ enabled: job.enabled }">
                  {{ job.enabled ? "Enabled" : "Disabled" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="selectedModuleData && isMaintainer" class="module-access">
        <h3>Access Control</h3>
        <p class="help-text">
          Maintainers have access to all modules by default. Grant additional users
          access below.
        </p>
        <div class="access-form">
          <input
            v-model="newAccessUsername"
            type="text"
            placeholder="Username"
            class="username-input"
            @keyup.enter="grantAccess(selectedModuleData!.name, newAccessUsername)"
          />
          <CdxButton
            :disabled="
              !newAccessUsername.trim() ||
              grantingAccess?.module === selectedModuleData.name
            "
            @click="grantAccess(selectedModuleData!.name, newAccessUsername)"
          >
            {{
              grantingAccess?.module === selectedModuleData.name
                ? "Granting..."
                : "Grant Access"
            }}
          </CdxButton>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped lang="less">
.modules-app {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

h1 {
  font-size: 2em;
  margin-bottom: 20px;
}

h2 {
  font-size: 1.5em;
  margin-bottom: 15px;
}

h3 {
  font-size: 1.2em;
  margin-top: 20px;
  margin-bottom: 10px;
}

.modules-container {
  display: grid;
  grid-template-columns: 250px 1fr;
  gap: 20px;
  margin-top: 20px;

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }
}

.modules-list {
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 15px;
  background-color: #f5f5f5;
}

.no-modules {
  padding: 20px;
  text-align: center;
  color: #666;
}

.module-items {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.module-item {
  padding: 10px 12px;
  border: 1px solid #ccc;
  background: white;
  border-radius: 4px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  justify-content: space-between;
  align-items: center;

  &:hover {
    background: #f9f9f9;
    border-color: #999;
  }

  &.active {
    background: #036;
    color: white;
    border-color: #036;
  }
}

.module-name {
  font-weight: 500;
  flex: 1;
}

.module-status {
  font-size: 0.85em;
  padding: 2px 6px;
  border-radius: 3px;
  background: #f0f0f0;
  color: #333;

  &.enabled {
    background: #d4edda;
    color: #155724;
  }

  &.disabled {
    background: #f8d7da;
    color: #721c24;
  }
}

.module-detail {
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 20px;
  background: white;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  border-bottom: 2px solid #eee;
  padding-bottom: 15px;
}

.detail-actions {
  display: flex;
  gap: 10px;
}

.detail-info {
  margin-bottom: 25px;
}

.info-row {
  display: grid;
  grid-template-columns: 150px 1fr;
  padding: 10px 0;
  border-bottom: 1px solid #eee;

  .label {
    font-weight: 600;
    color: #333;
  }

  .value {
    color: #666;

    &.status {
      font-weight: 600;

      &.enabled {
        color: #155724;
      }
    }

    code {
      background: #f5f5f5;
      padding: 2px 4px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 0.9em;
    }
  }
}

.cron-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;

  th {
    background: #f5f5f5;
    padding: 10px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #ddd;
  }

  td {
    padding: 10px;
    border-bottom: 1px solid #eee;

    code {
      background: #f5f5f5;
      padding: 2px 4px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 0.9em;
    }

    &.enabled {
      color: #155724;
      font-weight: 600;
    }
  }
}

.module-access {
  border-top: 2px solid #eee;
  padding-top: 20px;
  margin-top: 25px;
}

.help-text {
  color: #666;
  font-size: 0.95em;
  margin-bottom: 15px;
}

.access-form {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}

.username-input {
  flex: 1;
  max-width: 300px;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 0.95em;

  &:focus {
    outline: none;
    border-color: #036;
    box-shadow: 0 0 0 2px rgba(0, 51, 102, 0.1);
  }
}
</style>
