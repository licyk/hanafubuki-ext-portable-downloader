// What the backend's state and actions answer (backend/portable_downloader/app.py),
// and the page's pure logic over it.

export type Source = "modelscope" | "huggingface";
export type Channel = "nightly" | "stable";
export type Compatibility = "supported" | "unsupported" | "unknown";
export type JobState =
  | "queued"
  | "downloading"
  | "extracting"
  | "registering"
  | "done"
  | "failed"
  | "cancelled";

export interface Settings {
  source: Source;
  channel: Channel;
  downloadTool: string;
  autoExtract: boolean;
  deleteArchive: boolean;
  defaultFolder: string;
}

export interface Catalog {
  status: "loading" | "ready" | "failed";
  updateTime: string | null;
  fromCache: boolean;
  error: string | null;
  revision: number;
}

export interface Job {
  id: string;
  key: string;
  displayName: string;
  source: Source;
  channel: Channel;
  filename: string;
  version: string | null;
  buildDate: string | null;
  folder: string;
  state: JobState;
  cancelling: boolean;
  downloaded: number;
  total: number | null;
  speed: number;
  extracted: number;
  extractTotal: number | null;
  archivePath: string | null;
  packagePath: string | null;
  instances: { id: string; name: string }[];
  warnings: string[];
  error: string | null;
}

export interface DownloaderState {
  platform: string;
  locale: string;
  instancesDir: string | null;
  settings: Settings;
  gpu: { detected: boolean; vendors: string[] };
  catalog: Catalog;
  jobs: Job[];
}

export interface Entry {
  filename: string;
  version: string | null;
  buildDate: string | null;
  size: number | null;
}

export interface Package {
  key: string;
  displayName: string;
  description: string;
  gpu: string | null;
  compatibility: Compatibility;
  stable: Entry[];
  nightly: Entry[];
}

export interface PackagesAnswer {
  source: Source;
  platform: string;
  revision: number;
  packages: Package[];
}

const FINISHED: readonly JobState[] = ["done", "failed", "cancelled"];

export function isFinished(job: Job): boolean {
  return FINISHED.includes(job.state);
}

/** The packages whose name, key or description holds every word of `query`. */
export function filterPackages(packages: Package[], query: string): Package[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return packages;
  return packages.filter((pkg) => {
    const text = `${pkg.displayName} ${pkg.key} ${pkg.description}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

/**
 * Packages with builds in `channel` first; among them what suits this machine, then
 * unknown, then the rest; by name within each.
 */
export function sortPackages(packages: Package[], channel: Channel): Package[] {
  const rank: Record<Compatibility, number> = { supported: 0, unknown: 1, unsupported: 2 };
  const empty = (pkg: Package) => (pkg[channel].length === 0 ? 1 : 0);
  return [...packages].sort(
    (a, b) =>
      empty(a) - empty(b) ||
      rank[a.compatibility] - rank[b.compatibility] ||
      a.displayName.localeCompare(b.displayName),
  );
}

/** The fraction done of the job's current step, or null when it is not known. */
export function jobFraction(job: Job): number | null {
  if (job.state === "downloading" && job.total) return Math.min(1, job.downloaded / job.total);
  if (job.state === "extracting" && job.extractTotal) {
    return Math.min(1, job.extracted / job.extractTotal);
  }
  if (job.state === "done") return 1;
  return null;
}

/** Whether a job for this file into this folder is already waiting or running. */
export function isQueued(jobs: Job[], filename: string, folder: string): boolean {
  return jobs.some(
    (job) => job.filename === filename && job.folder === folder && !isFinished(job),
  );
}
