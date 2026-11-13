// The page's connection to its backend, through the host's frame client only:
// a frame has no network of its own (connect-src 'none').
import * as frame from "@hanafubuki/frame";
import { computed, ref, shallowRef, watch } from "vue";
import type { Channel, DownloaderState, Package, PackagesAnswer, Source } from "./model";

export interface EnqueueOptions {
  key: string;
  filename: string;
  folder: string;
  autoExtract: boolean;
  deleteArchive: boolean;
}

export function useDownloader() {
  const state = shallowRef<DownloaderState | null>(null);
  const packages = shallowRef<Package[]>([]);
  const packagesLoaded = ref(false);
  const source = ref<Source>("modelscope");
  const channel = ref<Channel>("nightly");
  const error = ref<string | null>(null);
  // The application's language, which the host sends with the theme.
  const locale = ref(frame.locale());
  let pushed = false;
  let loaded = { source: "", revision: -1 };

  function receive(next: DownloaderState) {
    if (!state.value) {
      source.value = next.settings.source;
      channel.value = next.settings.channel;
    }
    state.value = next;
  }

  async function loadPackages() {
    const wanted = { source: source.value, revision: state.value?.catalog.revision ?? -1 };
    if (wanted.source === loaded.source && wanted.revision === loaded.revision) return;
    loaded = wanted;
    try {
      const answer = await frame.call<PackagesAnswer>("packages", { source: wanted.source });
      if (answer.source !== source.value) return;
      packages.value = answer.packages;
      packagesLoaded.value = true;
      loaded.revision = answer.revision;
    } catch (failure) {
      loaded = { source: "", revision: -1 };
      error.value = message(failure);
    }
  }

  async function act<T>(method: string, params: unknown): Promise<T | undefined> {
    error.value = null;
    try {
      return await frame.call<T>(method, params);
    } catch (failure) {
      error.value = message(failure);
      return undefined;
    }
  }

  function start() {
    frame.onLocale((next) => (locale.value = next));
    // Listen first: a state pushed before the page listened is not sent again.
    frame.onState<DownloaderState>((next) => {
      pushed = true;
      receive(next);
    });
    frame.ready();
    frame
      .state<DownloaderState>()
      .then((first) => {
        if (!pushed) receive(first);
      })
      .catch((failure) => {
        error.value = message(failure);
      });
  }

  watch(
    () => [state.value?.catalog.revision, source.value] as const,
    ([revision]) => {
      if (revision !== undefined) void loadPackages();
    },
  );

  return {
    state,
    packages,
    packagesLoaded,
    source,
    channel,
    error,
    locale,
    jobs: computed(() => state.value?.jobs ?? []),
    start,
    refresh: () => act("refresh", {}),
    enqueue: (options: EnqueueOptions) =>
      act("enqueue", { ...options, source: source.value, channel: channel.value }),
    cancel: (jobId: string) => act("cancel", { jobId }),
    remove: (jobId: string) => act("remove", { jobId }),
    clearFinished: () => act("clearFinished", {}),
    openInstance: (instanceId: string) =>
      frame.navigateInstance(instanceId).catch((failure: unknown) => {
        error.value = message(failure);
      }),
  };
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
