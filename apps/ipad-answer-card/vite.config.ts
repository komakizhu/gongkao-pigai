import { defineConfig, type Plugin } from "vite";

function precacheManifest(): Plugin {
  return {
    name: "answer-recorder-precache-manifest",
    generateBundle(_options, bundle) {
      const assets = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg", "./sw.js", "./precache-manifest.js", ...Object.keys(bundle)
        .filter((fileName) => /\.(?:js|css)$/.test(fileName))
        .map((fileName) => `./${fileName}`)];
      this.emitFile({ type: "asset", fileName: "precache-manifest.js", source: `self.__ANSWER_RECORDER_PRECACHE = ${JSON.stringify([...new Set(assets)])};` });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [precacheManifest()],
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
