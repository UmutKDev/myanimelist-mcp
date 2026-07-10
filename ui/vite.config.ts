import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// Builds the entire app into one self-contained HTML file that the Python
// server ships as the ui://mal-mcp/app.html resource.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: "../src/mal_mcp/ui/dist",
    emptyOutDir: true,
    target: "es2022",
    assetsInlineLimit: 100_000_000,
  },
});
