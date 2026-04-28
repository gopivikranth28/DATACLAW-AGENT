import { defineChannelPluginEntry } from "openclaw/plugin-sdk/channel-core";
import { dataclawFrontendPlugin } from "./src/channel.js";
import { registerDataclawFrontendRoutes } from "./src/http-routes.js";

export default defineChannelPluginEntry({
  id: "dataclaw-frontend",
  name: "Dataclaw Frontend",
  description: "Dataclaw frontend channel plugin — routes messages between Dataclaw UI and OpenClaw",
  plugin: dataclawFrontendPlugin,
  registerFull(api) {
    registerDataclawFrontendRoutes(api);
  },
});
