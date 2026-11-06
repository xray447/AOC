import { useOutletContext } from "react-router-dom";
import type { Bootstrap, NavdataStatus, OpsStatus, RecordingStatus, Settings } from "./types";

export interface AppContextValue {
  bootstrap: Bootstrap;
  settings: Settings;
  navdata: NavdataStatus;
  recording: RecordingStatus;
  opsStatus: OpsStatus | null;
  dark: boolean;
  /** IA-07：已登录联机模式时，客户端的航线/机队/运营规则三页变只读（服务端权威）。 */
  onlineMode: boolean;
  /** UI-08：顶栏「刷新」的计数；页面把它放进自己的加载依赖里即可跟着刷新。 */
  refreshKey: number;
  refresh: () => Promise<void>;
  saveSettings: (patch: Partial<Settings>) => Promise<Settings>;
  /** IA-10：从设置页重新打开首次运行向导。 */
  openWizard: () => void;
}

export function useApp(): AppContextValue {
  return useOutletContext<AppContextValue>();
}

/**
 * UI-08：页面级刷新信号。
 *
 * 顶栏的「刷新」以前只重取 settings/navdata/recording/opsStatus，页面自己的表格不会更新，
 * 与页面内同名按钮行为不一致。现在顶栏刷新会自增 `refreshKey`，页面把返回的 key 放进
 * `useEffect` 依赖里（`[load, refreshKey]`）就会一起重取数据。
 */
export function useRefreshKey(): number {
  return useApp().refreshKey;
}
