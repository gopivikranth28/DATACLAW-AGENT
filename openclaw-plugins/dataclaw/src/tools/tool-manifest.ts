// Stable, committed entry point for the dataclaw tool manifest. Re-exports
// from `tool-manifest.generated.ts`, which the Dataclaw OpenClaw install
// service writes from each user's live tool registry.
//
// `tool-manifest.generated.ts` is gitignored — never commit it. The
// `prebuild` npm script creates an empty placeholder if it is missing
// (e.g. on a fresh clone before the first install) so esbuild and tsc can
// resolve this import.
export { DATACLAW_TOOL_MANIFEST } from "./tool-manifest.generated.js";
