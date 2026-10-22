using System.Text.Json;

namespace AocSimLink;

/// <summary>
/// 飞行状态机 + 本地队列。SimLink 只负责采集、自动起降、按 1Hz/2Hz（跑道窗口 0.1s）保存；
/// 落地指标、轨迹分段与日志由 aoc-core 处理。
/// </summary>
public sealed class Engine : IDisposable
{
    private readonly ISimSource _source;
    private readonly string _queueRoot;
    private readonly AdaptiveSampler _sampler = new();
    private readonly List<Sample> _samples = new();
    private readonly List<FlightEvent> _events = new();
    private readonly Queue<Sample> _preRoll = new();
    private readonly object _lock = new();
    private readonly JsonSerializerOptions _json = new() { WriteIndented = false };

    private StreamWriter? _queue;
    private bool _recording;
    private string? _recordingId;
    private string _startedAt = "";
    private double _recStartT;
    private double _nextSampleT;
    private long _seq;
    private long _evtSeq;
    private string _phase = "PREFLIGHT";
    private Sample? _prevFrame;
    private double? _airborneSince;
    private double? _groundSince;
    private bool _hasTakeoff;
    private double _hz = 1.0;
    private double _lastErrorT = -100;

    // 计时（P-04）：模拟时间累计，按 sim_rate 折算；暂停不计
    private double _simClock;
    private double _takeoffSim;
    private double? _landingSim;
    private bool _landed;
    private double _engineSeconds;
    private bool _engineRunning;
    private double? _engineOffSince;
    private bool _engineEstimated;

    public bool AutoStart { get; set; } = true;
    public double AutoStopHoldS { get; set; } = 30.0;
    public string? LastFinishedId { get; private set; }

    public Engine(ISimSource source, string home)
    {
        _source = source;
        _queueRoot = Path.Combine(home, "simlink-queue");
        Directory.CreateDirectory(_queueRoot);
        _source.Frame += OnFrame;
    }

    public string SourceName => _source.Name;

    public RecordingInfo Status()
    {
        lock (_lock)
        {
            return new RecordingInfo
            {
                Recording = _recording,
                RecordingId = _recordingId,
                RecordingStartedAt = _recording ? _startedAt : null,
                LastFinishedId = LastFinishedId,
                Samples = _samples.Count,
                Events = _events.Count,
                Phase = _phase,
                EngineSeconds = (int)Math.Round(Math.Max(0, _engineSeconds)),
                FlightSeconds = (int)Math.Round(FlightSecondsNow()),
                EngineEstimated = _recording && _engineEstimated,
                SimConnected = _source.Connected,
                AircraftTitle = _source.AircraftTitle,
                SimVersion = _source.SimVersion,
                Source = _source.Name,
                AutoStart = AutoStart,
            };
        }
    }

    /// <summary>最新一帧（未开始记录时也能取到），供实时状态与推出前 ZFW 校验。</summary>
    public Sample? LatestSample()
    {
        lock (_lock) return _prevFrame;
    }

    /// <summary>已飞行时间（秒）：takeoff 起算，landing 冻结；未起飞为 0。</summary>
    private double FlightSecondsNow()
    {
        if (!_recording || !_hasTakeoff) return 0;
        var end = _landed ? (_landingSim ?? _simClock) : _simClock;
        return Math.Max(0, end - _takeoffSim);
    }

    public (List<Sample> samples, long lastSeq) Samples(long since, int limit)
    {
        lock (_lock)
        {
            var list = _samples.Where(s => s.Seq > since).Take(Math.Max(1, limit)).ToList();
            return (list, _samples.Count == 0 ? -1 : _samples[^1].Seq);
        }
    }

    public (List<FlightEvent> events, long lastSeq) Events(long since, int limit)
    {
        lock (_lock)
        {
            var list = _events.Where(e => e.Seq > since).Take(Math.Max(1, limit)).ToList();
            return (list, _events.Count == 0 ? -1 : _events[^1].Seq);
        }
    }

    public void SetRate(double hz) => _hz = Math.Clamp(hz, 0.5, 4.0);

