<script setup lang="ts">
// Privileged preview of the cron fragment derived from current module manifests.
import { onMounted, ref } from "vue";
import { CdxButton, CdxProgressBar, CdxCopyTextLayout } from "@wikimedia/codex";
import { getInitialProps } from "./api";

const props = getInitialProps();

const yamlContent = ref("");
const loading = ref(true);
const error = ref("");
const copied = ref(false);

async function fetchYamlPreview() {
  /** Refresh generated YAML and retain a user-readable request failure. */
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
  /** Copy the reviewed fragment and show a short-lived confirmation state. */
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
          <li>Copy the generated module-job block below</li>
          <li>Replace only the contents between <code># BEGIN GENERATED MODULE JOBS</code> and <code># END GENERATED MODULE JOBS</code> in the repository's checked <code>jobs.yaml</code></li>
          <li>Review and commit <code>jobs.yaml</code>, preserving its framework-owned jobs and marker lines</li>
          <li>Deploy the commit with the normal wrapper; it flushes Toolforge jobs and loads the committed file</li>
        </ol>
        <p><strong>Note:</strong> Saving a schedule updates ToolsDB only. Toolforge does not use it until the reviewed generated block is committed to <code>jobs.yaml</code> and that file is loaded.</p>
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
  background-color: #f6f9ff;
  border-left: 4px solid #315fa8;
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
  background-color: #eef5ff;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: monospace;
}

.yaml-section {
  border: 1px solid #a7bde5;
  border-radius: 4px;
  overflow: hidden;
}

.yaml-header {
  background-color: #f6f9ff;
  border-bottom: 1px solid #a7bde5;
  padding: 12px 15px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.yaml-header h3 {
  margin: 0;
}

.yaml-content {
  background-color: #fbfdff;
  padding: 15px;
  margin: 0;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  color: #202122;
}
</style>
