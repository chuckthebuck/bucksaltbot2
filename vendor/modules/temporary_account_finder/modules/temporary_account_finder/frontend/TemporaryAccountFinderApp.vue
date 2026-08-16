<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  CdxButton,
  CdxCheckbox,
  CdxMessage,
  CdxProgressBar,
  CdxSelect,
  CdxTextArea,
  CdxTextInput,
} from "@wikimedia/codex";

interface WikiInfo {
  host: string;
  url: string;
}

interface AccessResult {
  wiki: WikiInfo;
  username: string;
  eligible: boolean;
  blocked: boolean;
  reveal_rights: string[];
  on_wiki_reveal_rights: string[];
  oauth_grant_missing: boolean;
}

interface SeedResult {
  seed: string;
  connected_accounts: string[];
  ips_used_count: number;
  ip_addresses?: string[];
}

interface SeedError {
  seed: string;
  detail: string;
}

interface SearchResult {
  wiki: WikiInfo;
  requested_by: string;
  seed_accounts: string[];
  results: SeedResult[];
  errors: SeedError[];
  combined_accounts: string[];
  combined_count: number;
  complete: boolean;
  privacy: {
    contains_ip_addresses: boolean;
    ip_storage: string;
    ip_retention_days: number;
    authorization_checked_by: string[];
  };
}

interface InitialProps {
  username?: string;
  can_manage?: boolean;
}

const props = JSON.parse(
  document.getElementById("temporary-account-finder-props")?.textContent || "{}"
) as InitialProps;

const apiBase = "/api/v1/modules/temporary_account_finder/api";
const wikiOptions = [
  { label: "Meta-Wiki", value: "meta" },
  { label: "Wikimedia Commons", value: "commons" },
  { label: "English Wikipedia", value: "enwiki" },
  { label: "Wikidata", value: "wikidata" },
  { label: "Other Wikimedia wiki", value: "custom" },
];

const selectedWiki = ref<string | number | null>("meta");
const customWiki = ref("");
const accountsText = ref("");
const includeIps = ref(true);
const access = ref<AccessResult | null>(null);
const accessLoading = ref(false);
const searching = ref(false);
const error = ref("");
const result = ref<SearchResult | null>(null);
const copied = ref("");
let accessSequence = 0;

const wikiValue = computed(() =>
  selectedWiki.value === "custom"
    ? customWiki.value.trim()
    : String(selectedWiki.value || "")
);
const seeds = computed(() =>
  accountsText.value
    .split(/[\n,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
);
const eligible = computed(() => Boolean(access.value?.eligible));
const canSearch = computed(
  () =>
    eligible.value &&
    Boolean(wikiValue.value) &&
    seeds.value.length > 0 &&
    seeds.value.length <= 50 &&
    !searching.value
);

/** Read a JSON response and preserve the server's safe public error detail. */
async function responseJson<T>(response: Response): Promise<T> {
  const payload = (await response.json().catch(() => ({}))) as T & {
    detail?: string;
  };
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

/** Refresh the selected wiki's live user-right decision. */
async function checkAccess() {
  const sequence = ++accessSequence;
  access.value = null;
  result.value = null;
  error.value = "";
  if (!wikiValue.value) return;

  accessLoading.value = true;
  try {
    const response = await fetch(
      `${apiBase}/access?wiki=${encodeURIComponent(wikiValue.value)}`,
      { cache: "no-store", credentials: "same-origin" }
    );
    const payload = await responseJson<AccessResult>(response);
    if (sequence === accessSequence) access.value = payload;
  } catch (exception) {
    if (sequence === accessSequence) {
      error.value =
        exception instanceof Error ? exception.message : "Access check failed.";
    }
  } finally {
    if (sequence === accessSequence) accessLoading.value = false;
  }
}

/** Run one no-store investigation as the current OAuth user. */
async function search() {
  if (!canSearch.value) return;
  searching.value = true;
  error.value = "";
  result.value = null;
  try {
    const response = await fetch(`${apiBase}/search`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        wiki: wikiValue.value,
        accounts: accountsText.value,
        include_ips: includeIps.value,
      }),
    });
    result.value = await responseJson<SearchResult>(response);
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : "Search failed.";
  } finally {
    searching.value = false;
  }
}

