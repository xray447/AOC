#if HAVE_SIMCONNECT
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.FlightSimulator.SimConnect;

namespace AocSimLink;

/// <summary>
/// 真实 SimConnect 数据源：后台线程负责「连接 → 收消息 → 断开 → 退避重连」。
///
/// 连接与 <c>ReceiveMessage</c> 都在同一个线程上（SimConnect 的消息窗口属于创建线程），
/// 因此 MSFS 没开、中途退出、手动重连都只需要重建这个对象，不会卡住 HTTP 服务。
/// 回调频率：平时 <c>SECOND</c>（1 Hz），跑道窗口临时切到 <c>SIM_FRAME</c>（D-26 内存优化）；
/// Engine 自己按 1Hz / 跑道 10Hz 抽稀保存。
/// </summary>
public sealed class SimConnectSource : ISimSource
{
    private enum Definitions { State }
    private enum Requests { State }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct StateData
    {
        public double Latitude;
        public double Longitude;
        public double Altitude;
        public double Agl;
        public double GroundSpeed;
        public double VerticalSpeed;
        public double Heading;
        public int OnGround;
        public double FuelWeightLb;
        public double TotalWeightLb;
        public double GForce;
        public int Gear;
        public double Flaps;
        public double Pitch;
        public double Bank;
        public double Ias;
        public double EngRpm1;
        public double EngRpm2;
        public double EngRpm3;
        public double EngRpm4;
        public double EngN1_1;
        public double EngN1_2;
        public double EngN1_3;
        public double EngN1_4;
        public int EngComb1;
        public int EngComb2;
        public int EngComb3;
        public int EngComb4;
        public int ParkingBrake;
        public double SimRate;
    }

    private const double LbToKg = 0.45359237;
    /// <summary>连接失败/断开后的重连退避。</summary>
    private const int ReconnectDelayMs = 5000;
    /// <summary>连上之后收消息的空转间隔（5 ms ≈ 200 次/秒，足够消化 SIM_FRAME 回调）。</summary>
    private const int PumpIdleMs = 5;
    /// <summary>建对象后等 OnRecvOpen 的上限；超时按失败处理，避免卡在「半连接」。</summary>
    private const double ConnectTimeoutS = 10.0;

    private readonly object _gate = new();
    private readonly Stopwatch _clock = new();
    private CancellationTokenSource? _cts;
    private Thread? _worker;
    private SimConnect? _sc;
    private volatile bool _connected;
    private volatile bool _runwayWindow;
    private volatile bool _reconnectNow;
    private volatile string? _pendingDrop;
    private volatile string? _lastError;
    private int _attempts;
    private double _createdAtT;
    private string _version = "";
    private string _title = "";

    public string Name => "simconnect";
    public bool Connected => _connected;
    public string? SimVersion => _version;
    public string? AircraftTitle => _title;
    public int ReconnectAttempts => Volatile.Read(ref _attempts);
    public string? LastConnectError => _lastError;
    public event Action<Sample>? Frame;
    public event Action<bool>? ConnectionChanged;

    public void Start()
    {
        lock (_gate)
        {
            if (_worker != null) return;
            _cts = new CancellationTokenSource();
            _clock.Start();
            var token = _cts.Token;
            _worker = new Thread(() => Run(token)) { IsBackground = true, Name = "aoc-simconnect" };
            _worker.Start();
        }
    }

    /// <summary>立刻重建连接（前端「重新连接」按钮）；后台循环本来也会按 5s 退避重试。</summary>
    public void Reconnect() => _reconnectNow = true;

    public void Stop()
    {
        _cts?.Cancel();
        Thread? worker;
        lock (_gate) worker = _worker;
        if (worker != null && worker.IsAlive && worker != Thread.CurrentThread)
        {
            try { worker.Join(1500); } catch (Exception) { /* 退出阶段不阻塞 */ }
        }
    }

    public void Dispose()
    {
        Stop();
        try { _sc?.Dispose(); } catch (Exception) { /* 已断开 */ }
        _sc = null;
        _cts?.Dispose();
        _cts = null;
    }

