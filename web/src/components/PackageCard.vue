<script setup lang="ts">
import { BaseDropdown, FormField, type StatusTone, StatusBadge, Tooltip } from "@hanafubuki/ui";
import { computed, ref, watch } from "vue";
import { formatBuildDate, formatBytes } from "../format";
import type { MessageKey, Translate } from "../i18n";
import type { Channel, Compatibility, Entry, Package } from "../model";

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

// The build's size is the option's alias, its own muted column in the menu.
const options = computed(() =>
  entries.value.map((entry) => ({
    value: entry.filename,
    label: entry.version
      ? `v${entry.version}`
      : entry.buildDate
        ? formatBuildDate(entry.buildDate)
        : entry.filename,
    alias: entry.size ? formatBytes(entry.size) : undefined,
  })),
);

const TONES: Record<Compatibility, StatusTone> = {
  supported: "success",
  unsupported: "warning",
  unknown: "neutral",
};

const badge = computed(() => {
  const vendor = props.pkg.gpu ? props.t(`vendor_${props.pkg.gpu}` as MessageKey) : null;
  return { vendor, tone: TONES[props.pkg.compatibility], hint: props.t(props.pkg.compatibility) };
});
</script>

<template>
  <article class="package surface-card" :aria-labelledby="`name-${pkg.key}`">
    <div class="heading">
      <h3 :id="`name-${pkg.key}`">{{ pkg.displayName }}</h3>
      <Tooltip v-if="badge.vendor" :text="badge.hint">
        <StatusBadge :tone="badge.tone" dot>
          {{ badge.vendor }}
          <span class="visually-hidden">: {{ badge.hint }}</span>
        </StatusBadge>
      </Tooltip>
    </div>
    <p v-if="pkg.description" class="description text-secondary">{{ pkg.description }}</p>
    <FormField v-if="entries.length > 0" class="actions" :label="t('version')">
      <template #default="{ controlId }">
        <div class="version-row">
          <BaseDropdown
            :id="controlId"
            class="version"
            :label="t('version')"
            :options="options"
            :model-value="selected"
            @update:model-value="selected = $event"
          />
          <!-- A queued build says why its Download is off. -->
          <Tooltip v-if="queued" :text="t('queued')">
            <button type="button" class="btn" disabled>{{ t("download") }}</button>
          </Tooltip>
          <button v-else type="button" class="btn" @click="emit('download', selected)">
            {{ t("download") }}
          </button>
        </div>
      </template>
    </FormField>
    <p v-else class="actions caption text-secondary">
      {{ t(`noBuilds_${channel}`) }}
    </p>
  </article>
</template>

<style scoped>
.package {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
}

.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

h3 {
  font: var(--type-body-strong);
}

.description {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.actions {
  margin-top: auto;
  padding-top: var(--space-2);
}

.version-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.version {
  flex: 1 1 0;
  min-width: 0;
}
</style>