    public RecordingInfo StartRecording(bool manual)
    {
        lock (_lock)
        {
            if (_recording) return Status();
            _samples.Clear();
            _events.Clear();
            _seq = 0;
            _evtSeq = 0;
            _recordingId = Guid.NewGuid().ToString();
            _startedAt = TimeUtil.Iso(DateTime.UtcNow);
            _recStartT = _prevFrame?.T ?? 0;
            _nextSampleT = 0;
            _recording = true;
            // 计时归零：记录开始时发动机已在转 → 从此刻起算并标 estimated=true
            _engineSeconds = 0;
            _engineOffSince = null;
            _engineEstimated = _engineRunning;
            if (_landed)
            {
                // 上一次飞行已落地：不要把旧航班的起飞时刻算进新的记录
                _landed = false;
                _hasTakeoff = false;
                _takeoffSim = 0;
                _landingSim = null;
            }
            // 自动开始时把起飞前 20s 的预录帧补进来，保留起飞机场与起飞时刻；
            // 同时避免把 _hasTakeoff 重置成 false（否则落地后不会自动收尾）。
            var pre = new List<Sample>();
            if (!manual)
            {
                var frames = _preRoll.ToArray();
                for (int i = 0; i < frames.Length; i++)
                {
                    if (frames[i].OnGround) continue;
                    _recStartT = frames[i].T;
                    pre.AddRange(frames.Skip(i));
                    break;
                }
            }
            _hasTakeoff = !manual && pre.Count > 0;
            _phase = _hasTakeoff ? "CRUISE" : "PREFLIGHT";
            var dir = Path.Combine(_queueRoot, _recordingId);
            Directory.CreateDirectory(dir);
            _queue = new StreamWriter(Path.Combine(dir, "samples.jsonl"), append: false) { AutoFlush = true };
            AddEvent(0, "recording_started", new() { ["manual"] = manual, ["pre_roll"] = pre.Count });
            foreach (var frame in pre) SaveSample(frame);
            Console.Error.WriteLine($"recording started ({_recordingId}, manual={manual}, pre_roll={pre.Count})");
            return Status();
        }
    }

    public RecordingInfo StopRecording()
    {
        lock (_lock) return StopLocked();
    }

    private RecordingInfo StopLocked()
    {
        if (!_recording) return Status();
        _recording = false;
        LastFinishedId = _recordingId;
        AddEvent(Math.Max(0, (_prevFrame?.T ?? _recStartT) - _recStartT), "recording_stopped", new());
        try { _queue?.Dispose(); } catch { }
        _queue = null;
        try
        {
            var dir = Path.Combine(_queueRoot, _recordingId ?? "unknown");
            File.WriteAllText(Path.Combine(dir, "manifest.json"), JsonSerializer.Serialize(new
            {
                recording_id = _recordingId,
                started_at = _startedAt,
                samples = _samples.Count,
                events = _events.Count,
                source = _source.Name,
                aircraft = _source.AircraftTitle,
            }, _json));
        }
        catch { }
        Console.Error.WriteLine($"recording stopped ({_recordingId}, samples={_samples.Count})");
        return Status();
    }

    private void AddEvent(double t, string type, Dictionary<string, object?> data)
    {
        _events.Add(new FlightEvent { Seq = _evtSeq++, T = Math.Max(0, t), Type = type, Data = data });
    }

    private void OnFrame(Sample s)
    {
        lock (_lock)
        {
            try
            {
                _preRoll.Enqueue(s);
                while (_preRoll.Count > 0 && s.T - _preRoll.Peek().T > 20) _preRoll.Dequeue();
                var dt = _prevFrame == null ? 0 : s.T - _prevFrame.T;
                var simDt = dt > 0 && dt <= 3.0
                    ? dt * (_source.ClockIsSimTime ? 1.0 : (s.SimRate <= 0 ? 1.0 : s.SimRate))
                    : 0;
                if (!s.Paused)
                {
                    _simClock += simDt;
                    UpdateEngine(s, simDt);
                }
                UpdateStateMachine(s);
                if (!_recording && AutoStart && _airborneSince != null && s.T - _airborneSince >= 5.0)
                    StartRecording(manual: false);
                if (_recording) SaveSample(s);
            }
            catch (Exception exc)
            {
                if (s.T - _lastErrorT > 5)
                {
                    _lastErrorT = s.T;
                    Console.Error.WriteLine($"engine error: {exc.Message}");
                }
            }
            _prevFrame = s;
        }
    }

