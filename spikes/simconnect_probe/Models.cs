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
    /// <summary>坡度，右倾为正。</summary>
    [JsonPropertyName("bank_deg")] public double BankDeg { get; set; }
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
    /// <summary>触地后 2s 窗口内的 G 峰值（帧级采样，用于与落地评分工具对齐）。</summary>
    [JsonPropertyName("g_force_peak")] public double? GForcePeak { get; set; }
    /// <summary>触地瞬间俯仰角，抬头为正。</summary>
    [JsonPropertyName("pitch_deg")] public double? PitchDeg { get; set; }
    /// <summary>触地瞬间坡度，右倾为正。</summary>
    [JsonPropertyName("bank_deg")] public double? BankDeg { get; set; }
    /// <summary>接地点距跑道入口的纵向距离（米）。</summary>
    [JsonPropertyName("runway_along_m")] public double? RunwayAlongM { get; set; }
    /// <summary>接地点相对跑道中心线的横向偏差（米），右偏为正。</summary>
    [JsonPropertyName("runway_lateral_m")] public double? RunwayLateralM { get; set; }
    /// <summary>跑道长度（米），由反向跑道记录推算，缺失为 null。</summary>
    [JsonPropertyName("runway_length_m")] public double? RunwayLengthM { get; set; }
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
