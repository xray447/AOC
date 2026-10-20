using System.Globalization;
using System.Text;

namespace SimLinkProbe;

/// <summary>
/// 把一次采集渲染成单文件 HTML 报告：左侧遥测卡片 + ALT PROFILE / V/S 曲线，
/// 对标另一款落地评分工具的右栏。只用内联 SVG，无外部依赖。
/// </summary>
public static class Report
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    public static void WriteHtml(string outDir, List<TrackSample> samples, List<Touchdown> touchdowns,
        SessionReport session)
    {
        File.WriteAllText(Path.Combine(outDir, "report.html"), Build(samples, touchdowns, session));
    }

    private static string Build(List<TrackSample> samples, List<Touchdown> touchdowns, SessionReport session)
    {
        var sb = new StringBuilder(16384);
        sb.Append("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
          .Append("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
          .Append("<title>AOC 落地报告</title><style>").Append(Css).Append("</style></head><body><div class=\"wrap\">");

        // 顶栏
        sb.Append("<div class=\"head\"><div><div class=\"kicker\">LANDING REPORT</div><div class=\"title\">")
          .Append(Esc(session.Aircraft.Length > 0 ? session.Aircraft : "机型未记录"))
          .Append("</div></div><div class=\"meta\">")
          .Append($"duration {Num(session.DurationS)}s · samples {session.Samples}");
        if (session.FrameCount is int frames && frames > 0)
            sb.Append($" · frames {frames} · fps {Num(session.Fps ?? 0)}");
        sb.Append("<br>").Append(Esc(session.Source)).Append(" · SimConnect ").Append(Esc(session.SimConnectVersion))
          .Append("</div></div>");

        if (touchdowns.Count == 0)
        {
            sb.Append("<div class=\"empty\">未检测到落地（on_ground 未发生 false→true 跳变）</div>");
        }
        else
        {
            foreach (var td in touchdowns)
            {
                sb.Append("<div class=\"tdhead\"><span class=\"dot\"></span>落地 ")
                  .Append(Esc($"{td.Airport}/{td.RunwayName}")).Append(" @ t=").Append(Num(td.T)).Append("s")
                  .Append("<span class=\"muted\"> · 距跑道参考点 ").Append(Num(td.RunwayDistNm ?? 0)).Append("nm")
                  .Append(" · 航向差 ").Append(Num(td.RunwayHdgDiffDeg ?? 0)).Append("°</span></div>");

                sb.Append("<div class=\"grid\">");
                Card(sb, "V/S", Num(td.VsFpm, 0), "fpm");
                Card(sb, "G-FORCE", Num(td.GForcePeak ?? td.GForce, 2), "g",
                    td.GForcePeak is double pk && Math.Abs(pk - td.GForce) > 0.001
                        ? $"峰值 {Num(pk, 2)} / 触地帧 {Num(td.GForce, 2)}"
                        : "触地帧");
                Card(sb, "IAS", Num(td.IasKt, 0), "kt");
                Card(sb, "PITCH", Num(td.PitchDeg ?? 0, 1), "°");
                Card(sb, "BANK", Num(td.BankDeg ?? 0, 1), "°");
                Card(sb, "HDG", Num(td.HdgDeg, 1), "°");
                Card(sb, "AOA", Num(td.AoaDeg, 1), "°");
                Card(sb, "RUNWAY", Esc(td.RunwayName ?? "-"), "", Esc(td.Airport ?? "-"));
                Card(sb, "接地区", td.RunwayAlongM is double al ? Num(al, 0) : "—", "m",
                    td.RunwayLengthM is double ln && td.RunwayAlongM is double a2
                        ? $"剩余 {Num(Math.Max(0, ln - a2), 0)} m" : "距入口");
                Card(sb, "TD DEV", td.RunwayLateralM is double lat2 ? Num(Math.Abs(lat2), 1) : "—",
                    td.RunwayLateralM is double lv ? (lv >= 0 ? "m 右" : "m 左") : "m", "中心线横向偏差");
                sb.Append("</div>");
                AppendRunwayPanel(sb, td);
            }
        }

        AppendChart(sb, "ALT PROFILE", "ft", samples, s => s.AglFt, touchdowns.Count > 0 ? touchdowns[0].T : null, "#3ddc97");
        AppendChart(sb, "VERTICAL SPEED", "fpm", samples, s => s.VsFpm, touchdowns.Count > 0 ? touchdowns[0].T : null, "#5b9dff");
        AppendChart(sb, "G FORCE", "g", samples, s => s.GForce, touchdowns.Count > 0 ? touchdowns[0].T : null, "#ffb547");

        sb.Append("<div class=\"foot\">samples 来自 flight.jsonl（").Append(session.Samples).Append(" 条，")
          .Append(Num(samples.Count > 0 ? samples[^1].T : 0)).Append("s）；曲线为逐样本折线，落地竖线为 touchdown 时刻。</div>");
        sb.Append("</div></body></html>");
        return sb.ToString();
    }

    private static void Card(StringBuilder sb, string label, string value, string unit, string? sub = null)
    {
        sb.Append("<div class=\"card\"><div class=\"label\">").Append(Esc(label)).Append("</div><div class=\"value\">")
          .Append(value);
        if (unit.Length > 0) sb.Append("<span class=\"unit\">").Append(Esc(unit)).Append("</span>");
        sb.Append("</div>");
        if (sub != null) sb.Append("<div class=\"sub\">").Append(sub).Append("</div>");
        sb.Append("</div>");
    }

    private static void AppendChart(StringBuilder sb, string title, string unit, List<TrackSample> samples,
        Func<TrackSample, double> selector, double? markerT, string color)
    {
        const int W = 1040, H = 200, PadL = 52, PadR = 14, PadT = 14, PadB = 22;
        sb.Append("<div class=\"chart\"><div class=\"chart-title\">").Append(Esc(title))
          .Append("<span class=\"muted\"> · ").Append(Esc(unit)).Append("</span></div>");

        if (samples.Count < 2)
        {
            sb.Append("<div class=\"empty\">样本不足，无法绘图</div></div>");
            return;
        }

        double t0 = samples[0].T, t1 = samples[^1].T;

        // 用 2%~98% 分位裁剪：载入瞬间的脏值（AGL 5 万英尺、VS 6250fpm、G=0）会把整条曲线压扁
        var values = new double[samples.Count];
        for (int i = 0; i < samples.Count; i++) values[i] = selector(samples[i]);
        Array.Sort(values);
        double yMin = values[(int)(values.Length * 0.02)];
        double yMax = values[Math.Min(values.Length - 1, (int)(values.Length * 0.98))];
        if (yMax - yMin < 1e-6) { yMax += 1; yMin -= 1; }
        double pad = (yMax - yMin) * 0.08;
        yMin -= pad; yMax += pad;
        double span = yMax - yMin;
        int digits = span >= 20 ? 0 : span >= 2 ? 1 : 2;

        double Spx(double t) => PadL + (t - t0) / Math.Max(1e-6, t1 - t0) * (W - PadL - PadR);
        double Spy(double v)
        {
            double y = H - PadB - (v - yMin) / (yMax - yMin) * (H - PadT - PadB);
            return Math.Clamp(y, PadT, H - PadB);
        }

        sb.Append("<svg viewBox=\"0 0 ").Append(W).Append(' ').Append(H).Append("\" preserveAspectRatio=\"none\">");

        // 网格 + Y 轴刻度
        for (int i = 0; i <= 4; i++)
        {
            double v = yMin + (yMax - yMin) * i / 4;
            double y = Spy(v);
            sb.Append("<line x1=\"").Append(Num(PadL)).Append("\" y1=\"").Append(Num(y))
              .Append("\" x2=\"").Append(Num(W - PadR)).Append("\" y2=\"").Append(Num(y))
              .Append("\" stroke=\"#1d2634\" stroke-width=\"1\"/>");
            sb.Append("<text x=\"").Append(Num(PadL - 6)).Append("\" y=\"").Append(Num(y + 3.5))
              .Append("\" fill=\"#6b7c93\" font-size=\"10\" text-anchor=\"end\">").Append(Num(v, digits)).Append("</text>");
        }
        // X 轴刻度
        for (int i = 0; i <= 4; i++)
        {
            double t = t0 + (t1 - t0) * i / 4;
            sb.Append("<text x=\"").Append(Num(Spx(t))).Append("\" y=\"").Append(Num(H - 6))
              .Append("\" fill=\"#6b7c93\" font-size=\"10\" text-anchor=\"middle\">").Append(Num(t, 0)).Append("s</text>");
        }

        // 曲线
        sb.Append("<polyline fill=\"none\" stroke=\"").Append(color)
          .Append("\" stroke-width=\"1.6\" stroke-linejoin=\"round\" stroke-linecap=\"round\" points=\"");
        for (int i = 0; i < samples.Count; i++)
        {
            if (i > 0) sb.Append(' ');
            sb.Append(Num(Spx(samples[i].T), 1)).Append(',').Append(Num(Spy(selector(samples[i])), 1));
        }
        sb.Append("\"/>");

        // 落地竖线
        if (markerT is double mt && mt >= t0 && mt <= t1)
        {
            double x = Spx(mt);
            sb.Append("<line x1=\"").Append(Num(x)).Append("\" y1=\"").Append(PadT)
              .Append("\" x2=\"").Append(Num(x)).Append("\" y2=\"").Append(H - PadB)
              .Append("\" stroke=\"#ffb547\" stroke-width=\"1\" stroke-dasharray=\"3 3\"/>");
            sb.Append("<text x=\"").Append(Num(x + 4)).Append("\" y=\"").Append(PadT + 10)
              .Append("\" fill=\"#ffb547\" font-size=\"10\">TD</text>");
        }

        sb.Append("</svg></div>");
    }

    /// <summary>跑道接地区示意：全长俯视图 + 中心线横向放大图。</summary>
    private static void AppendRunwayPanel(StringBuilder sb, Touchdown td)
    {
        if (td.RunwayLengthM is not double len || len <= 0 || td.RunwayAlongM is not double along) return;

        const int W = 1040, H = 190;
        const double PadL = 26, PadR = 26, StripY = 34, StripH = 40, ZoomY = 132;
        double x0 = PadL, x1 = W - PadR;
        double Px(double m) => x0 + Math.Clamp(m, 0, len) / len * (x1 - x0);
        double cy = StripY + StripH / 2;

        sb.Append("<div class=\"chart\"><div class=\"chart-title\">RUNWAY TOUCHDOWN ZONE<span class=\"muted\"> · ")
          .Append(Esc($"{td.Airport}/{td.RunwayName} · 全长 {Num(len, 0)} m")).Append("</span></div>")
          .Append("<svg viewBox=\"0 0 ").Append(W).Append(' ').Append(H).Append("\" preserveAspectRatio=\"none\">");

        // 跑道本体
        sb.Append("<rect x=\"").Append(Num(x0)).Append("\" y=\"").Append(Num(StripY))
          .Append("\" width=\"").Append(Num(x1 - x0)).Append("\" height=\"").Append(Num(StripH))
          .Append("\" fill=\"#111823\" stroke=\"#2a3646\" rx=\"2\"/>");

        // 中心线
        sb.Append("<line x1=\"").Append(Num(x0 + 10)).Append("\" y1=\"").Append(Num(cy))
          .Append("\" x2=\"").Append(Num(x1 - 10)).Append("\" y2=\"").Append(Num(cy))
          .Append("\" stroke=\"#3b4b5e\" stroke-width=\"1.5\" stroke-dasharray=\"12 10\"/>");

        // 入口斑马线
        for (int i = 0; i < 4; i++)
        {
            sb.Append("<rect x=\"").Append(Num(x0 + 4)).Append("\" y=\"").Append(Num(StripY + 5 + i * 9))
              .Append("\" width=\"12\" height=\"5\" fill=\"#8fa3ba\"/>");
        }

        // 接地区标记 300/600/900 m + 瞄准点
        foreach (int mark in new[] { 300, 600, 900 })
        {
            if (mark > len) continue;
            double x = Px(mark);
            int bars = mark == 300 ? 3 : mark == 600 ? 2 : 1;
            for (int b = 0; b < bars; b++)
            {
                sb.Append("<rect x=\"").Append(Num(x + b * 9)).Append("\" y=\"").Append(Num(cy - 13))
                  .Append("\" width=\"5\" height=\"26\" fill=\"#54657a\"/>");
            }
            sb.Append("<text x=\"").Append(Num(x)).Append("\" y=\"").Append(Num(StripY - 6))
              .Append("\" fill=\"#5f7387\" font-size=\"9\">").Append(mark).Append("m</text>");
        }

        // 落地点
        double tdx = Px(along);
        sb.Append("<circle cx=\"").Append(Num(tdx)).Append("\" cy=\"").Append(Num(cy))
          .Append("\" r=\"6\" fill=\"#ffb547\" stroke=\"#080b10\" stroke-width=\"1.5\"/>")
          .Append("<text x=\"").Append(Num(tdx)).Append("\" y=\"").Append(Num(StripY + StripH + 14))
          .Append("\" fill=\"#ffb547\" font-size=\"10\" text-anchor=\"middle\">TD ").Append(Num(along, 0))
          .Append("m</text>");

        // 跑道两端刻度
        sb.Append("<text x=\"").Append(Num(x0)).Append("\" y=\"").Append(Num(StripY + StripH + 14))
          .Append("\" fill=\"#5f7387\" font-size=\"9\">入口 0</text>")
          .Append("<text x=\"").Append(Num(x1)).Append("\" y=\"").Append(Num(StripY + StripH + 14))
          .Append("\" fill=\"#5f7387\" font-size=\"9\" text-anchor=\"end\">").Append(Num(len, 0)).Append("m</text>");

        // 横向放大（±20m）
        double latv = td.RunwayLateralM ?? 0;
        const double Half = 20;
        double Zx(double m) => (PadL + (W - PadR)) / 2 + ((W - PadL - PadR) / 2 - 22) * Math.Clamp(m / Half, -1, 1);
        sb.Append("<line x1=\"").Append(Num(PadL)).Append("\" y1=\"").Append(Num(ZoomY))
          .Append("\" x2=\"").Append(Num(W - PadR)).Append("\" y2=\"").Append(Num(ZoomY))
          .Append("\" stroke=\"#3b4b5e\" stroke-width=\"1.5\" stroke-dasharray=\"12 10\"/>");
        foreach (int tick in new[] { -20, -10, 0, 10, 20 })
        {
            sb.Append("<line x1=\"").Append(Num(Zx(tick))).Append("\" y1=\"").Append(Num(ZoomY - 4))
              .Append("\" x2=\"").Append(Num(Zx(tick))).Append("\" y2=\"").Append(Num(ZoomY + 4))
              .Append("\" stroke=\"#2a3646\"/>")
              .Append("<text x=\"").Append(Num(Zx(tick))).Append("\" y=\"").Append(Num(ZoomY + 20))
              .Append("\" fill=\"#5f7387\" font-size=\"9\" text-anchor=\"middle\">")
              .Append(tick > 0 ? "+" : "").Append(tick).Append("m</text>");
        }
        sb.Append("<text x=\"").Append(Num(PadL)).Append("\" y=\"").Append(Num(ZoomY - 28))
          .Append("\" fill=\"#5f7387\" font-size=\"9\">中心线横向放大 ±20m</text>");
        sb.Append("<circle cx=\"").Append(Num(Zx(latv))).Append("\" cy=\"").Append(Num(ZoomY))
          .Append("\" r=\"6\" fill=\"#ffb547\" stroke=\"#080b10\" stroke-width=\"1.5\"/>")
          .Append("<text x=\"").Append(Num(Zx(latv))).Append("\" y=\"").Append(Num(ZoomY - 11))
          .Append("\" fill=\"#ffb547\" font-size=\"10\" text-anchor=\"middle\">")
          .Append(Num(Math.Abs(latv), 1)).Append(latv >= 0 ? "m 右" : "m 左").Append("</text>");

        sb.Append("</svg></div>");
    }

    private static string Num(double v, int digits = 1)
        => v.ToString(digits <= 0 ? "0" : "0." + new string('#', digits), Inv);

    private static string Esc(string s)
        => s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");

    private const string Css = """
        :root{color-scheme:dark}
        *{box-sizing:border-box}
        body{margin:0;background:#080b10;color:#e6edf6;font:13px/1.45 "Segoe UI",system-ui,-apple-system,sans-serif}
        .wrap{max-width:1080px;margin:0 auto;padding:20px 18px 40px}
        .head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
              border-bottom:1px solid #1c2532;padding-bottom:14px;margin-bottom:18px}
        .kicker{font-size:10px;letter-spacing:2px;color:#5f7387}
        .title{font-size:22px;font-weight:600;letter-spacing:.5px}
        .meta{text-align:right;color:#7d8ea6;font-size:11px;line-height:1.6}
        .tdhead{display:flex;align-items:center;gap:8px;font-size:12px;color:#9fb0c6;margin:6px 0 10px}
        .dot{width:7px;height:7px;border-radius:50%;background:#3ddc97;box-shadow:0 0 8px #3ddc97}
        .muted{color:#6b7c93}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:18px}
        .card{background:#0e131a;border:1px solid #1b2431;border-radius:8px;padding:9px 11px}
        .label{font-size:10px;letter-spacing:1px;color:#6b7c93}
        .value{font:600 20px/1.2 Consolas,"SF Mono",monospace;color:#e6edf6;margin-top:2px}
        .unit{font-size:10px;color:#7d8ea6;margin-left:4px;font-weight:400}
        .sub{font-size:10px;color:#6b7c93;margin-top:2px}
        .chart{background:#0e131a;border:1px solid #1b2431;border-radius:8px;padding:10px 12px;margin-bottom:12px}
        .chart-title{font-size:10px;letter-spacing:1.4px;color:#8fa3ba;margin-bottom:4px}
        .chart svg{display:block;width:100%;height:200px}
        .empty{padding:14px;color:#7d8ea6;border:1px dashed #26313f;border-radius:8px}
        .foot{margin-top:14px;color:#5f7387;font-size:10px;line-height:1.6}
        """;
}
