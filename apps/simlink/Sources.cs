using System.Diagnostics;
using System.Text.Json;

namespace AocSimLink;

public interface ISimSource : IDisposable
{
    string Name { get; }
    bool Connected { get; }
    string? SimVersion { get; }
    string? AircraftTitle { get; }
    /// <summary>
    /// `Sample.T` 是否已经是模拟时间（demo/replay 按倍速推进时钟）。
    /// false 表示 T 是真实秒，Engine 累计模拟时间时要乘以 `sim_rate`。
    /// </summary>
    bool ClockIsSimTime => false;
    /// <summary>连续连接失败次数（只有 simconnect 源有意义，其余恒为 0）。</summary>
    int ReconnectAttempts => 0;
    /// <summary>最近一次连接模拟器失败的原始错误（异常类型 + message）。</summary>
    string? LastConnectError => null;
    /// <summary>立刻重建连接（手动触发；后台循环本来也会按 5s 退避重试）。</summary>
    void Reconnect() { }
    /// <summary>连接状态变化：true=已连上模拟器。</summary>
    event Action<bool>? ConnectionChanged { add { } remove { } }
    event Action<Sample>? Frame;
    void Start();
    void Stop();
}

/// <summary>合成一次 ZBAA→ZSSS 飞行，用于无模拟器时跑通 UI/验收流程。</summary>
public sealed class DemoSource : ISimSource
{
    private readonly double _speed;
    private CancellationTokenSource? _cts;
    private readonly Stopwatch _clock = new();

    public DemoSource(double speed = 12.0) => _speed = Math.Max(1.0, speed);

    public string Name => "demo";
    public bool Connected => true;
    public string? SimVersion => "demo-1.0";
    public string? AircraftTitle => "AOC Demo A320";
    public bool ClockIsSimTime => true;
    public event Action<Sample>? Frame;

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _clock.Start();
        _ = Task.Run(async () =>
        {
            var last = -1.0;
            while (!_cts.IsCancellationRequested)
            {
                var t = _clock.Elapsed.TotalSeconds * _speed;
                if (t - last >= 0.1)
                {
                    last = t;
                    try { Frame?.Invoke(MakeSample(t, _speed)); }
                    catch { /* 演示源不影响服务 */ }
                }
                await Task.Delay(100, _cts.Token).ContinueWith(_ => { });
            }
        });
    }

    private static Sample MakeSample(double t, double speed)
    {
        const double depLat = 40.0801, depLon = 116.5846, arrLat = 31.1979, arrLon = 121.3363;
        const double takeoff = 30, touchdown = 232;
        double f = Math.Clamp((t - takeoff) / (touchdown - takeoff), 0, 1);
        double lat = depLat + (arrLat - depLat) * f;
        double lon = depLon + (arrLon - depLon) * f;
        double elev = 116 + (10 - 116) * f;
        double alt, vs, gs, agl;
        bool onGround;
        if (t < takeoff)
        {
            // 起飞前：先停 5s，再以 12kt / 25kt 滑行 —— 自动开录要在这一段就触发（§27）
            alt = elev; agl = 0; vs = 0; gs = t < 5 ? 0 : (t < 25 ? 12 : 25); onGround = true;
        }
        else if (t < 60)
        {
            var k = (t - takeoff) / 30.0;
            alt = elev + (22000 - elev) * k; agl = alt - elev; vs = 2600; gs = 160 + 120 * k; onGround = false;
        }
        else if (t < 160)
        {
            alt = 35000; agl = alt - elev; vs = 0; gs = 450; onGround = false;
        }
        else if (t < 210)
        {
            var k = (t - 160) / 50.0;
            alt = 35000 + (3000 - 35000) * k; agl = Math.Max(0, alt - elev); vs = -1800; gs = 300; onGround = false;
        }
        else if (t < touchdown)
        {
            var k = (t - 210) / (touchdown - 210.0);
            alt = 3000 + (elev - 3000) * k; agl = Math.Max(0, alt - elev);
            vs = t > 228 ? -150 : -700; gs = 150 - 20 * k; onGround = false;
        }
        else
        {
            // 落地后：减速到 15kt 滑行 → 中途停车 20s（旧判据会在这里误收尾）→ 滑到机位停稳
            alt = elev; agl = 0;
            vs = t < touchdown + 1.0 ? -150 : 0;
            if (t < touchdown + 8) gs = 125 - (125 - 15) * ((t - touchdown) / 8.0);
            else if (t < touchdown + 28) gs = 15;
            else if (t < touchdown + 48) gs = 0;
            else if (t < touchdown + 63) gs = 10;
            else gs = 0;
            onGround = true;
        }
        double g = t >= touchdown && t < touchdown + 1.0 ? 1.42 : (t > touchdown + 1 ? 1.02 : 1.0);
        double fuelKg = Math.Max(1200, 8000 - (t / 255.0) * 6200);
        // 演示机：10s 起动发动机（自动开录从这一刻+10s 起算）、滑到机位后才关车；
        // 停机刹车在到位时置位，配合关车触发自动收尾（§30）
        bool engineOn = t >= 10 && t < touchdown + 63;
        bool parkingBrake = t >= touchdown + 63;
        double rpm = engineOn ? 2400 : 0;
        return new Sample
        {
            T = t, Lat = lat, Lon = lon, AltFt = alt, AglFt = Math.Max(0, agl), GsKt = Math.Max(0, gs),
            IasKt = Math.Max(0, gs * 0.92), VsFpm = vs, HdgTrue = 165,
            PitchDeg = t < takeoff ? 0 : (t < 60 ? 8 : (t > 228 ? 5 : 2)),
            BankDeg = 0, OnGround = onGround, FuelKg = fuelKg,
            TotalWeightKg = 42000 + 14000 + fuelKg, FuelWeightKg = fuelKg,
            EngRpm = new[] { rpm, rpm, 0, 0 }, EngN1 = new double[4], EngCombustion = new double[4],
            ParkingBrake = parkingBrake,
            G = g, Gear = t < 20 || t > 215 ? 1 : 0,
            Flaps = t < 15 ? 0 : (t < takeoff ? 1 : (t > 205 ? 3 : 0)),
            Paused = false, SimRate = speed,
        };
    }

    public void Stop() => _cts?.Cancel();

    public void Dispose()
    {
        Stop();
        _cts?.Dispose();
    }
}

