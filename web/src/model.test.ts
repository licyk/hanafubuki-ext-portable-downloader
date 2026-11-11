import { describe, expect, it } from "vitest";
import { formatBuildDate, formatBytes, formatPercent, formatSpeed } from "./format";
import { pickLocale, translator } from "./i18n";
import { filterPackages, isQueued, jobFraction, type Job, type Package, sortPackages } from "./model";

function pkg(key: string, displayName: string, compatibility: Package["compatibility"]): Package {
  return { key, displayName, description: "整合包", gpu: null, compatibility, stable: [], nightly: [] };
}

function job(overrides: Partial<Job>): Job {
  return {
    id: "1",
    key: "comfyui_cuda",
    displayName: "ComfyUI (NVIDIA)",
    source: "modelscope",
    channel: "nightly",
    filename: "a.7z",
    version: null,
    buildDate: "20261109",
    folder: "/srv",
    state: "queued",
    cancelling: false,
    downloaded: 0,
    total: null,
    speed: 0,
    extracted: 0,
    extractTotal: null,
    archivePath: null,
    packagePath: null,
    instances: [],
    warnings: [],
    error: null,
    ...overrides,
  };
}

describe("packages", () => {
  const list = [
    pkg("sd_webui_cuda", "Stable Diffusion WebUI (NVIDIA)", "supported"),
    pkg("comfyui_rocm", "ComfyUI (AMD)", "unsupported"),
    pkg("comfyui_cuda", "ComfyUI (NVIDIA)", "supported"),
    pkg("fooocus_xpu", "Fooocus (Intel)", "unknown"),
  ];

  it("filters by every word of the query, in any field", () => {
    expect(filterPackages(list, "comfy nvidia").map((p) => p.key)).toEqual(["comfyui_cuda"]);
    expect(filterPackages(list, "  ROCM ").map((p) => p.key)).toEqual(["comfyui_rocm"]);
    expect(filterPackages(list, "整合包")).toHaveLength(4);
    expect(filterPackages(list, "")).toBe(list);
  });

  it("puts what suits this machine first", () => {
    expect(sortPackages(list, "nightly").map((p) => p.key)).toEqual([
      "comfyui_cuda",
      "sd_webui_cuda",
      "fooocus_xpu",
      "comfyui_rocm",
    ]);
  });

  it("puts packages with builds in the channel before those without", () => {
    const build = { filename: "a.7z", version: "3.8", buildDate: null, size: null };
    const withStable = { ...pkg("fooocus_rocm", "Fooocus (AMD)", "unsupported"), stable: [build] };
    expect(sortPackages([...list, withStable], "stable")[0].key).toBe("fooocus_rocm");
  });
});

describe("jobs", () => {
  it("knows the fraction of the current step only when it has a total", () => {
    expect(jobFraction(job({ state: "downloading", downloaded: 25, total: 100 }))).toBe(0.25);
    expect(jobFraction(job({ state: "downloading", downloaded: 25 }))).toBeNull();
    expect(jobFraction(job({ state: "extracting", extracted: 3, extractTotal: 4 }))).toBe(0.75);
    expect(jobFraction(job({ state: "registering" }))).toBeNull();
    expect(jobFraction(job({ state: "done" }))).toBe(1);
  });

  it("finds a file already queued for the same folder", () => {
    const jobs = [job({ state: "downloading" }), job({ filename: "b.7z", state: "done" })];
    expect(isQueued(jobs, "a.7z", "/srv")).toBe(true);
    expect(isQueued(jobs, "a.7z", "/elsewhere")).toBe(false);
    expect(isQueued(jobs, "b.7z", "/srv")).toBe(false);
  });
});

describe("format", () => {
  it("writes sizes, speeds and percentages", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(formatBytes(150 * 1024 ** 2)).toBe("150 MB");
    expect(formatSpeed(2 * 1024 ** 2)).toBe("2.0 MB/s");
    expect(formatPercent(0.999)).toBe("99%");
  });

  it("writes build dates as ISO dates", () => {
    expect(formatBuildDate("20261109")).toBe("2026-11-09");
    expect(formatBuildDate("v3.8")).toBe("v3.8");
  });
});

describe("i18n", () => {
  it("follows the application's language, else the browser's", () => {
    expect(pickLocale("zh", "en-US")).toBe("zh");
    expect(pickLocale("auto", "zh-CN")).toBe("zh");
    expect(pickLocale(undefined, "fr")).toBe("en");
  });

  it("fills placeholders and leaves unknown ones", () => {
    const t = translator("en");
    expect(t("open", { name: "ComfyUI" })).toBe("Open ComfyUI");
    expect(t("ofTotal", { done: "1 MB" })).toBe("1 MB of {total}");
    expect(translator("zh")("download")).toBe("下载");
  });
});
