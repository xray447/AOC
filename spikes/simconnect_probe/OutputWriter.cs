using System.Text.Json;

namespace SimLinkProbe;

public static class OutputWriter
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    public static string FlightPath(string outDir) => Path.Combine(outDir, "flight.jsonl");

    /// <summary>逐行实时写 flight.jsonl，进程被强杀也不丢已采集样本。</summary>
    public static StreamWriter OpenFlightWriter(string outDir)
    {
        Directory.CreateDirectory(outDir);
        return new StreamWriter(FlightPath(outDir), append: false) { AutoFlush = true };
    }

    public static void WriteSample(StreamWriter writer, TrackSample sample)
        => writer.WriteLine(JsonSerializer.Serialize(sample));

    public static void Save(string outDir, List<TrackSample> samples, List<Touchdown> touchdowns,
        List<FlightEvent> events, SessionReport session, bool writeFlight = true)
    {
        Directory.CreateDirectory(outDir);
        if (writeFlight)
        {
            using var w = new StreamWriter(FlightPath(outDir));
            foreach (var s in samples)
                WriteSample(w, s);
        }
        File.WriteAllText(Path.Combine(outDir, "touchdowns.json"),
            JsonSerializer.Serialize(touchdowns, Json));
        File.WriteAllText(Path.Combine(outDir, "events.json"),
            JsonSerializer.Serialize(events, Json));
        File.WriteAllText(Path.Combine(outDir, "session.json"),
            JsonSerializer.Serialize(session, Json));
        Report.WriteHtml(outDir, samples, touchdowns, session);
    }
}
