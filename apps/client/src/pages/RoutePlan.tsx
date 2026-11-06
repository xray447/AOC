import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import { Recommend } from "./Recommend";
import { RoutePlanner } from "./RoutePlanner";

/**
 * 「航路规划」一页（IA-09 / D-11）：先推荐目的地、再规划航路。
 *
 * `/recommend` 与 `/route` 都落在这一页（深链带 `?dep=` / `?arr=`）：推荐卡片点选后
 * 机场直接填进下方表单，不再跳页重新确认机型/巡航高度。
 */
export function RoutePlan() {
  const { tr } = useI18n();
  const { settings } = useApp();
  const [params, setParams] = useSearchParams();
  const [dep, setDep] = useState(() => params.get("dep") || settings.home_airport || "");
  const [arr, setArr] = useState(() => params.get("arr") || "");

  const update = (nextDep: string, nextArr: string) => {
    setDep(nextDep);
    setArr(nextArr);
    const query: Record<string, string> = {};
    if (nextDep) query.dep = nextDep;
    if (nextArr) query.arr = nextArr;
    setParams(query, { replace: true });
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("航路规划", "Route planning")}</h2>
          <p>{tr("先按可用时间挑一个目的地，再生成航路（AIP → 覆盖检查 → Pre-train 图，失败给 SimBrief）",
            "Pick a destination by available time, then plan the route (AIP → coverage → graph, SimBrief as fallback)")}</p>
        </div>
      </div>

      <Recommend
        embedded
        base={dep}
        onBaseChange={(value) => update(value, arr)}
        onPick={(nextDep, nextArr) => update(nextDep, nextArr)}
      />

      <RoutePlanner
        embedded
        depValue={dep}
        arrValue={arr}
        onDepChange={(value) => update(value, arr)}
        onArrChange={(value) => update(dep, value)}
      />
    </div>
  );
}
