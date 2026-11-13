import * as frame from "@hanafubuki/frame";
import { frameUi } from "@hanafubuki/ui";
import { createApp } from "vue";
import App from "./App.vue";
import { pickLocale, translator } from "./i18n";
import "./style.css";

// The bundle's Browse asks for a folder without a title; the page names its dialog.
const client = {
  ...frame,
  pickDirectory: () =>
    frame.pickDirectory({
      title: translator(pickLocale(frame.locale() ?? undefined, navigator.language))("chooseTitle"),
    }),
};

createApp(App).use(frameUi(client)).mount("#app");
