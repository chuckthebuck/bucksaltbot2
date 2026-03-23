import { describe, expect, it, vi } from "vitest";

import { loadDraft, saveDraft } from "../draft";

function mockLocalStorage() {
  const store = new Map<string, string>();

  const api = {
    getItem: vi.fn((key: string) => (store.has(key) ? store.get(key)! : null)),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key);
    }),
    clear: vi.fn(() => {
      store.clear();
    }),
  };

  Object.defineProperty(globalThis, "localStorage", {
    value: api,
    configurable: true,
    writable: true,
  });

  return api;
}

describe("draft storage helpers", () => {
  it("loads a stored draft value", () => {
    mockLocalStorage();
    localStorage.setItem("buckbot:batchDraft:test", "File:A.jpg|User");
    expect(loadDraft("buckbot:batchDraft:test")).toBe("File:A.jpg|User");
  });

  it("returns empty string when key is missing", () => {
    mockLocalStorage();
    expect(loadDraft("buckbot:batchDraft:missing")).toBe("");
  });

  it("does not throw when localStorage write fails", () => {
    const api = mockLocalStorage();
    const setItemSpy = vi.spyOn(api, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    expect(() => saveDraft("buckbot:batchDraft:test", "x")).not.toThrow();

    setItemSpy.mockRestore();
  });

  it("does not throw when localStorage read fails", () => {
    const api = mockLocalStorage();
    const getItemSpy = vi.spyOn(api, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(loadDraft("buckbot:batchDraft:test")).toBe("");

    getItemSpy.mockRestore();
  });
});
