import { useEffect } from "react";

import { connectEvents } from "./api/client";
import { AboutView } from "./components/AboutView";
import { ActionsView } from "./components/ActionsView";
import { Banner } from "./components/Banner";
import { LayoutView } from "./components/LayoutView";
import { ModulesView } from "./components/ModulesView";
import { SystemView } from "./components/SystemView";
import { ThemeView } from "./components/ThemeView";
import { TopBar } from "./components/TopBar";
import { WeatherView } from "./components/WeatherView";
import { YouTubeView } from "./components/YouTubeView";
import i18n, { loadDashboardStrings } from "./i18n";
import { useStore } from "./store";

export default function App() {
  const view = useStore((s) => s.view);
  const ready = useStore((s) => s.ready);

  useEffect(() => {
    void useStore.getState().load();
    void loadDashboardStrings(i18n.language);

    // The socket is both the liveness signal and the way we hear about
    // settings written elsewhere — the kiosk saving a layout, a second
    // window, or the backend reloading an edited YAML.
    return connectEvents({
      onStatus: (online) => useStore.getState().setOnline(online),
      onSettings: (settings) => useStore.getState().adoptSettings(settings),
    });
  }, []);

  return (
    <div className="app">
      <TopBar />
      <main className="content">
        <Banner />
        {ready && (
          <>
            {view === "theme" && <ThemeView />}
            {view === "modules" && <ModulesView />}
            {view === "weather" && <WeatherView />}
            {view === "youtube" && <YouTubeView />}
            {view === "actions" && <ActionsView />}
            {view === "layout" && <LayoutView />}
            {view === "system" && <SystemView />}
            {view === "about" && <AboutView />}
          </>
        )}
      </main>
    </div>
  );
}
