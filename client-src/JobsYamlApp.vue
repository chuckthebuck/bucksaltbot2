<script setup lang="ts">
import { onMounted, ref } from "vue";
import { CdxButton, CdxProgressBar, CdxCopyTextLayout } from "@wikimedia/codex";
import { getInitialProps } from "./api";

const props = getInitialProps();

const yamlContent = ref("");
const loading = ref(true);
const error = ref("");
const copied = ref(false);

async function fetchYamlPreview() {
  try {
    loading.value = true;
    error.value = "";
    const resp = await fetch("/admin/jobs-yaml-preview");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    yamlContent.value = await resp.text();
  } catch (err) {
    error.value = `Failed to generate jobs.yaml: ${String(err)}`;
    console.error(err);
  } finally {
    loading.value = false;
  }
}

function copyToClipboard() {
  navigator.clipboard.writeText(yamlContent.value).then(() => {
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 2000);
  });
}

onMounted(() => {
  fetchYamlPreview();
});
</script>

<template>
  <div class="jobs-yaml-container">
    <h1>Toolforge jobs.yaml Generator</h1>
    
    <div v-if="loading" class="loading">
      <CdxProgressBar :inline="true" />
      <p>Generating jobs.yaml entries from module cron registry...</p>
    </div>

    <div v-else-if="error" class="error">
      <p><strong>Error:</strong> {{ error }}</p>
      <CdxButton @click="fetchYamlPreview">Retry</CdxButton>
    </div>

    <div v-else class="preview">
      <div class="instructions">
        <h2>Manual Workflow</h2>
        <ol>
          <li>Copy the YAML entries below</li>
          <li>Open <code>jobs.yaml</code> in the repo</li>
          <li>Add the entries to the appropriate section (keeping existing framework jobs)</li>
          <li>Commit and push to trigger Toolforge redeploy</li>
        </ol>
        <p><strong>Note:</strong> Module cron jobs don't auto-update when modules are installed/removed. Regenerate and update manually as needed.</p>
      </div>

      <div class="yaml-section">
        <div class="yaml-header">
          <h3>Generated jobs.yaml Entries</h3>
          <CdxButton
            :aria-label="copied ? 'Copied!' : 'Copy to clipboard'"
            @click="copyToClipboard"
          >
            {{ copied ? "✓ Copied" : "📋 Copy" }}
          </CdxButton>
        </div>
        <pre class="yaml-content">{{ yamlContent }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.jobs-yaml-container {
  padding: 20px;
  max-width: 1000px;
  margin: 0 auto;
}

h1 {
  margin-top: 0;
}

.loading {
  text-align: center;
  padding: 40px;
}

.error {
  background-color: #fee;
  border: 1px solid #fcc;
  border-radius: 4px;
  padding: 15px;
  margin-bottom: 20px;
}

.instructions {
  background-color: #f5f5f5;
  border-left: 4px solid #036;
  padding: 15px;
  margin-bottom: 20px;
  border-radius: 4px;
}

.instructions ol {
  margin: 10px 0;
  padding-left: 20px;
}

.instructions li {
  margin: 8px 0;
}

code {
  background-color: #eee;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: monospace;
}

.yaml-section {
  border: 1px solid #ccc;
  border-radius: 4px;
  overflow: hidden;
}

.yaml-header {
  background-color: #f9f9f9;
  border-bottom: 1px solid #ccc;
  padding: 12px 15px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.yaml-header h3 {
  margin: 0;
}

.yaml-content {
  background-color: #fafafa;
  padding: 15px;
  margin: 0;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  color: #333;
}
</style>
