<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import ChoiceTabs from "./components/ChoiceTabs.vue";
import InfoBar from "./components/InfoBar.vue";
import JobItem from "./components/JobItem.vue";
import PackageCard from "./components/PackageCard.vue";
import { useDownloader } from "./downloader";
import { formatUpdateTime } from "./format";
import { type MessageKey, pickLocale, translator } from "./i18n";
import { type Channel, filterPackages, isFinished, isQueued, type Source, sortPackages } from "./model";

const downloader = useDownloader();
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

const sources: { value: Source; label: string }[] = [
  { value: "modelscope", label: "ModelScope" },
  { value: "huggingface", label: "Hugging Face" },
];
const channels = computed(() =>
  (["nightly", "stable"] as Channel[]).map((value) => ({ value, label: t.value(value) })),
);

const catalog = computed(() => state.value?.catalog);
const visible = computed(() => sortPackages(filterPackages(packages.value, query.value), channel.value));
const hasFinished = computed(() => jobs.value.some(isFinished));

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

async function choose() {
  const picked = await downloader.pickDirectory(t.value("chooseTitle"));
  if (picked) {
    folder.value = picked;
    folderEdited = true;
  }
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
      <button
        type="button"
        class="btn"
        :disabled="catalog?.status === 'loading'"
        @click="downloader.refresh()"
      >
        {{ t("refresh") }}
      </button>
    </header>

    <InfoBar v-if="error" severity="error" :message="error" />

    <section class="surface-card options" :aria-label="t('folder')">
      <div class="folder">
        <label for="folder">{{ t("folder") }}</label>
        <div class="folder-row">
          <input
            id="folder"
            v-model="folder"
            class="text-input"
            type="text"
            spellcheck="false"
            autocomplete="off"
            aria-describedby="folder-help"
            @input="folderEdited = true"
          />
          <button type="button" class="btn" @click="choose">
            {{ t("choose") }}
          </button>
        </div>
        <p id="folder-help" class="field-help">{{ t("folderHelp") }}</p>
      </div>
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
          <input
            v-model="query"
            class="text-input search"
            type="search"
            :placeholder="t('search')"
            :aria-label="t('search')"
          />
          <ChoiceTabs v-model="source" :label="t('source')" :options="sources" />
          <ChoiceTabs v-model="channel" :label="t('channel')" :options="channels" />
        </div>
        <p class="caption text-secondary notes">
          <span>{{ gpuNote }}</span>
          <span v-if="catalogNote">{{ catalogNote }}</span>
        </p>

        <InfoBar
          v-if="catalog?.error && catalog.status !== 'loading'"
          severity="error"
          :message="t('loadFailed', { error: catalog.error })"
        />
        <div v-if="!packagesLoaded || (catalog?.status === 'loading' && packages.length === 0)" class="empty text-secondary" role="status">
          {{ t("loading") }}
        </div>
        <div v-else-if="packages.length === 0" class="empty text-secondary">
          <p>{{ t("noPackages", { platform: platformName }) }}</p>
          <button v-if="catalog?.status === 'failed'" type="button" class="btn" @click="downloader.refresh()">
            {{ t("retry") }}
          </button>
        </div>
        <p v-else-if="visible.length === 0" class="empty text-secondary">
          {{ t("noMatch", { query }) }}
        </p>
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
  display: flex;
  flex: 1 1 360px;
  flex-direction: column;
  gap: var(--space-1);
}

.folder-row {
  display: flex;
  gap: var(--space-2);
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
  flex: 1 1 200px;
  width: auto;
}

.notes {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2);
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-6) 0;
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
