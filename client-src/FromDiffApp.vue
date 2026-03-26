<script setup lang="ts">
import { computed, ref } from "vue";
import {
  CdxButton,
  CdxCheckbox,
  CdxField,
  CdxMessage,
  CdxTextInput,
  CdxTextArea
} from "@wikimedia/codex";

const props = JSON.parse(
  document.getElementById("from-diff-props")!.textContent!
) as {
  username: string;
  default_limit?: number;
  max_limit?: number;
  from_diff_dry_run_only?: boolean;
};

const diff = ref("");
const summary = ref("");
const dryRun = ref(Boolean(props.from_diff_dry_run_only));
const limit = ref(String(props.default_limit ?? 100));

const loading = ref(false);
const errors = ref<string[]>([]);
const result = ref<Record<string, unknown> | null>(null);

const maxLimit = computed(() => Number(props.max_limit ?? 1000));

function validate(): boolean {
  errors.value = [];

  const trimmedDiff = String(diff.value ?? "").trim();

  if (!trimmedDiff) {
    errors.value.push("Diff is required.");
  }

  const trimmedLimit = String(limit.value ?? "").trim();

  if (trimmedLimit) {
    const parsedLimit = Number(trimmedLimit);

    if (!Number.isInteger(parsedLimit) || parsedLimit <= 0) {
      errors.value.push("Limit must be a positive integer.");
    } else if (parsedLimit > maxLimit.value) {
      errors.value.push(`Limit cannot exceed ${maxLimit.value}.`);
    }
  }

  return errors.value.length === 0;
}

async function submit() {
  try {
    if (!validate()) {
      return;
    }

    loading.value = true;
    errors.value = [];
    result.value = null;

    const trimmedDiff = String(diff.value ?? "").trim();
    const trimmedSummary = String(summary.value ?? "").trim();
    const trimmedLimit = String(limit.value ?? "").trim();

    const response = await fetch("/api/v1/rollback/from-diff", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        diff: trimmedDiff,
        summary: trimmedSummary,
        dry_run: dryRun.value,
        limit: trimmedLimit ? Number(trimmedLimit) : undefined
      })
    });

    const data = await response.json();

    if (!response.ok) {
      errors.value = [String(data?.detail || "Failed to create rollback jobs")];
      return;
    }

    result.value = data;
  } catch {
    errors.value = ["Unable to queue rollback jobs. Check inputs and try again."];
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="rollback-tool-section">
    <CdxMessage type="notice" class="top-message">
      Enter a diff oldid or URL. The tool resolves that revision's author and timestamp,
      then queues that author's edits after that timestamp.
    </CdxMessage>

    <CdxMessage v-if="props.from_diff_dry_run_only" type="warning" class="top-message">
      Your from-diff permission is currently dry-run-only. Live rollback submission is disabled.
    </CdxMessage>

    <div class="rollback-tool-form">
      <CdxField
        label="Diff oldid or URL"
        description="Example: 123456789 or a URL containing oldid=123456789."
      >
        <CdxTextInput
          v-model="diff"
          placeholder="https://commons.wikimedia.org/w/index.php?title=...&oldid=123456789"
          :disabled="loading"
        />
      </CdxField>

      <CdxField
        label="Rollback limit"
        :description="`Maximum items to queue from this diff onward (1-${maxLimit}).`"
      >
        <CdxTextInput
          v-model="limit"
          input-type="number"
          min="1"
          :max="String(maxLimit)"
          :disabled="loading"
        />
      </CdxField>

      <CdxField label="Summary override" description="Optional summary for all created items.">
        <CdxTextArea
          v-model="summary"
          rows="3"
          placeholder="Optional rollback summary"
          :disabled="loading"
        />
      </CdxField>

      <CdxCheckbox v-model="dryRun" :disabled="loading || props.from_diff_dry_run_only">
        Dry run (do not execute live rollback)
      </CdxCheckbox>

      <CdxButton
        action="progressive"
        weight="primary"
        class="submit-button"
        :disabled="loading"
        @click="submit"
      >
        {{ loading ? "Submitting..." : "Queue rollback jobs" }}
      </CdxButton>
    </div>

    <CdxMessage v-if="errors.length" type="error">
      <ul>
        <li v-for="err in errors" :key="err">{{ err }}</li>
      </ul>
    </CdxMessage>

    <CdxMessage v-if="result" type="success">
      Created {{ result.total_items }} items across {{ result.chunks }} job chunk(s).
      <br>
      Resolved author: {{ result.resolved_user }}
      <br>
      Batch ID: {{ result.batch_id }}
      <br>
      Requested by: {{ props.username }}
    </CdxMessage>

    <pre v-if="result" class="log-pre">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>
</template>
