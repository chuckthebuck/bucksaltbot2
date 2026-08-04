<script setup lang="ts">
/**
 * Account-based rollback request form.
 *
 * This client validates and queues a request; it never performs rollback work.
 * Server-side authorization, maintainer approval, and dry-run enforcement remain
 * authoritative even when the local controls offer a live-looking option.
 */
import { computed, ref } from "vue";
import {
  CdxButton,
  CdxCheckbox,
  CdxField,
  CdxLookup,
  CdxMessage,
  CdxTextInput,
  CdxTextArea
} from "@wikimedia/codex";
import { searchUsernames } from "./api";

// Server-rendered limits and capability constraints seed the form. They are UI
// guidance only and are revalidated by the request endpoint.
const props = JSON.parse(
  document.getElementById("from-account-props")!.textContent!
) as {
  username: string;
  default_limit?: number;
  max_limit?: number;
  from_diff_dry_run_only?: boolean;
};

// Lookup state is split between typed text, selected menu value, and menu rows
// because Codex lookups can submit either a chosen result or a manual username.
const account = ref("");
const accountLookupItems = ref<Array<{ label: string; value: string }>>([]);
const accountLookupSelected = ref<string | number | null>(null);
const accountLookupInputValue = ref("");
const accountLookupRequestId = ref(0);
const summary = ref("");
const dryRun = ref(Boolean(props.from_diff_dry_run_only));
const rollbackThroughBots = ref(false);
const limit = ref(String(props.default_limit ?? 500));

// Submission state is replaced per attempt so a prior success cannot remain
// visible while a different request is in flight.
const loading = ref(false);
const errors = ref<string[]>([]);
const result = ref<Record<string, unknown> | null>(null);

const maxLimit = computed(() => Number(props.max_limit ?? 500));

/** Prefer an explicit lookup selection, falling back to the current typed text. */
function resolveTargetAccount(): string {
  const selected = accountLookupSelected.value;
  const typed = accountLookupInputValue.value;
  const candidate =
    selected !== null && selected !== undefined && String(selected).trim()
      ? String(selected).trim()
      : String(typed || "").trim();

  return candidate;
}

/** Search usernames while preventing an older response from replacing a newer query. */
async function onAccountLookupInput(value: string | number): Promise<void> {
  const query = String(value || "").trim();
  accountLookupInputValue.value = query;
  const requestId = accountLookupRequestId.value + 1;
  accountLookupRequestId.value = requestId;

  if (!query) {
    accountLookupItems.value = [];
    return;
  }

  try {
    const users = await searchUsernames(query);
    // Network responses may arrive out of order as the operator types.
    if (accountLookupRequestId.value !== requestId) return;
    accountLookupItems.value = users;
  } catch {
    if (accountLookupRequestId.value !== requestId) return;
    accountLookupItems.value = [];
  }
}

/** Validate required input and the server-advertised positive limit bound. */
function validate(): boolean {
  errors.value = [];

  const trimmedAccount = resolveTargetAccount();
  if (!trimmedAccount) {
    errors.value.push("Account is required.");
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

/** Queue a normalized request and expose endpoint errors without mutating jobs locally. */
async function submit() {
  try {
    if (!validate()) {
      return;
    }

    loading.value = true;
    errors.value = [];
    result.value = null;

    const trimmedAccount = resolveTargetAccount();
    account.value = trimmedAccount;
    const trimmedSummary = String(summary.value ?? "").trim();
    const trimmedLimit = String(limit.value ?? "").trim();

    // The server decides whether the authenticated caller may request this mode
    // and whether dry-run-only policy overrides the submitted checkbox value.
    const response = await fetch("/api/v1/rollback/from-account", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        target_user: trimmedAccount,
        summary: trimmedSummary,
        dry_run: dryRun.value,
        rollback_through_bots: rollbackThroughBots.value,
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
    errors.value = ["Unable to queue account rollback jobs. Check inputs and try again."];
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="rollback-tool-section">
    <!-- Policy and request workflow guidance comes before editable controls. -->
    <CdxMessage type="notice" class="top-message">
      Submit an account rollback request. A maintainer must approve it before
      any rollback runs. Maximum allowed per request is {{ maxLimit }}.
    </CdxMessage>

    <CdxMessage v-if="props.from_diff_dry_run_only" type="warning" class="top-message">
      Your from-diff permission is currently dry-run-only. Live rollback submission is disabled.
    </CdxMessage>

    <!-- Form controls collect request intent only; approval occurs elsewhere. -->
    <div class="rollback-tool-form">
      <CdxField
        label="Target account"
        description="Username to roll back. You can include or omit the User: prefix."
      >
        <CdxLookup
          v-model:selected="accountLookupSelected"
          :menu-items="accountLookupItems"
          placeholder="Search Commons username"
          :disabled="loading"
          @input="onAccountLookupInput"
        />
      </CdxField>

      <CdxField
        label="Rollback limit"
        :description="`Maximum items to queue (1-${maxLimit}).`"
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

      <CdxCheckbox v-model="rollbackThroughBots" :disabled="loading">
        Roll back through top bot edits
      </CdxCheckbox>

      <CdxButton
        action="progressive"
        weight="primary"
        class="submit-button"
        :disabled="loading"
        @click="submit"
      >
        {{ loading ? "Submitting..." : "Submit account rollback request" }}
      </CdxButton>
    </div>

    <CdxMessage v-if="errors.length" type="error">
      <ul>
        <li v-for="err in errors" :key="err">{{ err }}</li>
      </ul>
    </CdxMessage>

    <!-- Preserve both a concise confirmation and raw response for audit/debugging. -->
    <CdxMessage v-if="result" type="success">
      Request submitted with status: {{ result.status }}.
      <br>
      Target account: {{ result.resolved_user }}
      <br>
      Batch ID: {{ result.batch_id }}
      <br>
      Requested by: {{ props.username }}
      <br>
      Open the <b>Request Review</b> tab to preview and approve.
    </CdxMessage>

    <pre v-if="result" class="log-pre">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>
</template>
