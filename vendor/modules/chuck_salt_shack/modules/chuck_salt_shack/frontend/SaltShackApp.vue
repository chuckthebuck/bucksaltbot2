<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  CdxAccordion,
  CdxButton,
  CdxCheckbox,
  CdxField,
  CdxInfoChip,
  CdxLookup,
  CdxMessage,
  CdxMultiselectLookup,
  CdxSelect,
  CdxTab,
  CdxTabs,
  CdxTextArea,
  CdxTextInput,
  type ChipInputItem,
  type MenuItemData,
} from "@wikimedia/codex";
import logoUrl from "../assets/salt-shack-logo.svg";

// These interfaces mirror the public, execution-detail-free API contract.
interface NamespacePolicy {
  selectable: boolean;
  allowed: number[];
  default: number | null;
}

interface InputContract {
  type: string;
  label: string;
  description?: string;
  required?: boolean;
  default?: unknown;
  choices?: Array<{ value: unknown; label: string }>;
  minimum?: number;
  maximum?: number;
  max_items?: number;
  namespace?: NamespacePolicy;
  wiki_input?: string;
}

interface OutputContract {
  type: string;
  label: string;
  description?: string;
  optional?: boolean;
  columns?: Record<string, OutputContract>;
}

interface SaltlickContract {
  contract: number;
  id: string;
  display_name: string;
  description: string;
  generated: boolean;
  source_digest: string;
  inputs: Record<string, InputContract>;
  outputs: Record<string, OutputContract>;
  actions: { allowed: string[] };
}

interface AuthState {
  username?: string;
  can_preview?: boolean;
  can_apply?: boolean;
  can_manage?: boolean;
}

interface FieldState {
  value: any;
  text: string;
  namespace: number | null;
  selected: any;
  chips: ChipInputItem[];
}

interface WikiOption {
  code: string;
  family: string;
  label: string;
  url: string;
}

interface NamespaceOption {
  id: number;
  label: string;
  aliases: string[];
}

interface RunResult {
  ok: boolean;
  saltlick: { id: string; display_name: string; source_digest: string };
  outputs: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  action_result: {
    ok: boolean;
    dry_run: boolean;
    planned_count: number;
    completed_count: number;
    error_count: number;
    items: Array<Record<string, any>>;
  };
  dry_run: boolean;
  plan_token: string;
}

interface RunRow {
  id: number;
  job_name: string;
  status: string;
  triggered_by?: string;
  created_at?: string;
  error?: string;
  result?: RunResult;
}

// Namespace and wiki fallbacks keep Codex inputs usable if a public Wikimedia
// discovery request is temporarily unavailable. Successful requests replace
// these with live site-matrix and siteinfo data.
const COMMON_NAMESPACES: Array<[number, string]> = [
  [-2, "Media"],
  [-1, "Special"],
  [0, "(Main)"],
  [1, "Talk"],
  [2, "User"],
  [3, "User talk"],
  [4, "Project"],
  [5, "Project talk"],
  [6, "File"],
  [7, "File talk"],
  [10, "Template"],
  [11, "Template talk"],
  [14, "Category"],
  [15, "Category talk"],
  [100, "Portal"],
  [118, "Draft"],
];
const NAMESPACE_BY_PREFIX = new Map(
  COMMON_NAMESPACES.filter(([id]) => id >= 0).map(([id, label]) => [
    label.toLowerCase(),
    id,
  ]),
);
const WIKI_FALLBACKS: WikiOption[] = [
  {
    code: "commons",
    family: "commons",
    label: "Wikimedia Commons",
    url: "https://commons.wikimedia.org",
  },
  {
    code: "wikidata",
    family: "wikidata",
    label: "Wikidata",
    url: "https://www.wikidata.org",
  },
  {
    code: "meta",
    family: "meta",
    label: "Meta-Wiki",
    url: "https://meta.wikimedia.org",
  },
  {
    code: "en",
    family: "wikipedia",
    label: "English Wikipedia",
    url: "https://en.wikipedia.org",
  },
  {
    code: "de",
    family: "wikipedia",
    label: "German Wikipedia",
    url: "https://de.wikipedia.org",
  },
  {
    code: "fr",
    family: "wikipedia",
    label: "French Wikipedia",
    url: "https://fr.wikipedia.org",
  },
  {
    code: "es",
    family: "wikipedia",
    label: "Spanish Wikipedia",
    url: "https://es.wikipedia.org",
  },
];

// Catalog, form, and run state are kept in the module bundle. The framework
// still owns authentication, permissions, job persistence, and cancellation.
const auth = ref<AuthState>({});
const saltlicks = ref<SaltlickContract[]>([]);
const selectedId = ref("");
const nestedTab = ref("run");
const fields = ref<Record<string, FieldState>>({});
const draftCache = new Map<string, Record<string, FieldState>>();
const argumentsText = ref("");
const argumentCache = new Map<string, string>();
const busy = ref(false);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const runId = ref<number | null>(null);
const runStatus = ref("");
const result = ref<RunResult | null>(null);
const history = ref<RunRow[]>([]);
const wikiCatalog = ref<WikiOption[]>(WIKI_FALLBACKS);
const wikiLookupItems = ref<Record<string, MenuItemData[]>>({});
const pageLookupItems = ref<Record<string, MenuItemData[]>>({});
const namespaceCatalog = ref<Record<string, NamespaceOption[]>>({});
const wikiLookupRequestIds = new Map<string, number>();
const pageLookupRequestIds = new Map<string, number>();

