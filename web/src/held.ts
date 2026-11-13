import { computed } from "vue";

/**
 * The last message `source` gave, kept while it is gone: an InfoBar closes
 * through its `open` prop and collapses, and its text must stay while it does.
 */
export function useLastMessage(source: () => string | null | undefined) {
  let last = "";
  return computed(() => (last = source() || last));
}
