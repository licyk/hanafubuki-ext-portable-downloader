<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { formatBuildDate, formatBytes } from "../format";
import type { MessageKey, Translate } from "../i18n";
import type { Channel, Entry, Package } from "../model";

const props = defineProps<{
  pkg: Package;
  channel: Channel;
  t: Translate;
  isQueued: (filename: string) => boolean;
}>();

const emit = defineEmits<{ download: [filename: string] }>();

const entries = computed<Entry[]>(() => props.pkg[props.channel]);
const selected = ref("");

watch(
  entries,
  (list) => {
    if (!list.some((entry) => entry.filename === selected.value)) {
      selected.value = list[0]?.filename ?? "";
    }
  },
  { immediate: true },
);

const queued = computed(() => selected.value !== "" && props.isQueued(selected.value));
const selectId = computed(() => `version-${props.pkg.key}`);

function entryLabel(entry: Entry): string {
  const name = entry.version
    ? `v${entry.version}`
    : entry.buildDate
      ? formatBuildDate(entry.buildDate)
      : entry.filename;
  return entry.size ? `${name} (${formatBytes(entry.size)})` : name;
}

const badge = computed(() => {
  const vendor = props.pkg.gpu ? props.t(`vendor_${props.pkg.gpu}` as MessageKey) : null;
  return { vendor, status: props.pkg.compatibility, hint: props.t(props.pkg.compatibility) };
});
</script>

<template>
  <article class="package card" :aria-labelledby="`name-${pkg.key}`">
    <div class="heading">
      <h3 :id="`name-${pkg.key}`">{{ pkg.displayName }}</h3>
      <span v-if="badge.vendor" class="badge caption" :class="badge.status" :title="badge.hint">
        <span class="dot" aria-hidden="true"></span>
        {{ badge.vendor }}
        <span class="visually-hidden">: {{ badge.hint }}</span>
      </span>
    </div>
    <p v-if="pkg.description" class="description secondary">{{ pkg.description }}</p>
    <div class="actions">
      <template v-if="entries.length > 0">
        <label class="caption secondary" :for="selectId">{{ t("version") }}</label>
        <select :id="selectId" v-model="selected" class="field">
          <option v-for="entry in entries" :key="entry.filename" :value="entry.filename">
            {{ entryLabel(entry) }}
          </option>
        </select>
        <button
          type="button"
          class="button accent"
          :disabled="queued"
          :title="queued ? t('queued') : undefined"
          @click="emit('download', selected)"
        >
          {{ t("download") }}
        </button>
      </template>
      <p v-else class="caption secondary">
        {{ t(`noBuilds_${channel}`) }}
      </p>
    </div>
  </article>
</template>

<style scoped>
.package {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-4, 16px);
}

.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2, 8px);
}

h3 {
  font-size: var(--font-size-body, 14px);
  line-height: var(--line-height-body, 20px);
  font-weight: var(--weight-semibold, 600);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1, 4px);
  padding: 0 var(--space-2, 8px);
  border: 1px solid var(--stroke-control, ButtonBorder);
  border-radius: 999px;
  color: var(--text-secondary, GrayText);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary, GrayText);
}

.badge.supported .dot {
  background: var(--success, #0f7b0f);
}

.badge.unsupported .dot {
  background: var(--warning, #9d5d00);
}

.description {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2, 8px);
  margin-top: auto;
  padding-top: var(--space-2, 8px);
}

.actions select {
  flex: 1 1 140px;
}
</style>