    // ------------------------------------------------------------------ 后台循环
    private void Run(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            var sc = _sc;
            if (sc == null)
            {
                if (!TryConnect())
                {
                    SleepBeforeRetry(token);
                }
                continue;
            }
            if (_reconnectNow)
            {
                _reconnectNow = false;
                DropConnection("手动重新连接");
                continue;
            }
            if (!_connected && _createdAtT > 0 && _clock.Elapsed.TotalSeconds - _createdAtT > ConnectTimeoutS)
            {
                DropConnection("等待模拟器握手超时（OnRecvOpen）");
                SleepBeforeRetry(token);
                continue;
            }
            try
            {
                sc.ReceiveMessage();
            }
            catch (Exception exc)
            {
                DropConnection($"ReceiveMessage: {exc.GetType().Name}: {exc.Message}");
                continue;
            }
            var drop = _pendingDrop;
            if (drop != null)
            {
                _pendingDrop = null;
                DropConnection(drop);
                continue;
            }
            Thread.Sleep(PumpIdleMs);
        }
        // 正常退出不算连接错误：不写 last_connect_error
        DropConnection(string.Empty);
    }

    private bool TryConnect()
    {
        try
        {
            var sc = new SimConnect("AOC SimLink", IntPtr.Zero, 0, null, 0);
            sc.OnRecvOpen += (_, data) =>
            {
                _version = $"{data.dwSimConnectVersionMajor}.{data.dwSimConnectVersionMinor}";
                Interlocked.Exchange(ref _attempts, 0);
                SetError(null);
                SetConnected(true);
                Console.Error.WriteLine("simconnect connected");
            };
            sc.OnRecvQuit += (_, _) =>
            {
                // 在 ReceiveMessage 回调里不能直接 Dispose 自己，交给主循环收尾
                SetConnected(false);
                _pendingDrop = "模拟器已退出（OnRecvQuit）";
            };
            sc.OnRecvException += (_, data) =>
                Console.Error.WriteLine($"simconnect_exception:{data.dwException}");
            sc.OnRecvSimobjectData += (_, data) => OnSimObjectData(data.dwData);

            AddDefinitions(sc);
            _runwayWindow = false;
            Request(sc, runway: false);
            _createdAtT = _clock.Elapsed.TotalSeconds;
            _sc = sc;
            Console.Error.WriteLine("simconnect connecting…");
            return true;
        }
        catch (Exception exc)
        {
            Volatile.Write(ref _attempts, ReconnectAttempts + 1);
            SetError($"{exc.GetType().Name}: {exc.Message}");
            Console.Error.WriteLine($"simconnect connect failed ({ReconnectAttempts}): {_lastError}");
            DisposeConnection();
            return false;
        }
    }

    private void SleepBeforeRetry(CancellationToken token)
    {
        for (var waited = 0; waited < ReconnectDelayMs; waited += 250)
        {
            if (token.IsCancellationRequested || _reconnectNow) return;
            Thread.Sleep(250);
        }
    }

    private void DropConnection(string reason)
    {
        if (_connected) Console.Error.WriteLine($"simconnect disconnected: {reason}");
        SetConnected(false);
        DisposeConnection();
        if (!string.IsNullOrWhiteSpace(reason)) SetError(reason);
    }

    private void DisposeConnection()
    {
        var sc = _sc;
        _sc = null;
        if (sc == null) return;
        try { sc.Dispose(); } catch (Exception) { /* 已断开 */ }
    }

    private void SetConnected(bool value)
    {
        if (_connected == value) return;
        _connected = value;
        try { ConnectionChanged?.Invoke(value); } catch (Exception) { /* 订阅方异常不影响采样 */ }
    }

    private void SetError(string? error) => _lastError = error;

    private void AddDefinitions(SimConnect sc)
    {
        sc.AddToDataDefinition(Definitions.State, "PLANE LATITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE LONGITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE ALTITUDE", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE ALT ABOVE GROUND", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GROUND VELOCITY", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "VERTICAL SPEED", "feet per minute", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE HEADING DEGREES TRUE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "SIM ON GROUND", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        // FUEL TOTAL QUANTITY 是体积（加仑），不能当重量用；燃油重量只认 FUEL TOTAL QUANTITY WEIGHT。
        sc.AddToDataDefinition(Definitions.State, "FUEL TOTAL QUANTITY WEIGHT", "pounds", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "TOTAL WEIGHT", "pounds", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "G FORCE", "gforce", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GEAR HANDLE POSITION", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "FLAPS HANDLE INDEX", "number", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE PITCH DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "PLANE BANK DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "AIRSPEED INDICATED", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GENERAL ENG RPM:1", "rpm", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GENERAL ENG RPM:2", "rpm", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GENERAL ENG RPM:3", "rpm", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "GENERAL ENG RPM:4", "rpm", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "TURB ENG N1:1", "percent", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "TURB ENG N1:2", "percent", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "TURB ENG N1:3", "percent", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "TURB ENG N1:4", "percent", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "ENG COMBUSTION:1", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "ENG COMBUSTION:2", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "ENG COMBUSTION:3", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "ENG COMBUSTION:4", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "BRAKE PARKING POSITION", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.AddToDataDefinition(Definitions.State, "SIMULATION RATE", "number", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        sc.RegisterDataDefineStruct<StateData>(Definitions.State);
    }

    /// <summary>跑道窗口用逐帧（0.1s 采样要靠它），其余每秒一次即可。</summary>
    private static SIMCONNECT_PERIOD Period(bool runway) =>
        runway ? SIMCONNECT_PERIOD.SIM_FRAME : SIMCONNECT_PERIOD.SECOND;

    private void Request(SimConnect sc, bool runway) =>
        sc.RequestDataOnSimObject(Requests.State, Definitions.State,
            SimConnect.SIMCONNECT_OBJECT_ID_USER, Period(runway),
            SIMCONNECT_DATA_REQUEST_FLAG.CHANGED, 0, 0, 0);

    private void OnSimObjectData(object[] dwData)
    {
        var d = (StateData)dwData[0];
        var fuelKg = d.FuelWeightLb * LbToKg;
        var s = new Sample
        {
            T = _clock.Elapsed.TotalSeconds,
            Lat = d.Latitude, Lon = d.Longitude, AltFt = d.Altitude, AglFt = d.Agl,
            GsKt = d.GroundSpeed, VsFpm = d.VerticalSpeed, HdgTrue = d.Heading,
            OnGround = d.OnGround != 0, FuelKg = fuelKg, G = d.GForce,
            // MSFS 没有 ZERO FUEL WEIGHT：ZFW = TOTAL WEIGHT − FUEL TOTAL QUANTITY WEIGHT
            TotalWeightKg = d.TotalWeightLb * LbToKg,
            FuelWeightKg = fuelKg,
            EngRpm = new[] { d.EngRpm1, d.EngRpm2, d.EngRpm3, d.EngRpm4 },
            EngN1 = new[] { d.EngN1_1, d.EngN1_2, d.EngN1_3, d.EngN1_4 },
            EngCombustion = new double[] { d.EngComb1, d.EngComb2, d.EngComb3, d.EngComb4 },
            PitchDeg = -d.Pitch, BankDeg = d.Bank, IasKt = d.Ias,
            ParkingBrake = d.ParkingBrake != 0,
            Gear = d.Gear, Flaps = (int)Math.Round(d.Flaps),
            Paused = false, SimRate = d.SimRate <= 0 ? 1 : d.SimRate,
        };
        try { Frame?.Invoke(s); } catch (Exception) { /* 采样回调异常不能拖垮收消息线程 */ }

        // 跑道窗口临时期整到逐帧，窗口外回落到 1 Hz（可显著降低 GC 与峰值内存）
        var window = Engine.InRunwayWindow(s);
        if (window == _runwayWindow) return;
        _runwayWindow = window;
        var sc = _sc;
        if (sc == null) return;
        try
        {
            Request(sc, window);
        }
        catch (Exception exc)
        {
            _pendingDrop = $"切换采样周期失败: {exc.GetType().Name}: {exc.Message}";
        }
    }
}
#else
namespace AocSimLink;

/// <summary>未编译 SimConnect 后端：明确提示，不假装已连接。</summary>
public sealed class SimConnectSource : ISimSource
{
    public string Name => "simconnect";
    public bool Connected => false;
    public string? SimVersion => null;
    public string? AircraftTitle => null;
    public int ReconnectAttempts => 0;
    public string? LastConnectError => null;
    public event Action<Sample>? Frame { add { } remove { } }
    public event Action<bool>? ConnectionChanged { add { } remove { } }
    public void Start() =>
        Console.Error.WriteLine("本构建未启用 SimConnect（缺少 Microsoft.FlightSimulator.SimConnect.dll）。请用 --demo 或 --replay。");
    public void Reconnect() { }
    public void Stop() { }
    public void Dispose() { }
}
#endif
