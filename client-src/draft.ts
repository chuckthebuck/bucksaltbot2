/** Load a best-effort form draft without failing in privacy-restricted browsers. */
export function loadDraft(key: string): string {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

/** Persist a best-effort form draft while keeping storage failures non-fatal. */
export function saveDraft(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Ignore storage errors (quota/private mode) to avoid breaking the UI.
  }
}
