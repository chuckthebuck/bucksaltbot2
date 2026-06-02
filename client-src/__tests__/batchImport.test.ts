import { describe, expect, it } from "vitest";

import {
  parseDelimitedRows,
  parseQuarryJson,
  parseQuarryText,
  quarryResultUrl,
} from "../batchImport";

describe("batch Quarry import helpers", () => {
  it("builds a latest result URL from a Quarry query URL", () => {
    expect(quarryResultUrl("https://quarry.wmcloud.org/query/12345")).toBe(
      "https://quarry.wmcloud.org/query/12345/result/latest/0/json"
    );
  });

  it("builds a run output URL from a Quarry run URL", () => {
    expect(quarryResultUrl("https://quarry.wmcloud.org/run/67890/output/0/csv")).toBe(
      "https://quarry.wmcloud.org/run/67890/output/0/json"
    );
  });

  it("supports bare query IDs and run-prefixed IDs", () => {
    expect(quarryResultUrl("42")).toBe(
      "https://quarry.wmcloud.org/query/42/result/latest/0/json"
    );
    expect(quarryResultUrl("run:42")).toBe(
      "https://quarry.wmcloud.org/run/42/output/0/json"
    );
  });

  it("rejects non-Quarry URLs", () => {
    expect(quarryResultUrl("https://example.org/query/1")).toBeNull();
  });

  it("parses Quarry JSON headers and rows into rollback items", () => {
    expect(
      parseQuarryJson({
        headers: ["img_name", "actor_name", "comment_text"],
        rows: [["Example.jpg", "BadUser", "test upload"]],
      })
    ).toEqual([
      {
        title: "File:Example.jpg",
        user: "BadUser",
        summary: "test upload",
        selected: true,
      },
    ]);
  });

  it("parses CSV exports with quoted fields", () => {
    expect(
      parseDelimitedRows(
        'file_title,target_user,summary\n"File:One.jpg",Example,"contains, comma"'
      )
    ).toEqual([
      {
        title: "File:One.jpg",
        user: "Example",
        summary: "contains, comma",
        selected: true,
      },
    ]);
  });

  it("parses legacy uploaded JSON item lists", () => {
    expect(
      parseQuarryText(
        JSON.stringify({
          items: [{ title: "File:Two.jpg", user: "Uploader", summary: null }],
        })
      )
    ).toEqual([
      {
        title: "File:Two.jpg",
        user: "Uploader",
        summary: null,
        selected: true,
      },
    ]);
  });
});
