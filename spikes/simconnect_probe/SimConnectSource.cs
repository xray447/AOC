#if HAVE_SIMCONNECT
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.FlightSimulator.SimConnect;

namespace SimLinkProbe;

/// <summary>
/// 真实 SimConnect 数据源（V-01/V-02）。只在检测到 MSFS SDK 托管 DLL 时编译。
/// 以 SIM_FRAME 周期读取，帧级数据用于抓着陆瞬间，落盘按 --hz 抽稀。
/// flight.jsonl 逐行实时落盘；每次落地立即刷新 touchdowns/events/session；
/// Ctrl+C（或 --seconds 0）会走正常收尾，不丢已采集数据。
/// </summary>
internal static class SimConnectSource
{
    private enum Definitions { State, Aircraft }
    private enum Requests { State, Aircraft }

    /// <summary>落地后继续跟踪 G 峰值的时长（秒）。</summary>
    private const double TouchdownPeakWindowS = 2.0;

    /// <summary>相邻两帧间隔超过该值认为中间有暂停/瞬移，不据此判定起降转换。</summary>
    private const double MaxFrameGapS = 3.0;

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
        public double Bank;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    private struct AircraftData
    {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string Title;
    }

    public static int Run(string outDir, int seconds, int hz, List<Runway> runways, string? airport,
        string? stopFile = null)
    {
        Directory.CreateDirectory(outDir);
        var samples = new List<TrackSample>();
        var touchdowns = new List<Touchdown>();
        var events = new List<FlightEvent>();
        var warnings = new List<string>();
        int frameCount = 0;
        bool opened = false;
        string simVersion = "";
        string aircraftTitle = "";
        var sw = Stopwatch.StartNew();
        double nextWrite = 0;
        TrackSample? prev = null;
        bool stop = false;
        StreamWriter? flightWriter = null;

        // 落地后继续跟踪 2s 内的 G 峰值（对方工具报的是峰值，不是触地帧瞬时值）
        Touchdown? peakTarget = null;
        double peakG = 0;
        double peakWindowEnd = -1;

        ConsoleCancelEventHandler onCancel = (_, e) =>
        {
            e.Cancel = true;
            stop = true;
        };
        Console.CancelKeyPress += onCancel;

        SessionReport Snapshot(double durationS) => new()
        {
            Source = "simconnect",
            Samples = samples.Count,
            DurationS = Math.Round(durationS, 1),
            Touchdowns = touchdowns.Count,
            Events = events.Count,
            FrameCount = frameCount,
            Fps = durationS > 0 ? Math.Round(frameCount / durationS, 1) : null,
            SimConnectVersion = simVersion,
            Aircraft = aircraftTitle,
            Warnings = new List<string>(warnings),
        };

        SimConnect? sc = null;
        try
        {
            flightWriter = OutputWriter.OpenFlightWriter(outDir);

            // hWnd=0 依赖 ReceiveMessage 轮询；若某版本要求窗口句柄，改用隐藏 NativeWindow。
            sc = new SimConnect("AOC SimLink Probe", IntPtr.Zero, 0, null, 0);

            sc.OnRecvOpen += (_, data) =>
            {
                opened = true;
                simVersion = $"{data.dwSimConnectVersionMajor}.{data.dwSimConnectVersionMinor}";
            };
            sc.OnRecvQuit += (_, _) =>
            {
                warnings.Add("sim_quit");
                stop = true;
            };
            sc.OnRecvException += (_, data) =>
            {
                warnings.Add($"simconnect_exception:{data.dwException}");
            };
            sc.OnRecvSimobjectData += (_, data) =>
            {
                if (data.dwRequestID == (uint)Requests.Aircraft)
                {
                    var a = (AircraftData)data.dwData[0];
                    aircraftTitle = (a.Title ?? "").Trim();
                    return;
                }

                var d = (StateData)data.dwData[0];
                frameCount++;
                var s = new TrackSample
                {
                    T = sw.Elapsed.TotalSeconds,
                    Lat = d.Latitude, Lon = d.Longitude, AltFt = d.Altitude, AglFt = d.Agl,
                    GsKt = d.GroundSpeed, VsFpm = d.VerticalSpeed, HdgDeg = d.Heading,
                    OnGround = d.OnGround != 0, FuelKg = d.Fuel, GForce = d.GForce,
                    // SimConnect 的 PLANE PITCH DEGREES 是「低头为正」，这里统一成抬头为正
                    PitchDeg = -d.Pitch, AoaDeg = d.Aoa, IasKt = d.Ias,
                    Gear = d.Gear, Flaps = (int)Math.Round(d.Flaps), BankDeg = d.Bank,
                };

                if (s.T >= nextWrite)
                {
                    samples.Add(s);
                    OutputWriter.WriteSample(flightWriter!, s);
                    // 以「本样本时间 + 1/hz」为下一格，避免暂停/断流后追写导致一秒内灌进几十条
                    nextWrite = s.T + 1.0 / Math.Max(1, hz);
                }

                if (peakTarget != null)
                {
                    if (s.GForce > peakG) peakG = s.GForce;
                    if (s.T >= peakWindowEnd)
                    {
                        peakTarget.GForcePeak = Math.Round(peakG, 2);
                        peakTarget = null;
                    }
                }

                // 帧间隔过大说明中间有暂停/重新载入，跳过瞬移造成的假起降
                bool fresh = prev != null && s.T - prev.T <= MaxFrameGapS;

                if (fresh && !prev!.OnGround && s.OnGround)
                {
                    var td = new Touchdown
                    {
                        T = Math.Round(s.T, 2), Lat = s.Lat, Lon = s.Lon,
                        VsFpm = Math.Round(s.VsFpm, 1), GForce = Math.Round(s.GForce, 2),
                        AoaDeg = Math.Round(s.AoaDeg, 1), IasKt = Math.Round(s.IasKt, 1),
                        HdgDeg = Math.Round(s.HdgDeg, 1), PitchDeg = Math.Round(s.PitchDeg, 1),
                        BankDeg = Math.Round(s.BankDeg, 1),
                    };
                    var (rw, dist) = Runways.Nearest(s.Lat, s.Lon, runways);
                    if (rw != null && dist <= Analyzer.RunwayMatchRadiusNm
                        && (airport == null || rw.Airport == airport))
                    {
                        td.Airport = rw.Airport;
                        td.RunwayName = rw.Name;
                        td.RunwayDistNm = Math.Round(dist, 3);
                        td.RunwayHdgDiffDeg = Math.Round(Runways.HeadingDiff(s.HdgDeg, rw.Heading), 1);
                        var fix = Runways.Locate(rw, s.Lat, s.Lon, runways);
                        td.RunwayAlongM = Math.Round(fix.AlongM, 1);
                        td.RunwayLateralM = Math.Round(fix.LateralM, 1);
                        if (fix.LengthM > 0) td.RunwayLengthM = Math.Round(fix.LengthM, 0);
                    }
                    touchdowns.Add(td);
                    events.Add(new FlightEvent
                    {
                        T = s.T, Type = "touchdown",
                        Detail = td.RunwayName != null ? $"{td.Airport}/{td.RunwayName}" : "runway_unknown",
                    });
                    peakTarget = td;
                    peakG = s.GForce;
                    peakWindowEnd = s.T + TouchdownPeakWindowS;
                    // 落地瞬间立即刷新结果文件：即使之后被强杀也不丢落地指标
                    OutputWriter.Save(outDir, samples, touchdowns, events, Snapshot(s.T), writeFlight: false);
                }
                else if (fresh && prev!.OnGround && !s.OnGround)
                {
                    events.Add(new FlightEvent { T = s.T, Type = "liftoff", Detail = "" });
                }
                if (fresh && prev!.Gear != s.Gear)
                    events.Add(new FlightEvent { T = s.T, Type = "gear", Detail = s.Gear == 1 ? "down" : "up" });
                if (fresh && prev!.Flaps != s.Flaps)
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
            sc.AddToDataDefinition(Definitions.State, "PLANE BANK DEGREES", "degrees", SIMCONNECT_DATATYPE.FLOAT64, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.RegisterDataDefineStruct<StateData>(Definitions.State);
            sc.RequestDataOnSimObject(Requests.State, Definitions.State,
                SimConnect.SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD.SIM_FRAME,
                SIMCONNECT_DATA_REQUEST_FLAG.CHANGED, 0, 0, 0);

            // 机型标题只取一次，用于报告里标注 A321 之类的机型
            sc.AddToDataDefinition(Definitions.Aircraft, "TITLE", null, SIMCONNECT_DATATYPE.STRING256, 0, SimConnect.SIMCONNECT_UNUSED);
            sc.RegisterDataDefineStruct<AircraftData>(Definitions.Aircraft);
            sc.RequestDataOnSimObject(Requests.Aircraft, Definitions.Aircraft,
                SimConnect.SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD.ONCE,
                (SIMCONNECT_DATA_REQUEST_FLAG)0, 0, 0, 0);

            // --seconds 0（或负数）= 一直采到 Ctrl+C
            bool unlimited = seconds <= 0;
            Console.Error.WriteLine(unlimited
                ? "采集中（不限时，Ctrl+C 结束并落盘）…"
                : $"采集中（{seconds}s，Ctrl+C 可提前结束并落盘）…");

            double nextStopCheck = 0;
            while (!stop && (unlimited || sw.Elapsed.TotalSeconds < seconds))
            {
                sc.ReceiveMessage();
                Thread.Sleep(5);
                if (stopFile != null && sw.Elapsed.TotalSeconds >= nextStopCheck)
                {
                    nextStopCheck = sw.Elapsed.TotalSeconds + 0.5;
                    if (File.Exists(stopFile))
                    {
                        try { File.Delete(stopFile); } catch { /* 删不掉也不影响收尾 */ }
                        stop = true;
                    }
                }
            }
        }
        catch (Exception exc)
        {
            warnings.Add($"fatal:{exc.GetType().Name}:{exc.Message}");
            Console.Error.WriteLine(exc.Message);
        }
        finally
        {
            Console.CancelKeyPress -= onCancel;
            // 窗口没走完就结束时，用已知峰值兜底
            if (peakTarget != null) peakTarget.GForcePeak = Math.Round(peakG, 2);
            try { flightWriter?.Dispose(); } catch { /* 关闭阶段的异常不影响已采集数据 */ }
            try { sc?.Dispose(); } catch { /* 关闭阶段的异常不影响已采集数据 */ }
        }

        var session = Snapshot(sw.Elapsed.TotalSeconds);
        OutputWriter.Save(outDir, samples, touchdowns, events, session, writeFlight: false);
        Console.WriteLine($"simconnect opened={opened} frames={frameCount} samples={samples.Count} " +
                          $"fps={session.Fps} touchdowns={touchdowns.Count} aircraft={session.Aircraft} out={outDir}");
        foreach (var td in touchdowns)
            Console.WriteLine($"  TD t={td.T}s vs={td.VsFpm}fpm g={td.GForce} peak={td.GForcePeak} " +
                              $"pitch={td.PitchDeg} rwy={td.Airport}/{td.RunwayName} dist={td.RunwayDistNm}nm");
        if (!opened) return 4;
        return frameCount > 0 ? 0 : 5;
    }
}
#else
namespace SimLinkProbe;

/// <summary>未编译 SimConnect 时的占位：明确告知需要 SDK，避免误以为已联调。</summary>
internal static class SimConnectSource
{
    public static int Run(string outDir, int seconds, int hz, List<Runway> runways, string? airport,
        string? stopFile = null)
    {
        Console.Error.WriteLine(
            "本二进制未编译 SimConnect 后端：未找到 Microsoft.FlightSimulator.SimConnect.dll。" +
            "请设置 SimConnectDll 指向 MSFS SDK 后重建，并在模拟器运行时使用 --sim。");
        return 3;
    }
}
#endif
