#if HAVE_SIMCONNECT
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.FlightSimulator.SimConnect;

namespace SimLinkProbe;

/// <summary>
/// 真实 SimConnect 数据源（V-01/V-02）。只在检测到 MSFS SDK 托管 DLL 时编译。
/// 以 SIM_FRAME 周期读取，帧级数据用于抓着陆瞬间，落盘按 --hz 抽稀。
/// </summary>
internal static class SimConnectSource
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
        public double Aoa;
        public double Ias;
    }

    public static int Run(string outDir, int seconds, int hz, List<Runway> runways, string? airport)
    {
        var samples = new List<TrackSample>();
        var touchdowns = new List<Touchdown>();
        var events = new List<FlightEvent>();
        var warnings = new List<string>();
        int frameCount = 0;
        bool opened = false;
        string simVersion = "";
        var sw = Stopwatch.StartNew();
        double nextWrite = 0;
        TrackSample? prev = null;

        SimConnect? sc = null;
        try
        {
            // hWnd=0 依赖 ReceiveMessage 轮询；若某版本要求窗口句柄，改用隐藏 NativeWindow。
            sc = new SimConnect("AOC SimLink Probe", IntPtr.Zero, 0, null, 0);

            sc.OnRecvOpen += (_, data) =>
            {
                opened = true;
                simVersion = $"{data.dwSimConnectVersionMajor}.{data.dwSimConnectVersionMinor}";
            };
            sc.OnRecvQuit += (_, _) => { warnings.Add("sim_quit"); };
            sc.OnRecvException += (_, data) =>
            {
                warnings.Add($"simconnect_exception:{data.dwException}");
            };
            sc.OnRecvSimobjectData += (_, data) =>
            {
                var d = (StateData)data.dwData[0];
                frameCount++;
                var s = new TrackSample
                {
                    T = sw.Elapsed.TotalSeconds,
                    Lat = d.Latitude, Lon = d.Longitude, AltFt = d.Altitude, AglFt = d.Agl,
                    GsKt = d.GroundSpeed, VsFpm = d.VerticalSpeed, HdgDeg = d.Heading,
                    OnGround = d.OnGround != 0, FuelKg = d.Fuel, GForce = d.GForce,
                    PitchDeg = d.Pitch, AoaDeg = d.Aoa, IasKt = d.Ias,
                    Gear = d.Gear, Flaps = (int)Math.Round(d.Flaps),
                };

                if (s.T >= nextWrite)
                {
                    samples.Add(s);
                    nextWrite += 1.0 / Math.Max(1, hz);
                }
                if (prev != null && !prev.OnGround && s.OnGround)
                {
                    var td = new Touchdown
                    {
                        T = Math.Round(s.T, 2), Lat = s.Lat, Lon = s.Lon,
                        VsFpm = Math.Round(s.VsFpm, 1), GForce = Math.Round(s.GForce, 2),
                        AoaDeg = Math.Round(s.AoaDeg, 1), IasKt = Math.Round(s.IasKt, 1),
                        HdgDeg = Math.Round(s.HdgDeg, 1),
                    };
                    var (rw, dist) = Runways.Nearest(s.Lat, s.Lon, runways);
                    if (rw != null && dist <= Analyzer.RunwayMatchRadiusNm
                        && (airport == null || rw.Airport == airport))
                    {
                        td.Airport = rw.Airport;
                        td.RunwayName = rw.Name;
                        td.RunwayDistNm = Math.Round(dist, 3);
                        td.RunwayHdgDiffDeg = Math.Round(Runways.HeadingDiff(s.HdgDeg, rw.Heading), 1);
                    }
                    touchdowns.Add(td);
                    events.Add(new FlightEvent { T = s.T, Type = "touchdown", Detail = td.RunwayName ?? "runway_unknown" });
                }
                else if (prev != null && prev.OnGround && !s.OnGround)
                {
                    events.Add(new FlightEvent { T = s.T, Type = "liftoff", Detail = "" });
                }
                if (prev != null && prev.Gear != s.Gear)
                    events.Add(new FlightEvent { T = s.T, Type = "gear", Detail = s.Gear == 1 ? "down" : "up" });
                if (prev != null && prev.Flaps != s.Flaps)
                    events.Add(new FlightEvent { T = s.T, Type = "flaps", Detail = s.Flaps.ToString() });
                prev = s;
            };

            sc.AddToDataDefinition(Definitions.State, "PLANE LATITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "PLANE LONGITUDE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "PLANE ALTITUDE", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "PLANE ALT ABOVE GROUND", "feet", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "GROUND VELOCITY", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "VERTICAL SPEED", "feet per minute", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "PLANE HEADING DEGREES TRUE", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "SIM ON GROUND", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "FUEL TOTAL QUANTITY", "kilograms", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "G FORCE", "gforce", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "GEAR HANDLE POSITION", "bool", SIMCONNECT_DATATYPE.INT32, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "FLAPS HANDLE INDEX", "number", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "PLANE PITCH DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "INCIDENCE ALPHA", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.AddToDataDefinition(Definitions.State, "AIRSPEED INDICATED", "knots", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.RegisterDataDefineStruct<StateData>(Definitions.State);
            sc.RequestDataOnSimObject(Requests.State, Definitions.State,
                SimConnect.SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD.SIM_FRAME,
                SIMCONNECT_DATA_REQUEST_FLAG.CHANGED, 0, 0, 0);

            while (sw.Elapsed.TotalSeconds < seconds)
            {
                sc.ReceiveMessage();
                Thread.Sleep(5);
            }
        }
        catch (Exception exc)
        {
            warnings.Add($"fatal:{exc.GetType().Name}:{exc.Message}");
            Console.Error.WriteLine(exc.Message);
        }
        finally
        {
            try { sc?.Dispose(); } catch { /* 关闭阶段的异常不影响已采集数据 */ }
        }

        var session = new SessionReport
        {
            Source = "simconnect",
            Samples = samples.Count,
            DurationS = Math.Round(samples.Count > 0 ? samples[^1].T : 0, 1),
            Touchdowns = touchdowns.Count,
            Events = events.Count,
            FrameCount = frameCount,
            Fps = sw.Elapsed.TotalSeconds > 0 ? Math.Round(frameCount / sw.Elapsed.TotalSeconds, 1) : null,
            SimConnectVersion = simVersion,
            Warnings = warnings,
        };
        OutputWriter.Save(outDir, samples, touchdowns, events, session);
        Console.WriteLine($"simconnect opened={opened} frames={frameCount} samples={samples.Count} " +
                          $"fps={session.Fps} touchdowns={touchdowns.Count} out={outDir}");
        if (!opened) return 4;
        return frameCount > 0 ? 0 : 5;
    }
}
#else
namespace SimLinkProbe;

/// <summary>未编译 SimConnect 时的占位：明确告知需要 SDK，避免误以为已联调。</summary>
internal static class SimConnectSource
{
    public static int Run(string outDir, int seconds, int hz, List<Runway> runways, string? airport)
    {
        Console.Error.WriteLine(
            "本二进制未编译 SimConnect 后端：未找到 Microsoft.FlightSimulator.SimConnect.dll。" +
            "请设置 SimConnectDll 指向 MSFS SDK 后重建，并在模拟器运行时使用 --sim。");
        return 3;
    }
}
#endif