// Derived state drives the contract-generated form and ensures Apply is only
// offered for the exact action plan returned by a successful preview.
const selectedContract = computed(
  () => saltlicks.value.find((item) => item.id === selectedId.value) ?? null,
);
const inputEntries = computed(() =>
  Object.entries(selectedContract.value?.inputs ?? {}),
);
const outputEntries = computed(() =>
  Object.entries(selectedContract.value?.outputs ?? {}),
);
const previewCanApply = computed(
  () =>
    Boolean(auth.value.can_apply) &&
    Boolean(result.value?.dry_run) &&
    Boolean(result.value?.plan_token) &&
    (result.value?.actions?.length ?? 0) > 0,
);

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// Contract form lifecycle. Drafts are cached per Saltlick so switching between
// nested catalog entries does not discard maintainer input.
function defaultNamespace(spec: InputContract): number | null {
  if (spec.namespace?.default !== null && spec.namespace?.default !== undefined) {
    return spec.namespace.default;
  }
  if (spec.namespace?.allowed?.length === 1) return spec.namespace.allowed[0];
  return 0;
}

function makeFieldState(
  overrides: Partial<FieldState> = {},
): FieldState {
  return {
    value: "",
    text: "",
    namespace: null,
    selected: null,
    chips: [],
    ...overrides,
  };
}

function wikiKey(value: { code?: unknown; family?: unknown }): string {
  const code = String(value?.code ?? "").trim().toLowerCase();
  const family = String(value?.family ?? "").trim().toLowerCase();
  return `${family}:${code}`;
}

function initialField(spec: InputContract): FieldState {
  const defaultValue = spec.default !== undefined ? clone(spec.default) : undefined;
  if (spec.type === "wiki") {
    const wiki = defaultValue ?? { code: "commons", family: "commons" };
    return makeFieldState({
      selected: wikiKey(wiki),
      value: wiki,
    });
  }
  if (spec.type === "page") {
    const page = (defaultValue as Record<string, unknown> | undefined) ?? {};
    const title = String(page.title ?? "");
    return makeFieldState({
      value: page,
      text: title,
      selected: title || null,
      namespace: Number(page.namespace ?? defaultNamespace(spec)),
    });
  }
  if (spec.type === "pages") {
    const pages = Array.isArray(defaultValue) ? defaultValue : [];
    const titles = pages.map((page) => String(page?.title ?? "")).filter(Boolean);
    return makeFieldState({
      value: pages,
      selected: titles,
      chips: titles.map((title) => ({ value: title, label: title })),
      namespace: defaultNamespace(spec),
    });
  }
  if (spec.type === "boolean") {
    return makeFieldState({
      value: Boolean(defaultValue ?? false),
    });
  }
  if (spec.type === "choice") {
    return makeFieldState({
      value: defaultValue ?? spec.choices?.[0]?.value ?? null,
    });
  }
  return makeFieldState({
    value: defaultValue ?? "",
  });
}

function initializeFields(contract: SaltlickContract) {
  const cached = draftCache.get(contract.id);
  if (cached) {
    fields.value = clone(cached);
    argumentsText.value = argumentCache.get(contract.id) ?? "";
    return;
  }
  fields.value = Object.fromEntries(
    Object.entries(contract.inputs).map(([name, spec]) => [
      name,
      initialField(spec),
    ]),
  );
  argumentsText.value = "";
}

function selectSaltlick(id: string) {
  if (selectedId.value) {
    draftCache.set(selectedId.value, clone(fields.value));
    argumentCache.set(selectedId.value, argumentsText.value);
  }
  selectedId.value = id;
  const contract = saltlicks.value.find((item) => item.id === id);
  if (contract) initializeFields(contract);
  nestedTab.value = "run";
  result.value = null;
  runId.value = null;
  runStatus.value = "";
  history.value = [];
  error.value = "";
  notice.value = "";
  if (contract) void prepareContractLookups(contract);
}

// Wikimedia discovery helpers power Codex wiki, namespace, and page lookups.
// Public API requests are intentionally separate from the module run endpoint.
function wikiFromKey(key: unknown): { code: string; family: string } | null {
  const [family, code] = String(key ?? "").split(":", 2);
  if (!code || !family) return null;
  return { code, family };
}

function wikiSiteUrl(wiki: { code: string; family: string }): string {
  if (wiki.family === "commons") return "https://commons.wikimedia.org";
  if (wiki.family === "wikidata") return "https://www.wikidata.org";
  if (wiki.family === "mediawiki") return "https://www.mediawiki.org";
  if (["meta", "species", "incubator", "foundation"].includes(wiki.family)) {
    return `https://${wiki.family}.wikimedia.org`;
  }
  return `https://${wiki.code}.${wiki.family}.org`;
}

