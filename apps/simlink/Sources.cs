using System.Diagnostics;
using System.Text.Json;

namespace AocSimLink;

public interface ISimSource : IDisposable
{
    string Name { get; }
    bool Connected { get; }
    string? SimVersion { get; }
    string? AircraftTitle { get; }
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
                    try { Frame?.Invoke(MakeSample(t)); }
                    catch { /* 演示源不影响服务 */ }
                }
                await Task.Delay(100, _cts.Token).ContinueWith(_ => { });
            }
        });
    }

    private static Sample MakeSample(double t)
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
            alt = elev; agl = 0; vs = 0; gs = t < 20 ? 8 : 25; onGround = true;
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
            alt = elev; agl = 0;
            vs = t < touchdown + 1.0 ? -150 : 0;
            var k = Math.Min(1.0, (t - touchdown) / 12.0);
            gs = 125 * (1 - k); onGround = true;
        }
        double g = t >= touchdown && t < touchdown + 1.0 ? 1.42 : (t > touchdown + 1 ? 1.02 : 1.0);
        return new Sample
        {
            T = t, Lat = lat, Lon = lon, AltFt = alt, AglFt = Math.Max(0, agl), GsKt = Math.Max(0, gs),
            IasKt = Math.Max(0, gs * 0.92), VsFpm = vs, HdgTrue = 165,
            PitchDeg = t < takeoff ? 0 : (t < 60 ? 8 : (t > 228 ? 5 : 2)),
            BankDeg = 0, OnGround = onGround, FuelKg = Math.Max(1200, 8000 - (t / 255.0) * 6200),
            G = g, Gear = t < 20 || t > 215 ? 1 : 0,
            Flaps = t < 15 ? 0 : (t < takeoff ? 1 : (t > 205 ? 3 : 0)),
            Paused = false, SimRate = 1.0,
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
