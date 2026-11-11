<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import JobItem from "./components/JobItem.vue";
import PackageCard from "./components/PackageCard.vue";
import { useDownloader } from "./downloader";
import { formatUpdateTime } from "./format";
import { type MessageKey, pickLocale, translator } from "./i18n";
import { type Channel, filterPackages, isFinished, isQueued, type Source, sortPackages } from "./model";

const downloader = useDownloader();
const { state, packages, packagesLoaded, source, channel, error, jobs } = downloader;

const locale = computed(() => pickLocale(state.value?.locale, navigator.language));
const t = computed(() => translator(locale.value));
watch(locale, (value) => (document.documentElement.lang = value), { immediate: true });
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
const channels: Channel[] = ["nightly", "stable"];

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
        <p class="secondary">{{ t("subtitle") }}</p>
      </div>
      <button
        type="button"
        class="button"
        :disabled="catalog?.status === 'loading'"
        @click="downloader.refresh()"
      >
        {{ t("refresh") }}
      </button>
    </header>

    <p v-if="error" class="banner danger" role="alert">{{ error }}</p>

    <section class="card options" :aria-label="t('folder')">
      <div class="folder">
        <label for="folder">{{ t("folder") }}</label>
        <div class="folder-row">
          <input
            id="folder"
            v-model="folder"
            class="field"
            type="text"
            spellcheck="false"
            autocomplete="off"
            aria-describedby="folder-help"
            @input="folderEdited = true"
          />
          <button v-if="downloader.canPickDirectory" type="button" class="button" @click="choose">
            {{ t("choose") }}
          </button>
        </div>
        <p id="folder-help" class="caption secondary">{{ t("folderHelp") }}</p>
      </div>
      <div class="checks">
        <label class="check">
          <input v-model="autoExtract" type="checkbox" />
          {{ t("autoExtract") }}
        </label>
        <label class="check">
          <input v-model="deleteArchive" type="checkbox" :disabled="!autoExtract" />
          {{ t("deleteArchive") }}
        </label>
      </div>
    </section>

    <div class="columns">
      <section class="catalog" aria-labelledby="packages-title">
        <div class="toolbar">
          <h2 id="packages-title" class="visually-hidden">{{ t("packages") }}</h2>
          <input
            v-model="query"
            class="field search"
            type="search"
            :placeholder="t('search')"
            :aria-label="t('search')"
          />
          <fieldset class="segmented">
            <legend class="visually-hidden">{{ t("source") }}</legend>
            <label v-for="option in sources" :key="option.value">
              <input v-model="source" type="radio" name="source" :value="option.value" />
              <span>{{ option.label }}</span>
            </label>
          </fieldset>
          <fieldset class="segmented">
            <legend class="visually-hidden">{{ t("channel") }}</legend>
            <label v-for="option in channels" :key="option">
              <input v-model="channel" type="radio" name="channel" :value="option" />
              <span>{{ t(option) }}</span>
            </label>
          </fieldset>
        </div>
        <p class="caption secondary notes">
          <span>{{ gpuNote }}</span>
          <span v-if="catalogNote">{{ catalogNote }}</span>
        </p>

        <p v-if="catalog?.error && catalog.status !== 'loading'" class="caption danger" role="status">
          {{ t("loadFailed", { error: catalog.error }) }}
        </p>
        <div v-if="!packagesLoaded || (catalog?.status === 'loading' && packages.length === 0)" class="empty secondary" role="status">
          {{ t("loading") }}
        </div>
        <div v-else-if="packages.length === 0" class="empty secondary">
          <p>{{ t("noPackages", { platform: platformName }) }}</p>
          <button v-if="catalog?.status === 'failed'" type="button" class="button" @click="downloader.refresh()">
            {{ t("retry") }}
          </button>
        </div>
        <p v-else-if="visible.length === 0" class="empty secondary">
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

      <section class="card queue" aria-labelledby="queue-title">
        <div class="queue-header">
          <h2 id="queue-title">{{ t("downloads") }}</h2>
          <button
            v-if="hasFinished"
            type="button"
            class="button small subtle"
            @click="downloader.clearFinished()"
          >
            {{ t("clearFinished") }}
          </button>
        </div>
        <p v-if="jobs.length === 0" class="caption secondary">{{ t("noJobs") }}</p>
        <ul v-else class="jobs">
          <JobItem
            v-for="job in jobs"
            :key="job.id"
            :job="job"
            :t="t"
            :can-navigate="downloader.canNavigate"
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
  gap: var(--space-4, 16px);
  padding: var(--space-6, 24px);
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4, 16px);
}

.titles {
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 4px);
}

h1 {
  font-size: var(--font-size-title, 28px);
  line-height: var(--line-height-title, 36px);
  font-weight: var(--weight-semibold, 600);
}

h2 {
  font-size: var(--font-size-subtitle, 20px);
  line-height: var(--line-height-subtitle, 28px);
  font-weight: var(--weight-semibold, 600);
}

.banner {
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border: 1px solid currentColor;
  border-radius: var(--radius-control, 4px);
}

.options {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-4, 16px);
  padding: var(--space-4, 16px);
}

.folder {
  display: flex;
  flex: 1 1 360px;
  flex-direction: column;
  gap: var(--space-1, 4px);
}

.folder-row {
  display: flex;
  gap: var(--space-2, 8px);
}

.folder-row input {
  flex: 1;
}

.checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}

.check {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2, 8px);
}

.check input {
  margin: 0;
  accent-color: var(--accent-fill, AccentColor);
}

.columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-4, 16px);
  align-items: start;
}

@media (min-width: 960px) {
  .columns {
    grid-template-columns: minmax(0, 1fr) 340px;
  }

  .queue {
    position: sticky;
    top: var(--space-4, 16px);
  }
}

.catalog {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2, 8px);
}

.search {
  flex: 1 1 200px;
}

.segmented {
  display: inline-flex;
  margin: 0;
  padding: 2px;
  border: 1px solid var(--stroke-control, ButtonBorder);
  border-radius: var(--radius-control, 4px);
  background: var(--fill-control, ButtonFace);
}

.segmented label {
  position: relative;
  display: inline-flex;
}

.segmented input {
  position: absolute;
  opacity: 0;
  inset: 0;
  margin: 0;
}

.segmented span {
  display: inline-flex;
  align-items: center;
  min-height: calc(var(--control-height-md, 32px) - 6px);
  padding: 0 var(--space-3, 12px);
  border-radius: var(--radius-small, 2px);
  cursor: pointer;
  white-space: nowrap;
}

.segmented label:hover span {
  background: var(--fill-subtle-hover, ButtonFace);
}

.segmented input:checked + span {
  background: var(--accent-fill, AccentColor);
  color: var(--text-on-accent, AccentColorText);
}

.segmented input:focus-visible + span {
  outline: 2px solid var(--focus-stroke-outer, Highlight);
  outline-offset: 1px;
}

.notes {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2, 8px);
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3, 12px);
  padding: var(--space-6, 24px) 0;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-3, 12px);
}

.queue {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-4, 16px);
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
  gap: var(--space-2, 8px);
}

.jobs {
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
