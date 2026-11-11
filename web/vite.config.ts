/// <reference types="vitest/config" />
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// The frame client is the host's, served at the package root as
// `__hanafubuki/frame.js`. Its import stays external, written relative to the
// built chunks, which sit beside `ui/index.html`.
const FRAME_CLIENT = "@hanafubuki/frame";

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
      external: [FRAME_CLIENT],
      output: { paths: { [FRAME_CLIENT]: "../__hanafubuki/frame.js" } },
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
