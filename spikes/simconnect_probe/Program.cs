using System.Globalization;
using System.Text.Json;

namespace SimLinkProbe;

internal static class Program
{
    private static int Main(string[] args)
    {
        var opts = ParseArgs(args);
        string outDir = opts.GetValueOrDefault("out", "out");
        string runwayCsv = opts.GetValueOrDefault("runways",
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "data", "runways.csv"));
        string? airport = opts.TryGetValue("airport", out var ap) ? ap.ToUpperInvariant() : null;
        var runways = Runways.LoadCsv(Path.GetFullPath(runwayCsv));

        if (opts.ContainsKey("sim"))
        {
            int seconds = int.Parse(opts.GetValueOrDefault("seconds", "120"), CultureInfo.InvariantCulture);
            int hz = int.Parse(opts.GetValueOrDefault("hz", "1"), CultureInfo.InvariantCulture);
            // 长时段采集时不方便回到终端按 Ctrl+C：touch 一个文件即可正常收尾落盘
            string stopFile = opts.GetValueOrDefault("stop-file", Path.Combine(outDir, "stop"));
            if (File.Exists(stopFile)) File.Delete(stopFile);
            return SimConnectSource.Run(outDir, seconds, hz, runways, airport, stopFile);
        }

        if (!opts.TryGetValue("replay", out var path))
        {
            Console.Error.WriteLine("用法: SimLinkProbe --replay <track.jsonl> [--out out] [--airport RJTT] [--aircraft A321]");
            Console.Error.WriteLine("      SimLinkProbe --sim [--seconds 120|0=直到 Ctrl+C] [--hz 1] [--airport RJTT] [--out out]");
            Console.Error.WriteLine("--sim 期间 flight.jsonl 逐行实时落盘，落地瞬间刷新 touchdowns.json / events.json；");
            Console.Error.WriteLine("Ctrl+C 正常收尾落盘；也可在另一终端新建 <out>\\stop 文件让它提前收尾（--stop-file 可改路径）。");
            Console.Error.WriteLine("未编译 SimConnect 时 --sim 会返回 3（需 MSFS SDK + 模拟器）。");
            return 2;
        }

        var samples = new List<TrackSample>();
        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var s = JsonSerializer.Deserialize<TrackSample>(line, OutputWriter.Json);
            if (s != null) samples.Add(s);
        }
        if (samples.Count == 0)
        {
            Console.Error.WriteLine($"回放文件没有样本: {path}");
            return 1;
        }

        var (touchdowns, events) = Analyzer.Analyze(samples, runways, airport);
        var session = new SessionReport
        {
            Source = $"replay:{Path.GetFileName(path)}",
            Samples = samples.Count,
            DurationS = Math.Round(samples[^1].T - samples[0].T, 1),
            Touchdowns = touchdowns.Count,
            Events = events.Count,
            Aircraft = opts.GetValueOrDefault("aircraft", ""),
            Warnings = new List<string>(),
        };
        if (runways.Count == 0)
            session.Warnings.Add("runways.csv 未加载，落地无法匹配跑道");

        OutputWriter.Save(outDir, samples, touchdowns, events, session);
        Console.WriteLine($"samples={session.Samples} duration={session.DurationS}s " +
                          $"touchdowns={session.Touchdowns} events={session.Events} out={outDir}");
        foreach (var td in touchdowns)
            Console.WriteLine($"  TD t={td.T}s vs={td.VsFpm}fpm g={td.GForce} " +
                              $"rwy={td.Airport}/{td.RunwayName} along={td.RunwayAlongM}m " +
                              $"dev={td.RunwayLateralM}m len={td.RunwayLengthM}m");
        return 0;
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < args.Length; i++)
        {
            var a = args[i];
            if (!a.StartsWith("--")) continue;
            var key = a[2..];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--"))
                d[key] = args[++i];
            else
                d[key] = "1";
        }
        return d;
    }
}
