<script setup lang="ts" generic="T extends string">
// One value of a few, as the kit's tabs (`tabs`/`tab`, class API 1) in a
// radio group: the chosen tab is `aria-checked`, the only one in the tab
// order, and the arrow keys move the choice as a native radio group does.
import { nextTick, useTemplateRef } from "vue";

const props = defineProps<{ label: string; options: { value: T; label: string }[] }>();
const model = defineModel<T>({ required: true });
const group = useTemplateRef<HTMLElement>("group");

const STEPS: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

function move(event: KeyboardEvent, index: number) {
  const step = STEPS[event.key];
  if (step === undefined) return;
  event.preventDefault();
  const next = (index + step + props.options.length) % props.options.length;
  model.value = props.options[next].value;
  void nextTick(() => group.value?.querySelectorAll<HTMLElement>(".tab")[next]?.focus());
}
</script>

<template>
  <div ref="group" class="tabs" role="radiogroup" :aria-label="label">
    <button
      v-for="(option, index) in options"
      :key="option.value"
      type="button"
      class="tab"
      role="radio"
      :aria-checked="option.value === model"
      :tabindex="option.value === model ? 0 : -1"
      @click="model = option.value"
      @keydown="move($event, index)"
    >
      {{ option.label }}
    </button>
  </div>
</template>