/** Copy one investigation list without placing it in server-side state. */
async function copyList(key: string, values: string[]) {
  try {
    await navigator.clipboard.writeText(values.join("\n"));
    copied.value = key;
    window.setTimeout(() => {
      if (copied.value === key) copied.value = "";
    }, 1600);
  } catch {
    error.value = "The browser did not allow clipboard access.";
  }
}

/** Build a safe local-wiki contributions link for a temporary account. */
function contributionsUrl(account: string) {
  const host = result.value?.wiki.host || access.value?.wiki.host || "meta.wikimedia.org";
  return `https://${host}/wiki/Special:Contributions/${encodeURIComponent(account.replaceAll(" ", "_"))}`;
}

/** Build a safe local-wiki IPContributions link for transient IP evidence. */
function ipContributionsUrl(ip: string) {
  const host = result.value?.wiki.host || access.value?.wiki.host || "meta.wikimedia.org";
  return `https://${host}/wiki/Special:IPContributions/${encodeURIComponent(ip)}`;
}

/** Clear pasted targets and current results while retaining the wiki choice. */
function clearSearch() {
  accountsText.value = "";
  result.value = null;
  error.value = "";
}

watch(selectedWiki, checkAccess);
watch(customWiki, () => {
  if (selectedWiki.value === "custom") checkAccess();
});
onMounted(checkAccess);
</script>

