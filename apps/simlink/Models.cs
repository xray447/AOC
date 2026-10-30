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
    /// <summary>总重（磅 → kg）：SimVar `TOTAL WEIGHT`。</summary>
    [JsonPropertyName("total_weight_kg")] public double TotalWeightKg { get; set; }
    /// <summary>燃油重量（磅 → kg）：SimVar `FUEL TOTAL QUANTITY WEIGHT`。</summary>
    [JsonPropertyName("fuel_weight_kg")] public double FuelWeightKg { get; set; }
    /// <summary>四台发动机转速（`GENERAL ENG RPM:1..4`），用于判定发动机运转。</summary>
    [JsonPropertyName("eng_rpm")] public double[] EngRpm { get; set; } = new double[4];
    /// <summary>四台发动机 N1（%），`GENERAL ENG RPM` 恒为 0 时的退化判定。</summary>
    [JsonPropertyName("eng_n1")] public double[] EngN1 { get; set; } = new double[4];
    /// <summary>四台发动机燃烧状态（0/1），退化判定用。</summary>
    [JsonPropertyName("eng_combustion")] public double[] EngCombustion { get; set; } = new double[4];
    /// <summary>停机刹车（`BRAKE PARKING POSITION`）：自动收尾的硬信号（§30）。</summary>
    [JsonPropertyName("parking_brake")] public bool ParkingBrake { get; set; }
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
    /// <summary>发动机运转时间（秒，模拟时间）：任一 RPM &gt; 200 起算，四台全部 &lt; 200 持续 5s 停止。</summary>
    [JsonPropertyName("engine_seconds")] public int EngineSeconds { get; set; }
    /// <summary>已飞行时间（秒，模拟时间）：takeoff 起算，landing 冻结。</summary>
    [JsonPropertyName("flight_seconds")] public int FlightSeconds { get; set; }
    /// <summary>计时走退化判定（N1/燃烧）或记录开始时发动机已在转，无法精确回溯。</summary>
    [JsonPropertyName("engine_estimated")] public bool EngineEstimated { get; set; }
    [JsonPropertyName("sim_connected")] public bool SimConnected { get; set; }
    [JsonPropertyName("aircraft_title")] public string? AircraftTitle { get; set; }
    [JsonPropertyName("sim_version")] public string? SimVersion { get; set; }
    [JsonPropertyName("version")] public string Version { get; set; } = "0.1.0";
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("auto_start")] public bool AutoStart { get; set; } = true;
    /// <summary>自动开录起点：engine（默认）/ taxi / takeoff。</summary>
    [JsonPropertyName("auto_start_mode")] public string AutoStartMode { get; set; } = "engine";
    /// <summary>连续重连失败次数（simconnect 源）：0 = 当前连接正常或从未失败。</summary>
    [JsonPropertyName("reconnect_attempts")] public int ReconnectAttempts { get; set; }
    /// <summary>最近一次连模拟器失败的原始错误（异常类型 + message），供界面折叠展示。</summary>
    [JsonPropertyName("last_connect_error")] public string? LastConnectError { get; set; }
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
