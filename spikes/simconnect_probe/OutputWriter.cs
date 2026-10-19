using System.Text.Json;

namespace SimLinkProbe;

public static class OutputWriter
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    public static void Save(string outDir, List<TrackSample> samples, List<Touchdown> touchdowns,
        List<FlightEvent> events, SessionReport session)
    {
        Directory.CreateDirectory(outDir);
        using (var w = new StreamWriter(Path.Combine(outDir, "flight.jsonl")))
        {
            foreach (var s in samples)
                w.WriteLine(JsonSerializer.Serialize(s));
        }
        File.WriteAllText(Path.Combine(outDir, "touchdowns.json"),
            JsonSerializer.Serialize(touchdowns, Json));
        File.WriteAllText(Path.Combine(outDir, "events.json"),
            JsonSerializer.Serialize(events, Json));
        File.WriteAllText(Path.Combine(outDir, "session.json"),
            JsonSerializer.Serialize(session, Json));
    }
}