/// <summary>回放 SimLink/探针录制的 JSONL，按真实时间倍速发出。</summary>
public sealed class ReplaySource : ISimSource
{
    private readonly string _path;
    private readonly double _speed;
    private readonly Stopwatch _clock = new();
    private CancellationTokenSource? _cts;
    private readonly List<Sample> _samples = new();

    public string Name => $"replay:{Path.GetFileName(_path)}";
    public bool Connected => true;
    public string? SimVersion => "replay";
    public string? AircraftTitle => "Replay";
    public bool ClockIsSimTime => true;
    public event Action<Sample>? Frame;

    public ReplaySource(string path, double speed = 4.0)
    {
        _path = path;
        _speed = Math.Max(0.1, speed);
        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            try
            {
                var s = JsonSerializer.Deserialize<Sample>(line,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                if (s != null) _samples.Add(s);
            }
            catch { /* 跳过坏行 */ }
        }
        _samples.Sort((a, b) => a.T.CompareTo(b.T));
    }

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _clock.Start();
        _ = Task.Run(async () =>
        {
            var t0 = _samples.FirstOrDefault()?.T ?? 0;
            int index = 0;
            while (!_cts.IsCancellationRequested && index < _samples.Count)
            {
                var target = t0 + _clock.Elapsed.TotalSeconds * _speed;
                while (index < _samples.Count && _samples[index].T <= target)
                {
                    try { Frame?.Invoke(_samples[index]); } catch { }
                    index++;
                }
                if (index >= _samples.Count) break;
                await Task.Delay(50, _cts.Token).ContinueWith(_ => { });
            }
        });
    }

    public void Stop() => _cts?.Cancel();

    public void Dispose()
    {
        Stop();
        _cts?.Dispose();
    }
}