function wikiApiUrl(wiki: { code: string; family: string }): string {
  return `${wikiSiteUrl(wiki)}/w/api.php`;
}

function wikiFromHostname(hostname: string): { code: string; family: string } | null {
  const host = hostname.toLowerCase().replace(/^www\./, "");
  const special: Record<string, { code: string; family: string }> = {
    "commons.wikimedia.org": { code: "commons", family: "commons" },
    "wikidata.org": { code: "wikidata", family: "wikidata" },
    "meta.wikimedia.org": { code: "meta", family: "meta" },
    "species.wikimedia.org": { code: "species", family: "species" },
    "mediawiki.org": { code: "mediawiki", family: "mediawiki" },
    "incubator.wikimedia.org": { code: "incubator", family: "incubator" },
    "foundation.wikimedia.org": { code: "foundation", family: "foundation" },
  };
  if (special[host]) return special[host];
  const match = host.match(
    /^([a-z0-9-]+)\.(wikipedia|wiktionary|wikibooks|wikinews|wikiquote|wikisource|wikiversity|wikivoyage)\.org$/,
  );
  return match ? { code: match[1], family: match[2] } : null;
}

function wikiMenuItem(option: WikiOption): MenuItemData {
  return {
    value: wikiKey(option),
    label: option.label,
    supportingText: `${option.code}:${option.family}`,
  };
}

async function loadWikiCatalog(): Promise<void> {
  try {
    const params = new URLSearchParams({
      action: "sitematrix",
      format: "json",
      formatversion: "2",
      origin: "*",
      smsiteprop: "code|sitename|url",
    });
    const response = await fetch(
      `https://meta.wikimedia.org/w/api.php?${params.toString()}`,
    );
    if (!response.ok) throw new Error(`Wiki catalog HTTP ${response.status}`);
    const body = await response.json();
    const matrix = body?.sitematrix ?? {};
    const options = [...WIKI_FALLBACKS];
    for (const group of Object.values(matrix) as Array<
      Record<string, any> | Array<Record<string, any>>
    >) {
      const sites = Array.isArray(group) ? group : group?.site;
      if (!Array.isArray(sites)) continue;
      const groupName = Array.isArray(group) ? "" : group.name;
      for (const site of sites) {
        if (!site?.url || site.closed || site.private) continue;
        try {
          const wiki = wikiFromHostname(new URL(site.url).hostname);
          if (!wiki) continue;
          options.push({
            ...wiki,
            label:
              String(site.sitename || "").trim() ||
              `${String(groupName || wiki.code)} ${wiki.family}`,
            url: String(site.url),
          });
        } catch {
          // Ignore malformed third-party entries in the site matrix.
        }
      }
    }
    const unique = new Map<string, WikiOption>();
    for (const option of options) unique.set(wikiKey(option), option);
    wikiCatalog.value = [...unique.values()].sort((left, right) =>
      left.label.localeCompare(right.label),
    );
  } catch {
    wikiCatalog.value = [...WIKI_FALLBACKS];
  }
}

function setWikiLookupItems(name: string, query = ""): void {
  const normalized = query.trim().toLowerCase();
  const options = [...wikiCatalog.value];
  const current = fields.value[name]?.value;
  if (current?.code && current?.family && !options.some(
    (option) => wikiKey(option) === wikiKey(current),
  )) {
    options.unshift({
      code: String(current.code),
      family: String(current.family),
      label: `${current.code}:${current.family}`,
      url: wikiSiteUrl(current),
    });
  }
  const items = options
    .filter((option) => {
      if (!normalized) return true;
      return (
        option.label.toLowerCase().includes(normalized) ||
        option.code.includes(normalized) ||
        option.family.includes(normalized) ||
        wikiKey(option).includes(normalized)
      );
    })
    .slice(0, 20)
    .map(wikiMenuItem);
  wikiLookupItems.value = { ...wikiLookupItems.value, [name]: items };
}

function onWikiLookupInput(name: string, value: string | number): void {
  const requestId = (wikiLookupRequestIds.get(name) ?? 0) + 1;
  wikiLookupRequestIds.set(name, requestId);
  fields.value[name].text = String(value ?? "");
  setWikiLookupItems(name, fields.value[name].text);
}

function linkedWikiName(spec: InputContract): string | undefined {
  if (spec.wiki_input) return spec.wiki_input;
  return inputEntries.value.find(([, candidate]) => candidate.type === "wiki")?.[0];
}

function linkedWiki(spec: InputContract): { code: string; family: string } {
  const name = linkedWikiName(spec);
  const value = name ? fields.value[name]?.value : null;
  return {
    code: String(value?.code ?? "commons"),
    family: String(value?.family ?? "commons"),
  };
}

