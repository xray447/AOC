// V-3：验证能否从 MSFS 的设施数据（SimConnect Facility Data）读到游戏内跑道几何。
// 用法：
//   dotnet run --project spikes/facility_probe -- WMKN                 # 请求跑道数据
//   dotnet run --project spikes/facility_probe -- WMKN --probe         # 逐个试探字段名是否被接受
using Microsoft.FlightSimulator.SimConnect;
using System.Runtime.InteropServices;

string[] positional = args.Where(a => !a.StartsWith("-")).ToArray();
string icao = positional.Length > 0 ? positional[0].ToUpperInvariant() : "WMKN";
bool probeOnly = args.Contains("--probe");

var simConnect = new SimConnect("AOC Facility Probe", IntPtr.Zero, 0x0402, null, 0);
bool opened = false;
bool ended = false;
int received = 0;
uint lastSend = 0;

simConnect.OnRecvOpen += (_, data) =>
{
    opened = true;
    Console.WriteLine($"已连上模拟器：{data.szApplicationName} (SimConnect {data.dwSimConnectVersionMajor}.{data.dwSimConnectVersionMinor})");
};
simConnect.OnRecvException += (_, e) =>
    Console.WriteLine($"  异常 {e.dwException} (send={e.dwSendID}, index={e.dwIndex})");
simConnect.OnRecvFacilityData += (_, data) =>
{
    received++;
    var recv = (SIMCONNECT_RECV_FACILITY_DATA)(object)data;
    string values = string.Join(" | ", (recv.Data ?? Array.Empty<object>())
        .Select(v => v is RunwayData r
            ? $"LEN={r.LENGTH} WID={r.WIDTH} HDG={r.HEADING} LAT={r.LATITUDE} LON={r.LONGITUDE}"
            : v?.ToString() ?? "null"));
    Console.WriteLine($"  [#{recv.ItemIndex}/{recv.ListSize} type={recv.Type}] {values}");
};
simConnect.OnRecvFacilityDataEnd += (_, _) => ended = true;

for (int i = 0; i < 100 && !opened; i++)
{
    PumpOnce(simConnect);
    Thread.Sleep(100);
    lastSend = 0;
}
if (!opened)
{
    Console.Error.WriteLine("10s 内没等到 SimConnect 连接（模拟器没开？）");
    return 2;
}

if (probeOnly)
{
    // 先注册定义结构，再逐个试探字段名
    try
    {
        simConnect.RegisterFacilityDataDefineStruct<RunwayData>(SIMCONNECT_FACILITY_DATA_TYPE.RUNWAY);
        Console.WriteLine("RegisterFacilityDataDefineStruct<RunwayData> OK");
    }
    catch (Exception exc)
    {
        Console.WriteLine($"RegisterFacilityDataDefineStruct 失败: {exc.GetType().Name}: {exc.Message}");
    }
    string[] candidates =
    {
        "LENGTH", "WIDTH", "HEADING", "SURFACE",
        "PRIMARY_NUMBER", "SECONDARY_NUMBER",
        "PRIMARY_LATITUDE", "PRIMARY_LONGITUDE", "PRIMARY_ALTITUDE", "PRIMARY_ELEVATION",
        "SECONDARY_LATITUDE", "SECONDARY_LONGITUDE", "SECONDARY_ELEVATION",
        "LATITUDE", "LONGITUDE", "ALTITUDE",
        "MARKINGS", "EDGE_LIGHT", "CENTER_LIGHT", "THRESHOLD_LIGHT",
    };
    foreach (string field in candidates)
    {
        try
        {
            simConnect.AddToFacilityDefinition(SIMCONNECT_FACILITY_DATA_TYPE.RUNWAY, field);
            Console.WriteLine($"add {field,-22} 已提交");
        }
        catch (Exception exc)
        {
            Console.WriteLine($"add {field,-22} 直接抛异常: {exc.GetType().Name}: {exc.Message}");
        }
        for (int i = 0; i < 3; i++)
        {
            PumpOnce(simConnect);
            Thread.Sleep(60);
        }
    }
    return 0;
}

simConnect.RegisterFacilityDataDefineStruct<RunwayData>(SIMCONNECT_FACILITY_DATA_TYPE.RUNWAY);
foreach (string field in new[] { "LENGTH", "WIDTH", "HEADING", "PRIMARY_LATITUDE", "PRIMARY_LONGITUDE" })
{
    simConnect.AddToFacilityDefinition(SIMCONNECT_FACILITY_DATA_TYPE.RUNWAY, field);
}
simConnect.RequestFacilityData(SIMCONNECT_FACILITY_DATA_TYPE.RUNWAY, REQUEST.RUNWAY, icao, "");

DateTime deadline = DateTime.UtcNow.AddSeconds(15);
while (!ended && DateTime.UtcNow < deadline)
{
    PumpOnce(simConnect);
    Thread.Sleep(100);
}
Console.WriteLine(received == 0 ? "没有收到任何跑道数据" : $"共 {received} 条");
return received == 0 ? 1 : 0;

static void PumpOnce(SimConnect sim)
{
    try
    {
        sim.ReceiveMessage();
    }
    catch (COMException)
    {
        // 没有待处理消息时抛 COM 异常，忽略
    }
}

enum REQUEST
{
    RUNWAY = 1,
}

/// <summary>跑道设施数据：字段顺序必须与 AddToFacilityDefinition 的添加顺序一致。</summary>
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi, Pack = 1)]
struct RunwayData
{
    public float LENGTH;
    public float WIDTH;
    public float HEADING;
    public double LATITUDE;
    public double LONGITUDE;
}