<template>
  <main class="taf">
    <header class="taf__header">
      <div>
        <p class="taf__eyebrow">Chuckbot investigation module</p>
        <h1>Temporary Account Finder</h1>
        <p>Find related temporary accounts using your own on-wiki permissions.</p>
      </div>
      <span class="taf__identity">Requested by {{ props.username || "unknown user" }}</span>
    </header>

    <CdxMessage type="notice" class="taf__message">
      Every request is OAuth-signed as you. Chuckbot maintainer access does not
      replace TAIV on the selected wiki, and Wikimedia performs and logs the
      authoritative reveal check.
    </CdxMessage>

    <CdxMessage v-if="props.can_manage" type="warning" class="taf__message">
      You are a Chuckbot maintainer. That lets you administer this module, but
      searches remain disabled until your Wikimedia account has a reveal right on
      the selected wiki.
    </CdxMessage>

    <section class="taf__panel taf__controls">
      <div class="taf__field">
        <label for="taf-wiki">Wiki</label>
        <CdxSelect
          id="taf-wiki"
          v-model:selected="selectedWiki"
          :menu-items="wikiOptions"
        />
      </div>

      <div v-if="selectedWiki === 'custom'" class="taf__field">
        <label for="taf-custom-wiki">Wikimedia hostname</label>
        <CdxTextInput
          id="taf-custom-wiki"
          v-model="customWiki"
          placeholder="de.wikipedia.org"
          autocomplete="off"
        />
      </div>

      <div class="taf__access" aria-live="polite">
        <CdxProgressBar v-if="accessLoading" aria-label="Checking wiki rights" />
        <CdxMessage v-else-if="access?.eligible" type="success">
          Authorized as {{ access.username }} on {{ access.wiki.host }} via
          {{ access.reveal_rights.join(", ") }}.
        </CdxMessage>
        <CdxMessage v-else-if="access" type="error">
          <template v-if="access.blocked">
            Sitewide-blocked users cannot reveal temporary-account data on
            {{ access.wiki.host }}.
          </template>
          <template v-else-if="access.oauth_grant_missing">
            {{ access.username }} has {{ access.on_wiki_reveal_rights.join(", ") }}
            on {{ access.wiki.host }}, but Chuckbot's current OAuth authorization
            does not include that grant. A consumer owner must add or approve the
            checkuser-temporary-account grant if needed; then sign out and
            authorize Chuckbot again.
          </template>
          <template v-else>
            {{ access.username }} does not currently have a temporary-account
            reveal right on {{ access.wiki.host }}.
          </template>
        </CdxMessage>
      </div>

      <form class="taf__form" @submit.prevent="search">
        <div class="taf__field taf__targets">
          <div class="taf__label-row">
            <label for="taf-accounts">Temporary accounts</label>
            <span :class="{ 'taf__count--error': seeds.length > 50 }">
              {{ seeds.length }} / 50
            </span>
          </div>
          <CdxTextArea
            id="taf-accounts"
            v-model="accountsText"
            :rows="9"
            placeholder="~2026-12345&#10;~2026-67890"
          />
          <small>
            One per line. User: prefixes and Special:Contributions links are accepted.
          </small>
        </div>

        <CdxCheckbox v-model="includeIps">
          Show current IP evidence in this browser session
        </CdxCheckbox>
        <p v-if="includeIps" class="taf__retention">
          IPs are sent in a no-store response and are not written to Chuckbot
          databases, Redis, logs, jobs, or history. Current Chuckbot retention: 0 days.
        </p>

        <div class="taf__actions">
          <CdxButton
            type="submit"
            action="progressive"
            weight="primary"
            :disabled="!canSearch"
          >
            {{ searching ? "Searching…" : "Find connected accounts" }}
          </CdxButton>
          <CdxButton type="button" :disabled="searching" @click="clearSearch">
            Clear
          </CdxButton>
        </div>
      </form>
    </section>

    <CdxProgressBar v-if="searching" aria-label="Searching temporary accounts" />
    <CdxMessage v-if="error" type="error" class="taf__message">{{ error }}</CdxMessage>

    <section v-if="result" class="taf__results" aria-live="polite">
      <header class="taf__results-header">
        <div>
          <h2>{{ result.combined_count }} connected account{{ result.combined_count === 1 ? "" : "s" }}</h2>
          <p>
            {{ result.results.length }} of {{ result.seed_accounts.length }} seed
            lookups completed on {{ result.wiki.host }}.
          </p>
        </div>
        <CdxButton
          v-if="result.combined_accounts.length"
          @click="copyList('combined', result.combined_accounts)"
        >
          {{ copied === "combined" ? "Copied" : "Copy combined list" }}
        </CdxButton>
      </header>

      <CdxMessage v-if="result.errors.length" type="warning" class="taf__message">
        {{ result.errors.length }} lookup{{ result.errors.length === 1 ? "" : "s" }}
        failed. The successful results below are partial.
      </CdxMessage>

      <section class="taf__panel">
        <h3>Combined, deduplicated accounts</h3>
        <p v-if="!result.combined_accounts.length" class="taf__muted">
          No active connected accounts were returned in the wiki's retention window.
        </p>
        <ol v-else class="taf__account-grid">
          <li v-for="account in result.combined_accounts" :key="account">
            <a :href="contributionsUrl(account)" target="_blank" rel="noopener noreferrer">
              {{ account }}
            </a>
          </li>
        </ol>
      </section>

      <h3 class="taf__section-title">Results by seed</h3>
      <div class="taf__seed-grid">
        <article v-for="seedResult in result.results" :key="seedResult.seed" class="taf__seed-card">
          <header>
            <h4>
              <a :href="contributionsUrl(seedResult.seed)" target="_blank" rel="noopener noreferrer">
                {{ seedResult.seed }}
              </a>
            </h4>
            <span>
              {{ seedResult.connected_accounts.length }} accounts ·
              {{ seedResult.ips_used_count }} associated IPs
            </span>
          </header>

          <h5>Connected accounts</h5>
          <ul>
            <li v-for="account in seedResult.connected_accounts" :key="account">
              <a :href="contributionsUrl(account)" target="_blank" rel="noopener noreferrer">
                {{ account }}
              </a>
            </li>
          </ul>

          <template v-if="seedResult.ip_addresses">
            <div class="taf__subhead">
              <h5>Live IP evidence</h5>
              <CdxButton
                weight="quiet"
                size="small"
                @click="copyList(`ips:${seedResult.seed}`, seedResult.ip_addresses || [])"
              >
                {{ copied === `ips:${seedResult.seed}` ? "Copied" : "Copy" }}
              </CdxButton>
            </div>
            <p v-if="!seedResult.ip_addresses.length" class="taf__muted">
              No IPs were returned in the current CheckUser window.
            </p>
            <ul v-else class="taf__ips">
              <li v-for="ip in seedResult.ip_addresses" :key="ip">
                <a :href="ipContributionsUrl(ip)" target="_blank" rel="noopener noreferrer">
                  {{ ip }}
                </a>
              </li>
            </ul>
          </template>
        </article>

        <article v-for="failure in result.errors" :key="failure.seed" class="taf__seed-card taf__seed-card--error">
          <h4>{{ failure.seed }}</h4>
          <p>{{ failure.detail }}</p>
        </article>
      </div>

      <p class="taf__footnote">
        Relationships are investigative signals from the selected wiki's current
        CheckUser data, not proof that accounts are operated by the same person.
      </p>
    </section>
  </main>
</template>
