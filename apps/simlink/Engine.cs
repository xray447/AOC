using System.Buffers;
using System.Text.Json;

namespace AocSimLink;

/// <summary>
/// 飞行状态机 + 本地队列。SimLink 只负责采集、自动起降、按 1Hz/2Hz（跑道窗口 0.1s）保存；
/// 落地指标、轨迹分段与日志由 aoc-core 处理。
/// </summary>
public sealed class Engine : IDisposable
{
    /// <summary>内存里最多保留的采样条数：磁盘上的 samples.jsonl 才是权威，core 每 1–2s 就会取走。</summary>
    private const int MaxSamples = 20000;
    /// <summary>预录帧按 1Hz 保留（10 min ≈ 600 条），起点要能覆盖发动机启动与起飞前滑行。</summary>
    private const double PreRollStepS = 1.0;
    private const double PreRollWindowS = 600.0;
    /// <summary>自动开录判定：发动机运转 / 地速 &gt; 3kt 持续这么久就开录。</summary>
    private const double AutoStartHoldS = 10.0;
    /// <summary>靠「停机刹车置位」收尾时的最短保持时间（收到 AutoStopHoldS 以内）。</summary>
    private const double ParkingBrakeHoldS = 30.0;
    /// <summary>瞬移判定（§33 / V-1）：速度 &gt; 900kt，或「dt &gt; 30s 且位移 &gt; 10 NM」。</summary>
    private const double TeleportSpeedKt = 900.0;
    private const double TeleportGapS = 30.0;
    private const double TeleportMinNm = 10.0;
    /// <summary>距出发机场超过这个距离、或不在空中，视为「还没进飞行 / 幽灵机」。</summary>
    private const double DepGateNm = 10.0;
    /// <summary>推出判定（§32 / V-5）：GS ≥ 5kt 连续 3s 后取最近 5 帧的中位数。</summary>
    private const double PushbackGsKt = 5.0;
    private const double PushbackHoldS = 3.0;
    private const int PushbackMedianFrames = 5;

    private readonly ISimSource _source;
    private readonly string _queueRoot;
    private readonly AdaptiveSampler _sampler = new();
    private readonly List<Sample> _samples = new();
    private readonly List<FlightEvent> _events = new();
    private readonly Queue<Sample> _preRoll = new();
    private readonly object _lock = new();
    private readonly JsonSerializerOptions _json = new() { WriteIndented = false };
    private readonly ArrayBufferWriter<byte> _jsonBuffer = new(4096);

    private FileStream? _queue;
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
    // 自动开录/收尾的计时器（§27/§30）：停稳与滑行必须分开计，不能用「接地后」当「停稳」
    private double? _engineOnSince;
    private double? _taxiSince;
    private double? _stoppedSince;
    private double? _parkingBrakeSince;
    private bool _hasTakeoff;
    // 推出快照（§32 方案 B）：开录不带 ZFW/油量，推出时定稿
    private readonly Queue<Sample> _recent = new();
    private double? _pushbackSince;
    private double? _pushbackZfw;
    private double? _pushbackFuel;
    private string? _pushbackAt;
    private string? _pushbackSource;
    private double _hz = 1.0;
    private double _lastErrorT = -100;
    private double _lastPreRollT = -100;

    // 计时（P-04）：模拟时间累计，按 sim_rate 折算；暂停不计
    private double _simClock;
    private double _takeoffSim;
    private double? _landingSim;
    private bool _landed;
    private double _engineSeconds;
    private bool _engineRunning;
    private double? _engineOffSince;
    private bool _engineEstimated;

    // 出发机场（§33 位置闸 / 预录截断）：SimLink 没有导航库，坐标由 core 下发
    private string? _depIcao;
    private double? _depLat;
    private double? _depLon;

    public bool AutoStart { get; set; } = true;
    /// <summary>自动开录起点：engine（默认，发动机运转 10s）/ taxi（滑行 10s）/ takeoff（旧行为：离地 5s）。</summary>
    public string AutoStartMode { get; set; } = "engine";
    /// <summary>自动收尾：连续静止（GS &lt; 5kt）或停机刹车保持这么久。</summary>
    public double AutoStopHoldS { get; set; } = 60.0;
    public string? LastFinishedId { get; private set; }

