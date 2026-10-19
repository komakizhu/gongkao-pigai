import esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian"],
  format: "cjs",
  platform: "node",
  target: "es2020",
  outfile: "main.js",
  sourcemap: false,
  logLevel: "info",
});