async function loadNamespacesForWiki(
  wiki: { code: string; family: string },
): Promise<void> {
  const key = wikiKey(wiki);
  if (namespaceCatalog.value[key]) return;
  try {
    const params = new URLSearchParams({
      action: "query",
      meta: "siteinfo",
      siprop: "namespaces|namespacealiases",
      format: "json",
      formatversion: "2",
      origin: "*",
    });
    const response = await fetch(`${wikiApiUrl(wiki)}?${params.toString()}`);
    if (!response.ok) throw new Error(`Namespace HTTP ${response.status}`);
    const body = await response.json();
    const rawNamespaces = body?.query?.namespaces ?? {};
    const rawAliases = body?.query?.namespacealiases ?? [];
    const aliases = new Map<number, string[]>();
    for (const alias of rawAliases) {
      const id = Number(alias.id);
      const name = String(alias.alias ?? alias["*"] ?? "").trim();
      if (!name) continue;
      aliases.set(id, [...(aliases.get(id) ?? []), name]);
    }
    const options = Object.entries(rawNamespaces)
      .map(([rawId, rawValue]) => {
        const value = rawValue as Record<string, unknown>;
        const id = Number(value.id ?? rawId);
        const label = String(
          value.name ?? value["*"] ?? value.canonical ?? "",
        ).trim();
        const canonical = String(value.canonical ?? "").trim();
        return {
          id,
          label: label || "(Main)",
          aliases: [
            ...new Set(
              [label, canonical, ...(aliases.get(id) ?? [])].filter(Boolean),
            ),
          ],
        };
      })
      .filter((option) => Number.isInteger(option.id))
      .sort((left, right) => left.id - right.id);
    namespaceCatalog.value = {
      ...namespaceCatalog.value,
      [key]: options,
    };
  } catch {
    namespaceCatalog.value = {
      ...namespaceCatalog.value,
      [key]: COMMON_NAMESPACES.map(([id, label]) => ({
        id,
        label,
        aliases: label === "(Main)" ? [] : [label],
      })),
    };
  }
}

async function prepareContractLookups(contract: SaltlickContract): Promise<void> {
  for (const [name, spec] of Object.entries(contract.inputs)) {
    if (spec.type === "wiki") setWikiLookupItems(name);
  }
  const wikis = new Map<string, { code: string; family: string }>();
  for (const spec of Object.values(contract.inputs)) {
    if (!["namespace", "page", "pages"].includes(spec.type)) continue;
    const wiki = linkedWiki(spec);
    wikis.set(wikiKey(wiki), wiki);
  }
  await Promise.all([...wikis.values()].map(loadNamespacesForWiki));
}

function namespaceOptions(spec: InputContract): NamespaceOption[] {
  const wiki = linkedWiki(spec);
  return (
    namespaceCatalog.value[wikiKey(wiki)] ??
    COMMON_NAMESPACES.map(([id, label]) => ({
      id,
      label,
      aliases: label === "(Main)" ? [] : [label],
    }))
  );
}

function namespaceItems(spec: InputContract): MenuItemData[] {
  const allowed = spec.namespace?.allowed ?? [];
  return namespaceOptions(spec)
    .filter((option) => !allowed.length || allowed.includes(option.id))
    .map((option) => ({
      value: option.id,
      label: `${option.label} (${option.id})`,
    }));
}

function namespaceLabel(spec: InputContract, namespace: number | null): string {
  const value = namespace ?? defaultNamespace(spec);
  const option = namespaceOptions(spec).find((item) => item.id === value);
  return option ? `${option.label} (${option.id})` : `Namespace ${value}`;
}

function clearPageLookup(name: string): void {
  fields.value[name].selected = Array.isArray(fields.value[name].selected)
    ? []
    : null;
  fields.value[name].chips = [];
  fields.value[name].text = "";
  pageLookupItems.value = { ...pageLookupItems.value, [name]: [] };
}

function onNamespaceSelected(name: string, value: string | number | null): void {
  fields.value[name].namespace = value === null ? null : Number(value);
  clearPageLookup(name);
}

async function onWikiSelected(
  name: string,
  selected: string | number | null,
): Promise<void> {
  const wiki = wikiFromKey(selected);
  if (!wiki) return;
  fields.value[name].value = wiki;
  fields.value[name].text = "";
  const contract = selectedContract.value;
  if (contract) {
    for (const [fieldName, spec] of Object.entries(contract.inputs)) {
      if (
        ["namespace", "page", "pages"].includes(spec.type) &&
        linkedWikiName(spec) === name
      ) {
        if (["page", "pages"].includes(spec.type)) clearPageLookup(fieldName);
      }
    }
  }
  await loadNamespacesForWiki(wiki);
}

function stripNamespacePrefix(
  title: string,
  namespace: number,
  spec: InputContract,
): string {
  if (namespace === 0) return title;
  const option = namespaceOptions(spec).find((item) => item.id === namespace);
  const prefixes = option?.aliases ?? [];
  const lower = title.toLowerCase();
  for (const prefix of prefixes) {
    if (lower.startsWith(`${prefix.toLowerCase()}:`)) {
      return title.slice(prefix.length + 1).trim();
    }
  }
  return title;
}

