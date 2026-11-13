<script setup lang="ts">
import {
  BaseInput,
  BaseTabs,
  EmptyState,
  FormField,
  InfoBar,
  PathInput,
  RefreshButton,
  useUiStrings,
} from "@hanafubuki/ui";
import { computed, onMounted, ref, watch } from "vue";
import JobItem from "./components/JobItem.vue";
import PackageCard from "./components/PackageCard.vue";
import { useDownloader } from "./downloader";
import { formatUpdateTime } from "./format";
import { useLastMessage } from "./held";
import { type MessageKey, pickLocale, translator } from "./i18n";
import { type Channel, filterPackages, isFinished, isQueued, type Source, sortPackages } from "./model";

const downloader = useDownloader();
const uiStrings = useUiStrings();
const { state, packages, packagesLoaded, source, channel, error, jobs } = downloader;

// The frame client sets the root's `lang` to the application's language.
const locale = computed(() =>
  pickLocale(downloader.locale.value ?? state.value?.locale, navigator.language),
);
const t = computed(() => translator(locale.value));
watch(t, (translate) => (document.title = translate("title")), { immediate: true });

const query = ref("");
const folder = ref("");
const autoExtract = ref(true);
const deleteArchive = ref(false);
let folderEdited = false;
let optionsSet = false;

// The page's own choices start from the settings and stay the user's once changed.
watch(
  () => state.value?.settings,
  (settings) => {
    if (!settings) return;
    if (!folderEdited) folder.value = settings.defaultFolder;
    if (!optionsSet) {
      autoExtract.value = settings.autoExtract;
      deleteArchive.value = settings.deleteArchive;
      optionsSet = true;
    }
  },
);

const sources = [
  { value: "modelscope", label: "ModelScope" },
  { value: "huggingface", label: "Hugging Face" },
];
const channels = computed(() =>
  (["nightly", "stable"] as const).map((value) => ({ value, label: t.value(value) })),
);

const catalog = computed(() => state.value?.catalog);
const visible = computed(() => sortPackages(filterPackages(packages.value, query.value), channel.value));
const hasFinished = computed(() => jobs.value.some(isFinished));
const catalogError = computed(() =>
  catalog.value?.error && catalog.value.status !== "loading"
    ? t.value("loadFailed", { error: catalog.value.error })
    : null,
);
const errorText = useLastMessage(() => error.value);
const catalogErrorText = useLastMessage(() => catalogError.value);

const catalogNote = computed(() => {
  const value = catalog.value;
  if (!value?.updateTime) return "";
  const time = formatUpdateTime(value.updateTime, locale.value);
  return value.fromCache ? t.value("cached", { time }) : t.value("updated", { time });
});

const gpuNote = computed(() => {
  const gpu = state.value?.gpu;
  if (!gpu?.detected) return t.value("gpuUnknown");
  if (gpu.vendors.length === 0) return t.value("gpuNone");
  const names = gpu.vendors.map((vendor) => t.value(`vendor_${vendor}` as MessageKey));
  return t.value("gpuDetected", { vendors: names.join(", ") });
});

const platformName = computed(() =>
  t.value(`platform_${state.value?.platform ?? "linux"}` as MessageKey),
);

function queued(filename: string): boolean {
  return isQueued(jobs.value, filename, folder.value.trim());
}

function editFolder(value: string | null) {
  folder.value = value ?? "";
  folderEdited = true;
}

function download(key: string, filename: string) {
  void downloader.enqueue({
    key,
    filename,
    folder: folder.value.trim(),
    autoExtract: autoExtract.value,
    deleteArchive: deleteArchive.value,
  });
}

onMounted(downloader.start);
</script>

