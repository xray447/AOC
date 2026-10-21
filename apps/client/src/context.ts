import { useOutletContext } from "react-router-dom";
import type { Bootstrap, NavdataStatus, OpsStatus, RecordingStatus, Settings } from "./types";

export interface AppContextValue {
  bootstrap: Bootstrap;
  settings: Settings;
  navdata: NavdataStatus;
  recording: RecordingStatus;
  opsStatus: OpsStatus | null;
  dark: boolean;
  refresh: () => Promise<void>;
  saveSettings: (patch: Partial<Settings>) => Promise<Settings>;
}

export function useApp(): AppContextValue {
  return useOutletContext<AppContextValue>();
}