    public Engine(ISimSource source, string home)
    {
        _source = source;
        _queueRoot = Path.Combine(home, "simlink-queue");
        Directory.CreateDirectory(_queueRoot);
        _source.Frame += OnFrame;
        _source.ConnectionChanged += OnConnectionChanged;
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
                AircraftAtcModel = _source.AircraftAtcModel,
                AircraftAtcType = _source.AircraftAtcType,
                SimVersion = _source.SimVersion,
                Source = _source.Name,
                AutoStart = AutoStart,
                AutoStartMode = AutoStartMode,
                ReconnectAttempts = _source.ReconnectAttempts,
                LastConnectError = _source.LastConnectError,
                // §33 位置闸：把最新帧的位置/地速并进 /status，core 不再额外打一次 HTTP
                Lat = _prevFrame?.Lat, Lon = _prevFrame?.Lon,
                OnGround = _prevFrame?.OnGround, GsKt = _prevFrame?.GsKt,
                AltFt = _prevFrame?.AltFt, AglFt = _prevFrame?.AglFt,
                DepIcao = _depIcao,
                // §32 推出后定稿的 ZFW / 油量（未推出为 null）
                ZfwAtPushback = _pushbackZfw,
                FuelAtPushback = _pushbackFuel,
                PushbackUtc = _pushbackAt,
                PushbackSource = _pushbackSource,
            };
        }
    }

    /// <summary>下发出发机场（§33）：预录截断与幽灵帧判定用，查不到坐标时传 null。</summary>
    public void SetDeparture(string? icao, double? lat, double? lon)
    {
        lock (_lock)
        {
            _depIcao = string.IsNullOrWhiteSpace(icao) ? null : icao.Trim().ToUpperInvariant();
            _depLat = lat;
            _depLon = lon;
        }
    }

    /// <summary>最新一帧（未开始记录时也能取到），供实时状态与推出前 ZFW 校验。</summary>
    public Sample? LatestSample()
    {
        lock (_lock) return _prevFrame;
    }

    /// <summary>立刻重建 SimConnect（前端「重新连接」）；非 simconnect 源为空操作。</summary>
    public void ReconnectSource() => _source.Reconnect();

    /// <summary>已飞行时间（秒）：takeoff 起算，landing 冻结；未起飞为 0。</summary>
    private double FlightSecondsNow()
    {
        if (!_recording || !_hasTakeoff) return 0;
        var end = _landed ? (_landingSim ?? _simClock) : _simClock;
        return Math.Max(0, end - _takeoffSim);
    }

    /// <summary>按 `Seq` 二分找起点，避免每个轮询都全表扫描。</summary>
    private int IndexAfter(long since)
    {
        int lo = 0, hi = _samples.Count;
        while (lo < hi)
        {
            var mid = lo + (hi - lo) / 2;
            if (_samples[mid].Seq <= since) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    public (List<Sample> samples, long lastSeq) Samples(long since, int limit)
    {
        lock (_lock)
        {
            var start = IndexAfter(since);
            var count = Math.Min(Math.Max(1, limit), _samples.Count - start);
            var list = count > 0 ? _samples.GetRange(start, count) : new List<Sample>();
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
            _engineOffSince = null;
            // 开录后重新计时，避免同一个「已满足条件」的计时器反复触发
            _engineOnSince = null;
            _taxiSince = null;
            _stoppedSince = null;
            _parkingBrakeSince = null;
            // §32 推出快照：每段录制重新取
            _pushbackSince = null;
            _pushbackZfw = null;
            _pushbackFuel = null;
            _pushbackAt = null;
            _pushbackSource = null;
            _recent.Clear();
            // 地面晚接入（首帧已经在动）：只能取开录首帧并标 source=start；
            // 空中接入（首帧不在空中）留 null，界面显示「—」，不参与结算
            var foot = _prevFrame;
            if (foot is { OnGround: true } && foot.GsKt >= PushbackGsKt
                && foot.TotalWeightKg - foot.FuelWeightKg > 0)
            {
                _pushbackZfw = foot.TotalWeightKg - foot.FuelWeightKg;
                _pushbackFuel = foot.FuelWeightKg;
                _pushbackAt = _startedAt;
                _pushbackSource = "start";
            }
            if (_landed)
            {
                // 上一次飞行已落地：不要把旧航班的起飞时刻算进新的记录
                _landed = false;
                _hasTakeoff = false;
                _takeoffSim = 0;
                _landingSim = null;
            }
            // 自动开录把预录窗口里的帧全部补进来（含地面滑行帧）：block_off 落在
            // 发动机启动/开始滑行的时刻，TAXI 段与发动机时间才能回溯（旧版只补离地后的帧）。
            var pre = new List<Sample>();
            if (!manual)
            {
                // §33 第 2 道闸：预录里若含幽灵帧/瞬移（KBFI → 真实机场），从最后一次跳变起截断，
                // 否则 block_off 会落在幽灵机位置、判出假起降
                var frames = TrimPreRoll(_preRoll.ToArray());
                if (frames.Count > 0)
                {
                    _recStartT = frames[0].T;
                    pre.AddRange(frames);
                }
            }
            // 空中自动开录（takeoff 模式）时已经起飞：状态机不会再产生 takeoff 事件
            _hasTakeoff = !manual && _airborneSince != null;
            if (_hasTakeoff) _takeoffSim = _simClock;
            _phase = _hasTakeoff ? "CLIMB" : "PREFLIGHT";
            var dir = Path.Combine(_queueRoot, _recordingId);
            Directory.CreateDirectory(dir);
            _queue = new FileStream(Path.Combine(dir, "samples.jsonl"), FileMode.Create,
                FileAccess.Write, FileShare.Read);
            AddEvent(0, "recording_started", new() { ["manual"] = manual, ["pre_roll"] = pre.Count });
            // 发动机启动/开始滑行发生在开录之前：补进事件流（时刻相对预录首帧）
            if (_engineRunning && _engineOnSince != null)
                AddEvent(Math.Max(0, _engineOnSince.Value - _recStartT), "engine_start", new());
            if (_taxiSince != null)
                AddEvent(Math.Max(0, _taxiSince.Value - _recStartT), "taxi_start", new());
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
        _engineOnSince = null;
        _taxiSince = null;
        _stoppedSince = null;
        _parkingBrakeSince = null;
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

    /// <summary>连接/断线也要进事件流：飞行中模拟器退出再进，日志里能看到缺口与重连。</summary>
    private void OnConnectionChanged(bool connected)
    {
        lock (_lock)
        {
            if (_recording)
            {
                var t = Math.Max(0, (_prevFrame?.T ?? _recStartT) - _recStartT);
                AddEvent(t, connected ? "sim_connected" : "sim_disconnected", new());
            }
            // §33 / V-1：重连/切场景后状态机必须重置。旧代码保留了 _hasTakeoff/_landed，
            // 且 StopLocked 清掉的 _engineOnSince 再没被点亮 → 进了游戏、发动机在转也不自动开录。
            _hasTakeoff = false;
            _landed = false;
            _airborneSince = null;
            _takeoffSim = _simClock;
            _landingSim = null;
            _taxiSince = null;
            _stoppedSince = null;
            _parkingBrakeSince = null;
            _engineOffSince = null;
            _phase = "PREFLIGHT";
            // 重连时发动机若仍在转，重新点亮自动开录计时（否则永远等不到新的启动沿）
            _engineOnSince = connected && _engineRunning ? (_prevFrame?.T ?? 0) : null;
        }
    }

    /// <summary>
    /// 预录截断（§33）：回扫一遍，记录最后一次「瞬移/幽灵帧」的位置，只保留它之后的帧。
    /// 没有跳变时用满窗口（正常流程零变化）。
    /// </summary>
    private List<Sample> TrimPreRoll(Sample[] frames)
    {
        var list = frames.ToList();
        if (list.Count < 2) return list;
        var cut = 0;
        for (var i = 1; i < list.Count; i++)
        {
            if (!IsJump(list[i - 1], list[i])) continue;
            cut = i;
        }
        if (cut > 0) list.RemoveRange(0, cut);
        return list;
    }

    /// <summary>
    /// 瞬移判定（只用运动学 + 幽灵坐标）：推理速度 &gt; 900kt，或「dt &gt; 30s 且位移 &gt; 10 NM」。
    /// 录制中只用这一条 —— 把「远离出发机场的空中帧」也算瞬移会让每一次正常离场都被重置。
    /// </summary>
    private static bool IsTeleport(Sample a, Sample b)
    {
        var dt = b.T - a.T;
        if (dt <= 0) return false;
        var dist = DistanceNm(a.Lat, a.Lon, b.Lat, b.Lon);
        // 位移门槛必须有：单帧位移不到 10 NM 不可能是瞬移（避免把压缩时间轴当瞬移）
        if (dist <= TeleportMinNm) return false;
        if (dist / (dt / 3600.0) > TeleportSpeedKt) return true;
        if (dt > TeleportGapS) return true;
        // 菜单/加载期的幽灵坐标 (0, 90)：陆空都算（实测 on_ground=false、AGL 216ft）
        return !b.OnGround && Math.Abs(b.Lat) < 1e-3 && Math.Abs(b.Lon - 90.0) < 1e-3;
    }

    /// <summary>预录截断用：瞬移之外再叠「低空 + 远离出发机场」= 幽灵机帧（含 KBFI 那架）。</summary>
    private bool IsJump(Sample a, Sample b)
    {
        if (IsTeleport(a, b)) return true;
        if (b.OnGround || b.AglFt >= 2000) return false;
        return DistanceToDep(b) is > DepGateNm;
    }

    private double? DistanceToDep(Sample s)
    {
        if (_depLat is null || _depLon is null) return null;
        return DistanceNm(_depLat.Value, _depLon.Value, s.Lat, s.Lon);
    }

    private static double DistanceNm(double lat1, double lon1, double lat2, double lon2)
    {
        const double rad = Math.PI / 180.0;
        var dLat = (lat2 - lat1) * rad;
        var dLon = (lon2 - lon1) * rad;
        var h = Math.Sin(dLat / 2) * Math.Sin(dLat / 2)
                + Math.Cos(lat1 * rad) * Math.Cos(lat2 * rad) * Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
        return 2 * 3440.065 * Math.Asin(Math.Min(1.0, Math.Sqrt(h)));
    }

    /// <summary>
    /// 录制中瞬移 = 重置（§33 第 3 道闸）：核心那边丢弃跳变前轨迹，这里只把状态机清干净，
    /// 避免假起降事件与「已起飞/已落地」被带进新位置。
    /// </summary>
    private void ResetAfterTeleport(Sample s, bool recording)
    {
        _hasTakeoff = false;
        _landed = false;
        _airborneSince = null;
        _takeoffSim = _simClock;
        _landingSim = null;
        _taxiSince = null;
        _stoppedSince = null;
        _parkingBrakeSince = null;
        _phase = "PREFLIGHT";
        // 换了位置：推出快照要在新机位重新取
        _pushbackSince = null;
        _pushbackZfw = null;
        _pushbackFuel = null;
        _pushbackAt = null;
        _pushbackSource = null;
        _recent.Clear();
        if (recording)
        {
            AddEvent(Math.Max(0, s.T - _recStartT), "teleport", new()
            {
                ["lat"] = s.Lat, ["lon"] = s.Lon, ["on_ground"] = s.OnGround,
            });
        }
    }

    /// <summary>
    /// 推出判定（§32 方案 B / V-5）：`GS ≥ 5kt` 连续 3s 后取最近 5 帧的 ZFW 与油量中位数，
    /// 相邻帧跳变 &gt; 10% 就继续等稳定；只在「地面且未起飞」时计时，空中接入不参与。
    /// </summary>
    private void TrackPushback(Sample s)
    {
        if (_pushbackZfw != null || _hasTakeoff || !s.OnGround)
        {
            if (!s.OnGround || _hasTakeoff) _pushbackSince = null;
            return;
        }
        if (s.GsKt < PushbackGsKt)
        {
            _pushbackSince = null;
            return;
        }
        _pushbackSince ??= s.T;
        // 候选帧起表，等 t - since ≥ 3s 再取值（V-5：不能用「3s 窗口内全满足」，实测帧间隔 0.98–2.0s）
        if (s.T - _pushbackSince < PushbackHoldS) return;
        var frames = _recent.Where(f => f.OnGround).ToList();
        if (frames.Count == 0) return;
        var zfws = frames.Select(f => f.TotalWeightKg - f.FuelWeightKg).ToList();
        for (var i = 1; i < zfws.Count; i++)
        {
            if (zfws[i - 1] > 0 && Math.Abs(zfws[i] - zfws[i - 1]) / zfws[i - 1] > 0.10)
            {
                _pushbackSince = s.T;   // EFB 还在装货/加油：重新起表
                return;
            }
        }
        var zfw = Median(zfws);
        if (zfw <= 0) return;
        _pushbackZfw = zfw;
        _pushbackFuel = Median(frames.Select(f => f.FuelWeightKg).ToList());
        _pushbackAt = TimeUtil.Iso(DateTime.UtcNow);
        _pushbackSource = "pushback";
        if (_recording)
        {
            AddEvent(Math.Max(0, s.T - _recStartT), "pushback", new()
            {
                ["zfw_kg"] = Math.Round(zfw, 1),
                ["fuel_kg"] = Math.Round(_pushbackFuel ?? 0, 1),
                ["gs_kt"] = s.GsKt,
            });
        }
    }

    private static double Median(List<double> values)
    {
        if (values.Count == 0) return 0;
        var sorted = values.OrderBy(v => v).ToList();
        return sorted.Count % 2 == 1
            ? sorted[sorted.Count / 2]
            : (sorted[sorted.Count / 2 - 1] + sorted[sorted.Count / 2]) / 2.0;
    }

    private void OnFrame(Sample s)
    {
        lock (_lock)
        {
            try
            {
                // 预录只留 5Hz：逐帧（30–60Hz）存 20s 会白占上千个对象
                if (s.T - _lastPreRollT >= PreRollStepS)
                {
                    _lastPreRollT = s.T;
                    _preRoll.Enqueue(s);
                }
                while (_preRoll.Count > 0 && s.T - _preRoll.Peek().T > PreRollWindowS) _preRoll.Dequeue();
                var dt = _prevFrame == null ? 0 : s.T - _prevFrame.T;
                var simDt = dt > 0 && dt <= 3.0
                    ? dt * (_source.ClockIsSimTime ? 1.0 : (s.SimRate <= 0 ? 1.0 : s.SimRate))
                    : 0;
                if (!s.Paused)
                {
                    _simClock += simDt;
                    UpdateEngine(s, simDt);
                }
                // §33 第 3 道闸：录制中瞬移 = 重置状态机（假起降不许进事件流）
                if (_prevFrame != null && IsTeleport(_prevFrame, s))
                    ResetAfterTeleport(s, _recording);
                UpdateStateMachine(s);
                // §32：推出时定稿 ZFW / 油量（最近的 5 帧留着算中位数）
                _recent.Enqueue(s);
                while (_recent.Count > PushbackMedianFrames) _recent.Dequeue();
                TrackPushback(s);
                if (!_recording && AutoStart && AutoStartDue(s)) StartRecording(manual: false);
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

    /// <summary>
    /// 自动开录判定（§27）：默认从「发动机启动」开始，而不是离地 5s 之后；
    /// 这样起飞前滑行、等待与发动机时间都能进日志。takeoff 保留旧行为。
    /// </summary>
    private bool AutoStartDue(Sample s) => (AutoStartMode ?? "engine").ToLowerInvariant() switch
    {
        "takeoff" => _airborneSince != null && s.T - _airborneSince >= 5.0,
        "taxi" => _taxiSince != null && s.T - _taxiSince >= AutoStartHoldS,
        _ => _engineOnSince != null && s.T - _engineOnSince >= AutoStartHoldS,
    };

    private void UpdateStateMachine(Sample s)
    {
        // 滑行计时（taxi 模式）与「停稳」计时（收尾判定）：都必须连续满足，不能被单帧打断
        if (s.OnGround && s.GsKt > 3.0) _taxiSince ??= s.T;
        else if (!s.OnGround || s.GsKt <= 1.0) _taxiSince = null;
        if (s.GsKt < 5.0) _stoppedSince ??= s.T;
        else _stoppedSince = null;
        if (s.ParkingBrake) _parkingBrakeSince ??= s.T;
        else _parkingBrakeSince = null;

        bool fresh = _prevFrame != null && s.T - _prevFrame.T <= 3.0;
        if (!s.OnGround)
        {
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
            if (_recording && _hasTakeoff) MaybeAutoStop(s);
        }
    }

    /// <summary>
    /// 自动收尾（§30）：旧判据是「接地满 30s 后任意一帧 GS&lt;5 就停」，滑行中减速、
    /// 过跑道口等待都会误停。现在要求「连续静止」达到 hold，或停机刹车保持，
    /// 或「停机刹车 + 发动机全部关车」——真到机位才结束。
    /// </summary>
    private void MaybeAutoStop(Sample s)
    {
        var stoppedLongEnough = _stoppedSince != null && s.T - _stoppedSince >= AutoStopHoldS;
        var parkedLongEnough = _parkingBrakeSince != null
            && s.T - _parkingBrakeSince >= Math.Min(AutoStopHoldS, ParkingBrakeHoldS);
        var parkedWithEnginesOff = s.ParkingBrake && !_engineRunning;
        if (stoppedLongEnough || parkedLongEnough || parkedWithEnginesOff) StopLocked();
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
                // 新的发动机启动：自动开录从这一刻起算（§27），发动机计时也从零开始
                _engineOnSince = s.T;
                _engineSeconds = 0;
                _engineEstimated = fallbackRunning && !rpmRunning;
                if (_recording) AddEvent(Math.Max(0, s.T - _recStartT), "engine_start", new());
            }
            _engineOffSince = null;
            // 未开始记录也要累计：开录时可以从预录回溯，不必标 estimated
            _engineSeconds += simDt;
            return;
        }
        if (!_engineRunning) return;
        _engineOffSince ??= s.T;
        if (s.T - _engineOffSince < 5.0) return;
        _engineRunning = false;
        _engineOffSince = null;
        _engineOnSince = null;
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
    /// 否则接地区画不出连续滑跑线。SimConnect 源也用它决定回调频率（SECOND / SIM_FRAME）。
    /// </summary>
    public static bool InRunwayWindow(Sample s) =>
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
            ParkingBrake = s.ParkingBrake,
            G = s.G, Gear = s.Gear, Flaps = s.Flaps, Paused = s.Paused, SimRate = s.SimRate,
        };
        _sampler.Update(saved);
        _samples.Add(saved);
        if (_samples.Count > MaxSamples) _samples.RemoveRange(0, _samples.Count - MaxSamples);
        WriteQueue(saved);
    }

    /// <summary>逐点写盘：直接序列化进复用缓冲，避免每点新建一个字符串。</summary>
    private void WriteQueue(Sample saved)
    {
        var queue = _queue;
        if (queue == null) return;
        try
        {
            _jsonBuffer.ResetWrittenCount();
            using (var writer = new Utf8JsonWriter(_jsonBuffer))
            {
                JsonSerializer.Serialize(writer, saved, _json);
            }
            queue.Write(_jsonBuffer.WrittenSpan);
            queue.WriteByte((byte)'\n');
            queue.Flush();
        }
        catch (Exception exc)
        {
            if (saved.T - _lastErrorT > 5)
            {
                _lastErrorT = saved.T;
                Console.Error.WriteLine($"queue write failed: {exc.Message}");
            }
        }
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
