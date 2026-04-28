import { defineSetupPluginEntry } from "openclaw/plugin-sdk/channel-core";
import { dataclawFrontendPlugin } from "./src/channel.js";

export default defineSetupPluginEntry(dataclawFrontendPlugin);