async function onPageLookupInput(
  name: string,
  spec: InputContract,
  value: string | number,
): Promise<void> {
  const query = String(value ?? "").trim();
  fields.value[name].text = query;
  const requestId = (pageLookupRequestIds.get(name) ?? 0) + 1;
  pageLookupRequestIds.set(name, requestId);
  if (!query) {
    pageLookupItems.value = { ...pageLookupItems.value, [name]: [] };
    return;
  }
  pageLookupItems.value = {
    ...pageLookupItems.value,
    [name]: [
      {
        value: `__saltlick_searching_${name}`,
        label: "Searching…",
        disabled: true,
      },
    ],
  };
  const wiki = linkedWiki(spec);
  const namespace = Number(fields.value[name].namespace ?? defaultNamespace(spec));
  try {
    const params = new URLSearchParams({
      action: "opensearch",
      search: query,
      limit: "10",
      namespace: String(namespace),
      format: "json",
      origin: "*",
    });
    const response = await fetch(`${wikiApiUrl(wiki)}?${params.toString()}`);
    if (!response.ok) throw new Error(`Page lookup HTTP ${response.status}`);
    const body = await response.json();
    if (pageLookupRequestIds.get(name) !== requestId) return;
    const titles = Array.isArray(body?.[1]) ? body[1] : [];
    pageLookupItems.value = {
      ...pageLookupItems.value,
      [name]: titles.map((rawTitle: unknown) => {
        const title = String(rawTitle);
        return {
          value: stripNamespacePrefix(title, namespace, spec),
          label: title,
        };
      }),
    };
  } catch {
    if (pageLookupRequestIds.get(name) !== requestId) return;
    pageLookupItems.value = { ...pageLookupItems.value, [name]: [] };
  }
}

// Contract serialization is the only data sent to a Saltlick run: child ID,
// typed inputs, and optional compatibility arguments—never Python source.
function choiceItems(spec: InputContract): MenuItemData[] {
  return (spec.choices ?? []).map((choice) => ({
    value: choice.value as string | number,
    label: choice.label,
  }));
}

function inputType(spec: InputContract) {
  if (spec.type === "integer" || spec.type === "number") return "number";
  if (spec.type === "date") return "date";
  if (spec.type === "datetime") return "datetime-local";
  return "text";
}

function parsePageTitle(raw: string, fallbackNamespace: number | null) {
  const title = raw.trim();
  const separator = title.indexOf(":");
  if (separator > 0) {
    const prefix = title.slice(0, separator).trim().toLowerCase();
    const namespace = NAMESPACE_BY_PREFIX.get(prefix);
    if (namespace !== undefined) {
      return {
        namespace,
        title: title.slice(separator + 1).trim(),
      };
    }
  }
  return {
    namespace: fallbackNamespace ?? 0,
    title,
  };
}

function buildInputs() {
  const contract = selectedContract.value;
  if (!contract) return {};
  const inputs: Record<string, unknown> = {};
  for (const [name, spec] of Object.entries(contract.inputs)) {
    const state = fields.value[name];
    if (spec.type === "wiki") {
      inputs[name] = wikiFromKey(state.selected) ?? clone(state.value);
    } else if (spec.type === "page") {
      inputs[name] = parsePageTitle(
        String(state.selected ?? state.text ?? ""),
        state.namespace,
      );
    } else if (spec.type === "pages") {
      const selected = Array.isArray(state.selected) ? state.selected : [];
      inputs[name] = selected
        .map((title) => String(title).trim())
        .filter(Boolean)
        .map((title) => parsePageTitle(title, state.namespace));
    } else if (spec.type === "integer") {
      inputs[name] = Number.parseInt(String(state.value), 10);
    } else if (spec.type === "number") {
      inputs[name] = Number.parseFloat(String(state.value));
    } else {
      inputs[name] = clone(state.value);
    }
  }
  return inputs;
}