    private void UpdateStateMachine(Sample s)
    {
        bool fresh = _prevFrame != null && s.T - _prevFrame.T <= 3.0;
        if (!s.OnGround)
        {
            _groundSince = null;
            _airborneSince ??= s.T;
            if (fresh && _prevFrame!.OnGround)
            {
                _hasTakeoff = true;
                _takeoffSim = _simClock;   // 已飞行时间从此刻起算
                if (_recording) AddEvent(s.T - _recStartT, "takeoff", new());
                _phase = "TAKEOFF";
            }
            if (_phase is not ("APPROACH" or "LANDING"))
            {
                if (s.AglFt < 3000 && s.VsFpm < 0) _phase = "APPROACH";
                else if (s.VsFpm > 800) _phase = "CLIMB";
                else if (s.VsFpm < -800) _phase = "DESCENT";
                else if (s.AglFt > 5000) _phase = "CRUISE";
            }
        }
        else
        {
            _airborneSince = null;
            _groundSince ??= s.T;
            if (fresh && !_prevFrame!.OnGround)
            {
                _landed = true;
                _landingSim = _simClock;   // 已飞行时间冻结
                if (_recording) AddEvent(s.T - _recStartT, "landing", new()
                {
                    ["vs_fpm"] = s.VsFpm, ["g"] = s.G, ["lat"] = s.Lat, ["lon"] = s.Lon,
                });
                _phase = "LANDING";
            }
            if (_hasTakeoff && s.GsKt < 5) _phase = "TAXI_IN";
            if (_recording && _hasTakeoff && s.GsKt < 5 && s.T - _groundSince >= AutoStopHoldS)
                StopLocked();
        }
    }

    /// <summary>
    /// 发动机运转判定（P-04）：任一 RPM &gt; 200 视为已启动并开始累计；
    /// 四台全部 &lt; 200 持续 5s 视为全部关车、停止累计，再启动继续累加（不清零）。
    /// 部分涡扇 RPM 恒为 0：退回 N1 &gt; 20% 或 ENG COMBUSTION 判定并标 estimated。
    /// </summary>
    private void UpdateEngine(Sample s, double simDt)
    {
        var rpmRunning = AnyAbove(s.EngRpm, 200);
        var fallbackRunning = AnyAbove(s.EngN1, 20) || AnyAbove(s.EngCombustion, 0.5);
        var running = rpmRunning || fallbackRunning;
        if (fallbackRunning && !rpmRunning) _engineEstimated = true;

        if (running)
        {
            if (!_engineRunning)
            {
                _engineRunning = true;
                if (_recording) AddEvent(Math.Max(0, s.T - _recStartT), "engine_start", new());
            }
            _engineOffSince = null;
            if (_recording) _engineSeconds += simDt;
            return;
        }
        if (!_engineRunning) return;
        _engineOffSince ??= s.T;
        if (s.T - _engineOffSince < 5.0) return;
        _engineRunning = false;
        _engineOffSince = null;
        if (_recording) AddEvent(Math.Max(0, s.T - _recStartT), "engine_stop", new());
    }

    private static bool AnyAbove(double[]? values, double threshold)
    {
        if (values == null) return false;
        foreach (var value in values)
        {
            if (value > threshold) return true;
        }
        return false;
    }

    /// <summary>
    /// 跑道窗口（P-05/P-06）：地面上 GS &gt;= 40kt（起飞滑跑 / 落地滑跑），或空中 AGL &lt; 100ft。
    /// SimLink 没有导航库，用这个近似代替「距机场 &lt; 5NM」；窗口内按 0.1s 保存，
    /// 否则接地区画不出连续滑跑线。
    /// </summary>
    private static bool InRunwayWindow(Sample s) =>
        s.OnGround ? s.GsKt >= 40.0 : s.AglFt < 100.0;

    private void SaveSample(Sample s)
    {
        var t = Math.Max(0, s.T - _recStartT);
        double interval = InRunwayWindow(s)
            ? 0.1
            : (s.AglFt < 3000 && !s.OnGround ? 0.5 : 1.0 / Math.Max(0.5, _hz));
        if (t < _nextSampleT) return;
        _nextSampleT = t + interval;
        var saved = new Sample
        {
            Seq = _seq++, T = t, Lat = s.Lat, Lon = s.Lon, AltFt = s.AltFt, AglFt = s.AglFt,
            GsKt = s.GsKt, IasKt = s.IasKt, VsFpm = s.VsFpm, HdgTrue = s.HdgTrue,
            PitchDeg = s.PitchDeg, BankDeg = s.BankDeg, OnGround = s.OnGround, FuelKg = s.FuelKg,
            TotalWeightKg = s.TotalWeightKg, FuelWeightKg = s.FuelWeightKg,
            EngRpm = s.EngRpm, EngN1 = s.EngN1, EngCombustion = s.EngCombustion,
            G = s.G, Gear = s.Gear, Flaps = s.Flaps, Paused = s.Paused, SimRate = s.SimRate,
        };
        _sampler.Update(saved);
        _samples.Add(saved);
        _queue?.WriteLine(JsonSerializer.Serialize(saved, _json));
    }

    public void Start() => _source.Start();

    public void Stop()
    {
        try { _source.Stop(); } catch { }
        lock (_lock)
        {
            if (_recording) StopLocked();
        }
    }

    public void Dispose()
    {
        Stop();
        _source.Dispose();
    }
}
