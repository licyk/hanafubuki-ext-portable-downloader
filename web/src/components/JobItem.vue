<script setup lang="ts">
import { computed } from "vue";
import { formatBuildDate, formatBytes, formatPercent, formatSpeed } from "../format";
import type { MessageKey, Translate } from "../i18n";
import { isFinished, jobFraction, type Job } from "../model";

const props = defineProps<{ job: Job; t: Translate; canNavigate: boolean }>();

const emit = defineEmits<{
  cancel: [jobId: string];
  remove: [jobId: string];
  open: [instanceId: string];
}>();

const finished = computed(() => isFinished(props.job));
const fraction = computed(() => jobFraction(props.job));
const stateKey = computed(
  () =>
    `state${props.job.state[0].toUpperCase()}${props.job.state.slice(1)}` as MessageKey,
);

const label = computed(() => {
  const job = props.job;
  const when = job.version ? `v${job.version}` : job.buildDate ? formatBuildDate(job.buildDate) : "";
  return when ? `${job.displayName} · ${when}` : job.displayName;
});

const detail = computed(() => {
  const job = props.job;
  if (job.cancelling) return props.t("cancelling");
  if (job.state === "downloading" && job.downloaded > 0) {
    const done = formatBytes(job.downloaded);
    const amount = job.total ? props.t("ofTotal", { done, total: formatBytes(job.total) }) : done;
    return job.speed > 0 ? `${amount} · ${formatSpeed(job.speed)}` : amount;
  }
  if (job.state === "extracting" && fraction.value !== null) return formatPercent(fraction.value);
  if (job.state === "done" && job.instances.length === 0) {
    const path = job.packagePath ?? job.archivePath;
    return path ? props.t("savedTo", { path }) : "";
  }
  return "";
});
</script>

<template>
  <li class="job" :aria-label="label">
    <div class="row">
      <div class="text">
        <p class="name">{{ label }}</p>
        <p class="caption secondary">
          <span :class="{ danger: job.state === 'failed' }" aria-live="polite">{{ t(stateKey) }}</span>
          <template v-if="detail"> · {{ detail }}</template>
        </p>
      </div>
      <button
        v-if="!finished"
        type="button"
        class="button small"
        :disabled="job.cancelling"
        @click="emit('cancel', job.id)"
      >
        {{ t("cancel") }}
      </button>
      <button v-else type="button" class="button small subtle" @click="emit('remove', job.id)">
        {{ t("remove") }}
      </button>
    </div>
    <div
      v-if="!finished && job.state !== 'queued'"
      class="bar"
      role="progressbar"
      :aria-label="t(stateKey)"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="fraction === null ? undefined : Math.floor(fraction * 100)"
      :class="{ indeterminate: fraction === null }"
    >
      <div class="fill" :style="{ width: fraction === null ? '30%' : `${fraction * 100}%` }"></div>
    </div>
    <p v-if="job.error" class="caption danger message">{{ job.error }}</p>
    <ul v-if="job.warnings.length" class="caption secondary message warnings">
      <li v-for="(warning, index) in job.warnings" :key="index">{{ warning }}</li>
    </ul>
    <div v-if="canNavigate && job.instances.length" class="instances">
      <button
        v-for="instance in job.instances"
        :key="instance.id"
        type="button"
        class="button small accent"
        @click="emit('open', instance.id)"
      >
        {{ t("open", { name: instance.name }) }}
      </button>
    </div>
  </li>
</template>

<style scoped>
.job {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px) 0;
  border-top: 1px solid var(--stroke-divider, ButtonBorder);
}

.job:first-child {
  border-top: 0;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2, 8px);
}

.text {
  flex: 1;
  min-width: 0;
}

.name {
  overflow-wrap: anywhere;
}

.bar {
  position: relative;
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--fill-well, ButtonFace);
}

.fill {
  height: 100%;
  border-radius: 2px;
  background: var(--accent-fill, AccentColor);
  transition: width 200ms linear;
}

.indeterminate .fill {
  animation: slide 1.4s ease-in-out infinite;
}

@keyframes slide {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(340%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: none;
  }

  .indeterminate .fill {
    animation: none;
    width: 100% !important;
    opacity: 0.4;
  }
}

.message {
  overflow-wrap: anywhere;
}

.warnings {
  margin: 0;
  padding-left: var(--space-4, 16px);
}

.instances {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2, 8px);
}
</style>