<template>
  <main class="page">
    <header class="header">
      <div class="titles">
        <h1>{{ t("title") }}</h1>
        <p class="text-secondary">{{ t("subtitle") }}</p>
      </div>
      <RefreshButton
        :label="t('refresh')"
        :busy="catalog?.status === 'loading'"
        @click="downloader.refresh()"
      />
    </header>

    <InfoBar severity="error" :open="Boolean(error)" :message="errorText" />

    <section class="surface-card options" :aria-label="t('folder')">
      <FormField class="folder" :label="t('folder')" :hint="t('folderHelp')">
        <template #default="{ controlId }">
          <PathInput
            :id="controlId"
            :model-value="folder"
            :browse-label="uiStrings.t('common.actions.browseDirectory')"
            @update:model-value="editFolder"
          />
        </template>
      </FormField>
      <div class="checks">
        <span class="check-row">
          <input
            id="auto-extract"
            v-model="autoExtract"
            class="checkbox"
            type="checkbox"
            aria-labelledby="auto-extract-label"
          />
          <label id="auto-extract-label" for="auto-extract">{{ t("autoExtract") }}</label>
        </span>
        <span class="check-row">
          <input
            id="delete-archive"
            v-model="deleteArchive"
            class="checkbox"
            type="checkbox"
            :disabled="!autoExtract"
            aria-labelledby="delete-archive-label"
          />
          <label id="delete-archive-label" for="delete-archive">{{ t("deleteArchive") }}</label>
        </span>
      </div>
    </section>

    <div class="columns">
      <section class="catalog" aria-labelledby="packages-title">
        <div class="toolbar">
          <h2 id="packages-title" class="visually-hidden">{{ t("packages") }}</h2>
          <BaseInput
            class="search"
            type="search"
            :model-value="query"
            :placeholder="t('search')"
            :aria-label="t('search')"
            @update:model-value="query = String($event ?? '')"
          />
          <BaseTabs
            class="filter"
            selection-mode="radio"
            :label="t('source')"
            :items="sources"
            :model-value="source"
            @update:model-value="source = $event as Source"
          />
          <BaseTabs
            class="filter"
            selection-mode="radio"
            :label="t('channel')"
            :items="channels"
            :model-value="channel"
            @update:model-value="channel = $event as Channel"
          />
        </div>
        <p class="caption text-secondary notes">
          <span>{{ gpuNote }}</span>
          <span v-if="catalogNote">{{ catalogNote }}</span>
        </p>

        <InfoBar severity="error" :open="Boolean(catalogError)" :message="catalogErrorText" />
        <EmptyState
          v-if="!packagesLoaded || (catalog?.status === 'loading' && packages.length === 0)"
          :text="t('loading')"
        />
        <EmptyState v-else-if="packages.length === 0" :text="t('noPackages', { platform: platformName })">
          <template v-if="catalog?.status === 'failed'" #action>
            <button type="button" class="btn" @click="downloader.refresh()">
              {{ t("retry") }}
            </button>
          </template>
        </EmptyState>
        <EmptyState v-else-if="visible.length === 0" :text="t('noMatch', { query })" />
        <div v-else class="grid">
          <PackageCard
            v-for="pkg in visible"
            :key="pkg.key"
            :pkg="pkg"
            :channel="channel"
            :t="t"
            :is-queued="queued"
            @download="(filename) => download(pkg.key, filename)"
          />
        </div>
      </section>

      <section class="surface-card queue" aria-labelledby="queue-title">
        <div class="queue-header">
          <h2 id="queue-title">{{ t("downloads") }}</h2>
          <button
            v-if="hasFinished"
            type="button"
            class="btn btn-subtle btn-sm"
            @click="downloader.clearFinished()"
          >
            {{ t("clearFinished") }}
          </button>
        </div>
        <p v-if="jobs.length === 0" class="caption text-secondary">{{ t("noJobs") }}</p>
        <ul v-else class="jobs">
          <JobItem
            v-for="job in jobs"
            :key="job.id"
            :job="job"
            :t="t"
            @cancel="downloader.cancel"
            @remove="downloader.remove"
            @open="downloader.openInstance"
          />
        </ul>
      </section>
    </div>
  </main>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.titles {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

h1 {
  font: var(--type-title);
}

h2 {
  font: var(--type-subtitle);
}

.options {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-4);
  padding: var(--space-4);
}

.folder {
  flex: 1 1 360px;
}

.checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

@media (min-width: 960px) {
  .columns {
    grid-template-columns: minmax(0, 1fr) 340px;
  }

  .queue {
    position: sticky;
    top: var(--space-4);
  }
}

.catalog {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
}

.search {
  flex: 1 1 100%;
}

/* The tabs take the width they are given (they fold what does not fit), so each gets a share. */
.filter {
  flex: 1 1 240px;
}

.notes {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-3);
}

.queue {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  /* Above the long package list in one column, beside it in two. */
  order: -1;
}

@media (min-width: 960px) {
  .queue {
    order: 0;
  }
}

.queue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.jobs {
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
