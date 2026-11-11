/**
 * The Hanafubuki frame client (`__hanafubuki/frame.js`, served by the host at the
 * package root), as `sdk/frame/frame.d.ts` types it, with the messages the
 * extension-validation plan (§3.6) adds. The page imports it as a namespace, so a
 * method an older host's client lacks is `undefined` rather than a link error.
 */
declare module "@hanafubuki/frame" {
  export type FrameErrorKind = "unavailable" | "timeout" | "invalid" | "forbidden" | "failed";

  export interface FrameError extends Error {
    name: "FrameError";
    kind: FrameErrorKind;
  }

  export function ready(): void;
  export function call<T = unknown>(method: string, params?: unknown): Promise<T>;
  export function on<T = unknown>(event: string, listener: (payload: T) => void): () => void;
  export function state<T = unknown>(): Promise<T>;
  export function onState<T = unknown>(listener: (state: T) => void): () => void;

  /** Opens the host's folder dialog: the chosen native path, or null when cancelled. */
  export const pickDirectory: ((options?: { title?: string }) => Promise<string | null>) | undefined;
  /** Opens an instance's page in the application. */
  export const navigateInstance: ((instanceId: string) => Promise<void>) | undefined;
}
