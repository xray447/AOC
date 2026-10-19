using System.Text.Json.Serialization;

namespace SimLinkProbe;

/// <summary>归一化后的 1Hz 飞行样本；SimConnect 与回放共用。</summary>
public sealed class TrackSample
{
    [JsonPropertyName("t")] public double T { get; set; }
    [JsonPropertyName("lat")] public double Lat { get; set; }
    [JsonPropertyName("lon")] public double Lon { get; set; }
    [JsonPropertyName("alt_ft")] public double AltFt { get; set; }
    [JsonPropertyName("agl_ft")] public double AglFt { get; set; }
    [JsonPropertyName("gs_kt")] public double GsKt { get; set; }
    [JsonPropertyName("vs_fpm")] public double VsFpm { get; set; }
    [JsonPropertyName("hdg_deg")] public double HdgDeg { get; set; }
    [JsonPropertyName("on_ground")] public bool OnGround { get; set; }
    [JsonPropertyName("fuel_kg")] public double FuelKg { get; set; }
    [JsonPropertyName("g_force")] public double GForce { get; set; }
    [JsonPropertyName("pitch_deg")] public double PitchDeg { get; set; }
    [JsonPropertyName("aoa_deg")] public double AoaDeg { get; set; }
    [JsonPropertyName("ias_kt")] public double IasKt { get; set; }
    [JsonPropertyName("gear")] public int Gear { get; set; }
    [JsonPropertyName("flaps")] public int Flaps { get; set; }
}

public sealed class Runway
{
    [JsonPropertyName("airport")] public string Airport { get; set; } = "";
    [JsonPropertyName("runway")] public string Name { get; set; } = "";
    [JsonPropertyName("heading")] public double Heading { get; set; }
    [JsonPropertyName("lat")] public double Lat { get; set; }
    [JsonPropertyName("lon")] public double Lon { get; set; }
    [JsonPropertyName("elev_ft")] public double ElevFt { get; set; }
}

public sealed class Touchdown
{
    [JsonPropertyName("t")] public double T { get; set; }
    [JsonPropertyName("lat")] public double Lat { get; set; }
    [JsonPropertyName("lon")] public double Lon { get; set; }
    [JsonPropertyName("vs_fpm")] public double VsFpm { get; set; }
    [JsonPropertyName("g_force")] public double GForce { get; set; }
    [JsonPropertyName("aoa_deg")] public double AoaDeg { get; set; }
    [JsonPropertyName("ias_kt")] public double IasKt { get; set; }
    [JsonPropertyName("hdg_deg")] public double HdgDeg { get; set; }
    [JsonPropertyName("airport")] public string? Airport { get; set; }
    [JsonPropertyName("runway")] public string? RunwayName { get; set; }
    [JsonPropertyName("runway_dist_nm")] public double? RunwayDistNm { get; set; }
    [JsonPropertyName("runway_hdg_diff_deg")] public double? RunwayHdgDiffDeg { get; set; }
}

public sealed class FlightEvent
{
    [JsonPropertyName("t")] public double T { get; set; }
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("detail")] public string Detail { get; set; } = "";
}

public sealed class SessionReport
{
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("samples")] public int Samples { get; set; }
    [JsonPropertyName("duration_s")] public double DurationS { get; set; }
    [JsonPropertyName("touchdowns")] public int Touchdowns { get; set; }
    [JsonPropertyName("events")] public int Events { get; set; }
    [JsonPropertyName("fps")] public double? Fps { get; set; }
    [JsonPropertyName("frame_count")] public int? FrameCount { get; set; }
    [JsonPropertyName("simconnect")] public string SimConnectVersion { get; set; } = "";
    [JsonPropertyName("warnings")] public List<string> Warnings { get; set; } = new();
    [JsonPropertyName("aircraft")] public string Aircraft { get; set; } = "";
}
