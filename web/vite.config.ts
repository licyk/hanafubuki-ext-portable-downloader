/// <reference types="vitest/config" />
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// The frame client, the Vue runtime and the component bundle are the host's,
// served at the package root under `__hanafubuki/`. Their imports stay
// external, written relative to the built chunks, which sit beside
// `ui/index.html`. `vue` must resolve to the same URL `ui.js` imports
// (`./vue.js` beside it), so the page and the components share one runtime.
const HOST_MODULES = {
  "@hanafubuki/frame": "../__hanafubuki/frame.js",
  "@hanafubuki/ui": "../__hanafubuki/ui.js",
  vue: "../__hanafubuki/vue.js",
};

export default defineConfig({
  // Relative URLs only: on Windows the package root is `/<id>/`, not `/`.
  base: "./",
  plugins: [vue()],
  build: {
    outDir: "../ui",
    emptyOutDir: true,
    assetsDir: "",
    // The polyfill would fetch() the preloads, and a frame's connect-src is 'none'.
    modulePreload: { polyfill: false },
    rollupOptions: {
      external: Object.keys(HOST_MODULES),
      output: { paths: HOST_MODULES },
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