function buildArguments() {
  return argumentsText.value
    .split(/\r?\n/)
    .map((argument) => argument.trim())
    .filter(Boolean);
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(path, {
    cache: "no-store",
    ...init,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
  return body;
}

// Bootstrap capabilities and the compiled Saltlick registry from the framework-
// registered module blueprint. A failed API must not masquerade as an empty
// image, so the empty-catalog warning is suppressed when `error` is populated.
onMounted(async () => {
  try {
    const catalogPromise = loadWikiCatalog();
    const [authBody, registryBody] = await Promise.all([
      requestJson("/api/v1/modules/chuck_salt_shack/auth"),
      requestJson("/api/v1/modules/chuck_salt_shack/saltlicks"),
    ]);
    auth.value = authBody;
    saltlicks.value = Array.isArray(registryBody.saltlicks)
      ? registryBody.saltlicks
      : [];
    if (saltlicks.value.length) selectSaltlick(saltlicks.value[0].id);
    void catalogPromise.then(() => {
      if (selectedContract.value) void prepareContractLookups(selectedContract.value);
    });
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Could not load Salt Shack";
  } finally {
    loading.value = false;
  }
});

watch(nestedTab, async (tab) => {
  if (tab === "history" && selectedId.value) await loadHistory();
});

async function loadHistory() {
  try {
    const body = await requestJson(
      `/api/v1/modules/chuck_salt_shack/saltlicks/${encodeURIComponent(selectedId.value)}/runs`,
    );
    history.value = Array.isArray(body.runs) ? body.runs : [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Could not load run history";
  }
}

async function startRun(mode: "preview" | "apply") {
  const contract = selectedContract.value;
  if (!contract) return;
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const payload: Record<string, unknown> = {
      mode,
      inputs: buildInputs(),
      arguments: buildArguments(),
    };
    if (mode === "apply") {
      payload.confirm_live = true;
      payload.preview_token = result.value?.plan_token ?? "";
    } else {
      result.value = null;
    }
    const body = await requestJson(
      `/api/v1/modules/chuck_salt_shack/saltlicks/${encodeURIComponent(contract.id)}/runs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    runId.value = Number(body.run_id);
    runStatus.value = "queued";
    notice.value =
      mode === "preview" ? "Dry preview queued." : "Approved action plan queued.";
    await pollRun(runId.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Saltlick run failed";
  } finally {
    busy.value = false;
  }
}

async function pollRun(id: number) {
  for (let attempt = 0; attempt < 360; attempt += 1) {
    const body = await requestJson(`/api/v1/modules/chuck_salt_shack/runs/${id}`);
    runStatus.value = String(body.status || "unknown");
    if (body.status === "completed") {
      result.value = body.result as RunResult;
      notice.value = result.value?.dry_run
        ? "Preview complete. Review the outputs and action plan."
        : "Action plan completed.";
      return;
    }
    if (body.status === "failed" || body.status === "canceled") {
      throw new Error(body.error || `Run ${body.status}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("Run is still pending after six minutes.");
}

// Results are display-only structured output. Live execution remains in the
// framework action catalog and isolated module runner.
function pageLabel(value: any): string {
  if (!value || typeof value !== "object") return String(value ?? "");
  const namespace = Number(value.namespace ?? 0);
  const prefix = COMMON_NAMESPACES.find(([id]) => id === namespace)?.[1];
  const title = String(value.title ?? "");
  if (namespace === 0 || !prefix || title.includes(":")) return title;
  return `${prefix}:${title}`;
}

function wikiUrl(value: any): string {
  const wiki = value?.wiki ?? {};
  const family = String(wiki.family ?? "commons");
  const code = String(wiki.code ?? "commons");
  const host =
    family === "wikipedia"
      ? `${code}.wikipedia.org`
      : family === "commons"
        ? "commons.wikimedia.org"
        : `${code}.${family}.org`;
  return `https://${host}/wiki/${encodeURIComponent(pageLabel(value).replace(/ /g, "_"))}`;
}

function displayValue(value: unknown, type: string): string {
  if (type === "page") return pageLabel(value);
  if (type === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value ?? "");
}

function statusType(ok: boolean | undefined) {
  return ok === false ? "error" : "success";
}

function formatDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}
</script>

<template>
  <main class="salt-shack">
    <!-- Salt Shack owns this nested module surface; the framework owns the
         surrounding header, primary navigation, permissions, and footer. -->
    <header class="ss-header">
      <img :src="logoUrl" alt="" class="ss-logo" />
      <div>
        <h1>Salt Shack</h1>
        <p v-if="loading">Loading installed Saltlicks…</p>
        <p v-else-if="error">Saltlick registry unavailable</p>
        <p v-else>
          {{ saltlicks.length }} Saltlick{{ saltlicks.length === 1 ? "" : "s" }}
          discovered in this image
        </p>
      </div>
    </header>

    <cdx-message v-if="error" type="error" class="ss-message">
      {{ error }}
    </cdx-message>
    <cdx-message v-if="notice" type="success" class="ss-message">
      {{ notice }}
    </cdx-message>
    <cdx-message v-if="loading" type="notice" class="ss-message">
      Loading installed Saltlicks…
    </cdx-message>

    <div v-if="!loading && saltlicks.length" class="ss-layout">
      <!-- Each compiled child directory becomes one nested catalog entry. -->
      <aside class="ss-catalog" aria-label="Installed Saltlicks">
        <div class="ss-catalog-heading">
          <h2>Installed Saltlicks</h2>
          <span>{{ saltlicks.length }}</span>
        </div>
        <div class="ss-catalog-list">
          <button
            v-for="saltlick in saltlicks"
            :key="saltlick.id"
            type="button"
            class="cdx-card ss-saltlick-card"
            :aria-current="selectedId === saltlick.id ? 'page' : undefined"
            @click="selectSaltlick(saltlick.id)"
          >
            <span class="cdx-card__text">
              <span class="cdx-card__text__title">{{ saltlick.display_name }}</span>
              <span class="cdx-card__text__description">{{ saltlick.id }}</span>
              <span class="cdx-card__text__supporting-text">
                {{ saltlick.generated ? "Generated defaults" : "Typed contract" }}
              </span>
            </span>
          </button>
        </div>
      </aside>

      <article v-if="selectedContract" class="ss-selected">
        <header class="ss-selected-heading">
          <div>
            <h2>{{ selectedContract.display_name }}</h2>
            <p>{{ selectedContract.description }}</p>
          </div>
          <cdx-info-chip status="notice">
            {{ selectedContract.actions.allowed.length ? "Framework actions" : "Read only" }}
          </cdx-info-chip>
        </header>

        <cdx-tabs v-model:active="nestedTab" framed>
          <cdx-tab name="run" label="Run">
            <form class="ss-run-form" @submit.prevent="startRun('preview')">
              <div class="ss-field-grid">
                <template v-for="[name, spec] in inputEntries" :key="name">
                  <cdx-checkbox
                    v-if="spec.type === 'boolean'"
                    v-model="fields[name].value"
                    class="ss-checkbox-field"
                  >
                    {{ spec.label }}
                  </cdx-checkbox>

                  <cdx-field
                    v-else-if="spec.type === 'wiki'"
                    :optional="!spec.required"
                    is-fieldset
                    class="ss-field ss-field-wide"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <cdx-lookup
                      v-model:selected="fields[name].selected"
                      v-model:input-value="fields[name].text"
                      :menu-items="wikiLookupItems[name] ?? []"
                      placeholder="Search Wikimedia projects"
                      @input="onWikiLookupInput(name, $event)"
                      @update:selected="onWikiSelected(name, $event)"
                    />
                  </cdx-field>

                  <cdx-field
                    v-else-if="spec.type === 'choice'"
                    :optional="!spec.required"
                    class="ss-field"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <cdx-select
                      v-model:selected="fields[name].value"
                      :menu-items="choiceItems(spec)"
                    />
                  </cdx-field>

                  <cdx-field
                    v-else-if="spec.type === 'namespace'"
                    :optional="!spec.required"
                    class="ss-field"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <cdx-select
                      v-model:selected="fields[name].value"
                      :menu-items="namespaceItems(spec)"
                      default-label="Namespace"
                    />
                  </cdx-field>

                  <cdx-field
                    v-else-if="spec.type === 'page' || spec.type === 'pages'"
                    :optional="!spec.required"
                    class="ss-field ss-field-wide"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <div class="ss-page-field">
                      <cdx-select
                        v-if="spec.namespace?.selectable"
                        v-model:selected="fields[name].namespace"
                        :menu-items="namespaceItems(spec)"
                        default-label="Namespace"
                        @update:selected="onNamespaceSelected(name, $event)"
                      />
                      <div v-else class="ss-fixed-namespace">
                        {{ namespaceLabel(spec, fields[name].namespace) }}
                      </div>
                      <cdx-lookup
                        v-if="spec.type === 'page'"
                        v-model:selected="fields[name].selected"
                        v-model:input-value="fields[name].text"
                        :menu-items="pageLookupItems[name] ?? []"
                        placeholder="Search pages"
                        @input="onPageLookupInput(name, spec, $event)"
                      />
                      <cdx-multiselect-lookup
                        v-else
                        v-model:selected="fields[name].selected"
                        v-model:input-chips="fields[name].chips"
                        v-model:input-value="fields[name].text"
                        :menu-items="pageLookupItems[name] ?? []"
                        separate-input
                        placeholder="Search and add pages"
                        @input="onPageLookupInput(name, spec, $event)"
                      />
                    </div>
                    <p v-if="spec.type === 'pages'" class="ss-lookup-help">
                      Select up to {{ spec.max_items ?? 500 }} pages. Results follow the
                      selected wiki and namespace.
                    </p>
                  </cdx-field>

                  <cdx-field
                    v-else-if="spec.type === 'text'"
                    :optional="!spec.required"
                    class="ss-field ss-field-wide"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <cdx-text-area v-model="fields[name].value" :rows="5" />
                  </cdx-field>

                  <cdx-field
                    v-else
                    :optional="!spec.required"
                    class="ss-field"
                  >
                    <template #label>{{ spec.label }}</template>
                    <template v-if="spec.description" #description>
                      {{ spec.description }}
                    </template>
                    <cdx-text-input
                      v-model="fields[name].value"
                      :input-type="inputType(spec)"
                      :min="spec.minimum"
                      :max="spec.maximum"
                    />
                  </cdx-field>
                </template>
              </div>

              <cdx-accordion separation="outline" class="ss-arguments">
                <template #title>Advanced Pywikibot arguments</template>
                <template #description>
                  Optional compatibility escape hatch; enter one argument per line.
                </template>
                <cdx-text-area
                  v-model="argumentsText"
                  :rows="4"
                  placeholder="-simulate"
                />
              </cdx-accordion>

              <div class="ss-actions">
                <cdx-button
                  type="submit"
                  action="progressive"
                  weight="primary"
                  :disabled="busy || !auth.can_preview"
                >
                  {{ busy && runStatus ? `Run ${runStatus}…` : "Run dry preview" }}
                </cdx-button>
                <cdx-button
                  v-if="previewCanApply"
                  action="progressive"
                  :disabled="busy"
                  @click="startRun('apply')"
                >
                  Apply this exact plan
                </cdx-button>
              </div>
            </form>

            <section v-if="result" class="ss-results">
              <header>
                <div>
                  <h3>Run #{{ runId }}</h3>
                  <p>
                    {{ result.dry_run ? "Dry preview" : "Applied plan" }}
                  </p>
                </div>
                <cdx-info-chip :status="statusType(result.ok)">
                  {{ result.ok ? "Completed" : "Completed with errors" }}
                </cdx-info-chip>
              </header>

              <section v-for="[name, spec] in outputEntries" :key="name" class="ss-output">
                <h3>{{ spec.label }}</h3>
                <p v-if="spec.description">{{ spec.description }}</p>

                <div v-if="spec.type === 'table'" class="ss-table-wrap">
                  <table class="cdx-table__table">
                    <thead>
                      <tr>
                        <th v-for="(column, columnName) in spec.columns" :key="columnName">
                          {{ column.label }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, rowIndex) in (result.outputs[name] as any[])"
                        :key="rowIndex"
                      >
                        <td
                          v-for="(column, columnName) in spec.columns"
                          :key="columnName"
                        >
                          <a
                            v-if="column.type === 'page'"
                            :href="wikiUrl(row[columnName])"
                            target="_blank"
                            rel="noopener"
                          >
                            {{ pageLabel(row[columnName]) }}
                          </a>
                          <template v-else>
                            {{ displayValue(row[columnName], column.type) }}
                          </template>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <ul v-else-if="spec.type === 'pages'" class="ss-page-list">
                  <li v-for="page in (result.outputs[name] as any[])" :key="pageLabel(page)">
                    <a :href="wikiUrl(page)" target="_blank" rel="noopener">
                      {{ pageLabel(page) }}
                    </a>
                  </li>
                </ul>

                <pre v-else-if="spec.type === 'json'">{{ result.outputs[name] }}</pre>
                <p v-else class="ss-output-value">
                  {{ displayValue(result.outputs[name], spec.type) }}
                </p>
              </section>

              <section v-if="result.action_result.items.length" class="ss-output">
                <h3>Action plan</h3>
                <div class="ss-table-wrap">
                  <table class="cdx-table__table">
                    <thead>
                      <tr><th>Target</th><th>Action</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="item in result.action_result.items"
                        :key="`${item.index}-${pageLabel(item.target)}`"
                      >
                        <td>{{ pageLabel(item.target) }}</td>
                        <td><code>{{ item.type }}</code></td>
                        <td>{{ item.status }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p class="ss-plan-token">
                  Plan digest: <code>{{ result.plan_token.slice(0, 16) }}</code>
                </p>
              </section>
            </section>
          </cdx-tab>

          <cdx-tab name="history" label="History">
            <div class="ss-tab-panel">
              <p v-if="!history.length">No runs recorded for this Saltlick.</p>
              <div v-else class="ss-table-wrap">
                <table class="cdx-table__table">
                  <thead>
                    <tr><th>Run</th><th>Mode</th><th>Status</th><th>Created</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="run in history" :key="run.id">
                      <td>
                        <a :href="`/modules/runs/${run.id}/report`">#{{ run.id }}</a>
                      </td>
                      <td>{{ run.job_name }}</td>
                      <td>{{ run.status }}</td>
                      <td>{{ formatDate(run.created_at) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </cdx-tab>

          <cdx-tab name="contract" label="Contract">
            <div class="ss-tab-panel">
              <cdx-message type="notice">
                This contract and its script are immutable image contents. Duplicate or
                change the Saltlick directory, rebuild Salt Shack, and redeploy to update it.
              </cdx-message>
              <dl class="ss-contract-summary">
                <div><dt>Saltlick ID</dt><dd><code>{{ selectedContract.id }}</code></dd></div>
                <div>
                  <dt>Contract</dt>
                  <dd>Version {{ selectedContract.contract }}</dd>
                </div>
                <div>
                  <dt>Source digest</dt>
                  <dd><code>{{ selectedContract.source_digest.slice(0, 16) }}</code></dd>
                </div>
                <div>
                  <dt>Allowed actions</dt>
                  <dd>
                    {{ selectedContract.actions.allowed.join(", ") || "None (read only)" }}
                  </dd>
                </div>
              </dl>
              <pre>{{ JSON.stringify(selectedContract, null, 2) }}</pre>
            </div>
          </cdx-tab>
        </cdx-tabs>
      </article>
    </div>

    <cdx-message v-else-if="!loading && !error && !saltlicks.length" type="warning">
      This Salt Shack image contains no discovered Saltlick directories.
    </cdx-message>
  </main>
</template>
