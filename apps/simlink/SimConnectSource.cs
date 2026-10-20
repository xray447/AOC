#if HAVE_SIMCONNECT
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.FlightSimulator.SimConnect;

namespace AocSimLink;

/// <summary>真实 SimConnect 数据源：帧级读取，由 Engine 按 1Hz/2Hz 保存。</summary>
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
        public double Fuel;
        public double GForce;
        public int Gear;
        public double Flaps;
        public double Pitch;
        public double Bank;
        public double Ias;
        public double EngineRpm;
        public int ParkingBrake;
        public double SimRate;
    }

    private SimConnect? _sc;
    private readonly Stopwatch _clock = new();
    private CancellationTokenSource? _cts;
    private volatile bool _connected;
    private string _version = "";
    private string _title = "";

    public string Name => "simconnect";
    public bool Connected => _connected;
    public string? SimVersion => _version;
    public string? AircraftTitle => _title;
    public event Action<Sample>? Frame;

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _clock.Start();
        _sc = new SimConnect("AOC SimLink", IntPtr.Zero, 0, null, 0);
        _sc.OnRecvOpen += (_, data) =>
        {
            _connected = true;
            _version = $"{data.dwSimConnectVersionMajor}.{data.dwSimConnectVersionMinor}";
        };
        _sc.OnRecvQuit += (_, _) => _connected = false;
        _sc.OnRecvException += (_, data) =>
            Console.Error.WriteLine($"simconnect_exception:{data.dwException}");
        _sc.OnRecvSimobjectData += (_, data) =>
        {
            var d = (StateData)data.dwData[0];
            var s = new Sample
            {
                T = _clock.Elapsed.TotalSeconds,
                Lat = d.Latitude, Lon = d.Longitude, AltFt = d.Altitude, AglFt = d.Agl,
                GsKt = d.GroundSpeed, VsFpm = d.VerticalSpeed, HdgTrue = d.Heading,
                OnGround = d.OnGround != 0, FuelKg = d.Fuel, G = d.GForce,
                PitchDeg = -d.Pitch, BankDeg = d.Bank, IasKt = d.Ias,
                Gear = d.Gear, Flaps = (int)Math.Round(d.Flaps),
                Paused = false, SimRate = d.SimRate <= 0 ? 1 : d.SimRate,
            };
            try { Frame?.Invoke(s); } catch { }
        };

        _sc.AddToDataDefinition(Definitions.State, "PLANE LATITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE LONGITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE ALTITUDE", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE ALT ABOVE GROUND", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "GROUND VELOCITY", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "VERTICAL SPEED", "feet per minute", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE HEADING DEGREES TRUE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "SIM ON GROUND", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "FUEL TOTAL QUANTITY", "kilograms", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "G FORCE", "gforce", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "GEAR HANDLE POSITION", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "FLAPS HANDLE INDEX", "number", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE PITCH DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "PLANE BANK DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "AIRSPEED INDICATED", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "GENERAL ENG RPM:1", "rpm", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "BRAKE PARKING POSITION", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.AddToDataDefinition(Definitions.State, "SIMULATION RATE", "number", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
        _sc.RegisterDataDefineStruct<StateData>(Definitions.State);
        _sc.RequestDataOnSimObject(Requests.State, Definitions.State,
            SimConnect.SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD.SIM_FRAME,
            SIMCONNECT_DATA_REQUEST_FLAG.CHANGED, 0, 0, 0);

        _ = Task.Run(() =>
        {
            while (!(_cts?.IsCancellationRequested ?? true))
            {
                try { _sc?.ReceiveMessage(); } catch { _connected = false; }
                Thread.Sleep(5);
            }
        });
    }

    public void Stop() => _cts?.Cancel();

    public void Dispose()
    {
        Stop();
        try { _sc?.Dispose(); } catch { }
        _cts?.Dispose();
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
    public event Action<Sample>? Frame { add { } remove { } }
    public void Start() =>
        Console.Error.WriteLine("本构建未启用 SimConnect（缺少 Microsoft.FlightSimulator.SimConnect.dll）。请用 --demo 或 --replay。");
    public void Stop() { }
    public void Dispose() { }
}
#endif
