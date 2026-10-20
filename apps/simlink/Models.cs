using System.Text.Json.Serialization;

namespace AocSimLink;

public sealed class Sample
{
    [JsonPropertyName("seq")] public long Seq { get; set; }
    [JsonPropertyName("t")] public double T { get; set; }
    [JsonPropertyName("lat")] public double Lat { get; set; }
    [JsonPropertyName("lon")] public double Lon { get; set; }
    [JsonPropertyName("alt_ft")] public double AltFt { get; set; }
    [JsonPropertyName("agl_ft")] public double AglFt { get; set; }
    [JsonPropertyName("gs_kt")] public double GsKt { get; set; }
    [JsonPropertyName("ias_kt")] public double IasKt { get; set; }
    [JsonPropertyName("vs_fpm")] public double VsFpm { get; set; }
    [JsonPropertyName("hdg_true")] public double HdgTrue { get; set; }
    [JsonPropertyName("pitch_deg")] public double PitchDeg { get; set; }
    [JsonPropertyName("bank_deg")] public double BankDeg { get; set; }
    [JsonPropertyName("on_ground")] public bool OnGround { get; set; }
    [JsonPropertyName("fuel_kg")] public double FuelKg { get; set; }
    [JsonPropertyName("g")] public double G { get; set; } = 1.0;
    [JsonPropertyName("gear")] public int Gear { get; set; }
    [JsonPropertyName("flaps")] public int Flaps { get; set; }
    [JsonPropertyName("paused")] public bool Paused { get; set; }
    [JsonPropertyName("sim_rate")] public double SimRate { get; set; } = 1.0;
    [JsonPropertyName("mode")] public string Mode { get; set; } = "TAXI";
    [JsonPropertyName("saved")] public bool Saved { get; set; } = true;
}

public sealed class FlightEvent
{
    [JsonPropertyName("seq")] public long Seq { get; set; }
    [JsonPropertyName("t")] public double T { get; set; }
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("data")] public Dictionary<string, object?> Data { get; set; } = new();
}

public sealed class RecordingInfo
{
    [JsonPropertyName("recording")] public bool Recording { get; set; }
    [JsonPropertyName("recording_id")] public string? RecordingId { get; set; }
    [JsonPropertyName("recording_started_at")] public string? RecordingStartedAt { get; set; }
    [JsonPropertyName("last_finished_id")] public string? LastFinishedId { get; set; }
    [JsonPropertyName("samples")] public int Samples { get; set; }
    [JsonPropertyName("events")] public int Events { get; set; }
    [JsonPropertyName("phase")] public string Phase { get; set; } = "PREFLIGHT";
    [JsonPropertyName("sim_connected")] public bool SimConnected { get; set; }
    [JsonPropertyName("aircraft_title")] public string? AircraftTitle { get; set; }
    [JsonPropertyName("sim_version")] public string? SimVersion { get; set; }
    [JsonPropertyName("version")] public string Version { get; set; } = "0.1.0";
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("auto_start")] public bool AutoStart { get; set; } = true;
}

public sealed class RuntimeInfo
{
    [JsonPropertyName("pid")] public int Pid { get; set; }
    [JsonPropertyName("port")] public int Port { get; set; }
    [JsonPropertyName("url")] public string Url { get; set; } = "";
    [JsonPropertyName("token")] public string Token { get; set; } = "";
    [JsonPropertyName("started_at")] public string StartedAt { get; set; } = "";
    [JsonPropertyName("source")] public string Source { get; set; } = "";
}

public static class TimeUtil
{
    public static string Iso(DateTime utc) =>
        utc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", System.Globalization.CultureInfo.InvariantCulture);
}
