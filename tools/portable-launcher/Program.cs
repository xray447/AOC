// AOC 便携版启动器（P-11 / A-32）：
// 无控制台拉起包内 aoc-core.exe + aoc-simlink.exe，托盘图标 + 菜单，
// 健康检查通过后打开默认浏览器；单实例，退出时结束两个 sidecar。
using System.Diagnostics;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace AocPortable;

internal static class Program
{
    private const string MutexName = "Local\\AOC-portable-single-instance";
    private const string ClassName = "AOCPortableTrayWindow";
    private const int WmApp = 0x8000;
    private const int WmTray = WmApp + 1;
    private const int WmCommand = 0x0111;
    private const int WmDestroy = 0x0002;
    private const int WmNull = 0x0000;
    private const int WmLButtonUp = 0x0202;
    private const int WmRButtonUp = 0x0205;
    private const int IdOpen = 1;
    private const int IdLogs = 2;
    private const int IdQuit = 3;
    private const uint NifMessage = 0x01;
    private const uint NifIcon = 0x02;
    private const uint NifTip = 0x04;
    private const uint NimAdd = 0x00;
    private const uint NimDelete = 0x02;
    private const uint MfString = 0x0000;
    private const uint MfSeparator = 0x0800;
    private const uint TpmRightButton = 0x0002;
    private const uint TpmBottomAlign = 0x0020;

    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(3) };
    private static readonly object LogLock = new();
    private static readonly List<Process> Children = new();
    private static readonly WndProcDelegate WndProcKeepAlive = WndProc;

    private static string _root = "";
    private static string _home = "";
    private static string _logs = "";
    private static IntPtr _hwnd;
    private static IntPtr _job;
    private static string? _clientUrl;

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate IntPtr WndProcDelegate(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WndClassEx
    {
        public uint cbSize;
        public uint style;
        public IntPtr lpfnWndProc;
        public int cbClsExtra;
        public int cbWndExtra;
        public IntPtr hInstance;
        public IntPtr hIcon;
        public IntPtr hCursor;
        public IntPtr hbrBackground;

        [MarshalAs(UnmanagedType.LPWStr)]
        public string? lpszMenuName;

        [MarshalAs(UnmanagedType.LPWStr)]
        public string lpszClassName;

        public IntPtr hIconSm;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NotifyIconData
    {
        public uint cbSize;
        public IntPtr hWnd;
        public uint uID;
        public uint uFlags;
        public uint uCallbackMessage;
        public IntPtr hIcon;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string szTip;

        public uint dwState;
        public uint dwStateMask;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string szInfo;

        public uint uVersion;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)]
        public string szInfoTitle;

        public uint dwInfoFlags;
        public Guid guidItem;
        public IntPtr hBalloonIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        public int X;
        public int Y;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr GetModuleHandleW(string? name);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern ushort RegisterClassExW(ref WndClassEx wndClass);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateWindowExW(uint exStyle, string className, string windowName,
        uint style, int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);

    [DllImport("user32.dll")]
    private static extern IntPtr DefWindowProcW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern void DestroyWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern void PostQuitMessage(int exitCode);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out Point point);

    [DllImport("user32.dll")]
    private static extern IntPtr CreatePopupMenu();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool AppendMenuW(IntPtr menu, uint flags, int id, string? item);

    [DllImport("user32.dll")]
    private static extern bool DestroyMenu(IntPtr menu);

    [DllImport("user32.dll")]
    private static extern bool TrackPopupMenu(IntPtr menu, uint flags, int x, int y, int reserved,
        IntPtr hWnd, IntPtr rect);

    [DllImport("user32.dll")]
    private static extern bool PostMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Shell_NotifyIconW(uint message, ref NotifyIconData data);

    [DllImport("user32.dll")]
    private static extern IntPtr LoadIconW(IntPtr instance, IntPtr iconName);

    // Job Object：启动器被杀掉（任务管理器/崩溃）时一并结束 sidecar，避免残留进程
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObjectW(IntPtr attributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass,
        ref JobObjectExtendedLimitInformation info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    private const int JobObjectExtendedLimitInformationClass = 9;
    private const uint JobObjectLimitKillOnJobClose = 0x2000;

    [DllImport("user32.dll")]
    private static extern int GetMessageW(out Msg msg, IntPtr hWnd, uint min, uint max);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref Msg msg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessageW(ref Msg msg);

    [StructLayout(LayoutKind.Sequential)]
    private struct Msg
    {
        public IntPtr hWnd;
        public uint message;
        public IntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public Point pt;
    }

    private static int Main()
    {
        using var mutex = new Mutex(true, MutexName, out var created);
        _root = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        _home = Environment.GetEnvironmentVariable("AOC_HOME")
                ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AOC");
        _logs = Path.Combine(_home, "logs");
        Directory.CreateDirectory(_home);
        Directory.CreateDirectory(_logs);

        if (!created)
        {
            // 已有实例：只打开页面，不重复起进程
            OpenClient();
            return 0;
        }

        _hwnd = CreateTrayWindow();
        if (_hwnd == IntPtr.Zero)
        {
            Log("launcher", "托盘窗口创建失败，退出");
            return 1;
        }
        AddTrayIcon();
        CreateJob();

        StartCore();
        StartSimlink();
        _ = Task.Run(OpenWhenReadyAsync);

        while (GetMessageW(out var msg, IntPtr.Zero, 0, 0) > 0)
        {
            TranslateMessage(ref msg);
            DispatchMessageW(ref msg);
        }
        Shutdown();
        return 0;
    }

    // -- 托盘 ---------------------------------------------------------------
    private static IntPtr CreateTrayWindow()
    {
        var instance = GetModuleHandleW(null);
        var wndClass = new WndClassEx
        {
            cbSize = (uint)Marshal.SizeOf<WndClassEx>(),
            lpfnWndProc = Marshal.GetFunctionPointerForDelegate(WndProcKeepAlive),
            hInstance = instance,
            lpszClassName = ClassName,
        };
        if (RegisterClassExW(ref wndClass) == 0 && Marshal.GetLastWin32Error() != 1410)
        {
            return IntPtr.Zero;
        }
        return CreateWindowExW(0, ClassName, "AOC", 0, 0, 0, 0, 0,
            IntPtr.Zero, IntPtr.Zero, instance, IntPtr.Zero);
    }

    private static void AddTrayIcon()
    {
        var data = new NotifyIconData
        {
            cbSize = (uint)Marshal.SizeOf<NotifyIconData>(),
            hWnd = _hwnd,
            uID = 1,
            uFlags = NifMessage | NifIcon | NifTip,
            uCallbackMessage = WmTray,
            hIcon = LoadIconW(IntPtr.Zero, (IntPtr)32512), // IDI_APPLICATION
            szTip = "AOC · 模拟飞行运行中心",
            szInfo = "",
            szInfoTitle = "",
        };
        if (!Shell_NotifyIconW(NimAdd, ref data))
        {
            Log("launcher", $"托盘图标添加失败（Win32 错误 {Marshal.GetLastWin32Error()}）");
        }
    }

    private static void RemoveTrayIcon()
    {
        var data = new NotifyIconData
        {
            cbSize = (uint)Marshal.SizeOf<NotifyIconData>(),
            hWnd = _hwnd,
            uID = 1,
            szTip = "",
            szInfo = "",
            szInfoTitle = "",
        };
        Shell_NotifyIconW(NimDelete, ref data);
    }

    private static IntPtr WndProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        switch (msg)
        {
            case WmTray:
                var evt = (int)(lParam.ToInt64() & 0xFFFF);
                if (evt == WmLButtonUp)
                {
                    OpenClient();
                    return IntPtr.Zero;
                }
                if (evt == WmRButtonUp)
                {
                    ShowMenu(hWnd);
                    return IntPtr.Zero;
                }
                break;
            case WmCommand:
                switch ((int)(wParam.ToInt64() & 0xFFFF))
                {
                    case IdOpen:
                        OpenClient();
                        return IntPtr.Zero;
                    case IdLogs:
                        OpenLogs();
                        return IntPtr.Zero;
                    case IdQuit:
                        RemoveTrayIcon();
                        DestroyWindow(hWnd);
                        return IntPtr.Zero;
                }
                break;
            case WmDestroy:
                PostQuitMessage(0);
                return IntPtr.Zero;
        }
        return DefWindowProcW(hWnd, msg, wParam, lParam);
    }

    private static void ShowMenu(IntPtr hWnd)
    {
        var menu = CreatePopupMenu();
        AppendMenuW(menu, MfString, IdOpen, "打开客户端");
        AppendMenuW(menu, MfString, IdLogs, "打开日志目录");
        AppendMenuW(menu, MfSeparator, 0, null);
        AppendMenuW(menu, MfString, IdQuit, "退出");
        GetCursorPos(out var pt);
        SetForegroundWindow(hWnd);
        TrackPopupMenu(menu, TpmRightButton | TpmBottomAlign, pt.X, pt.Y, 0, hWnd, IntPtr.Zero);
        DestroyMenu(menu);
        PostMessageW(hWnd, WmNull, IntPtr.Zero, IntPtr.Zero);
    }

    // -- 菜单动作 -----------------------------------------------------------
    private static void OpenClient()
    {
        var url = _clientUrl ?? ReadRuntimeUrl();
        if (string.IsNullOrWhiteSpace(url))
        {
            url = "http://127.0.0.1:8765/";
        }
        TryStart(url, null);
    }

    private static void OpenLogs() => TryStart("explorer.exe", _logs);

    private static void TryStart(string file, string? args)
    {
        try
        {
            var info = new ProcessStartInfo(file) { UseShellExecute = true };
            if (args != null)
            {
                info.Arguments = $"\"{args}\"";
            }
            Process.Start(info);
        }
        catch (Exception exc)
        {
            Log("launcher", $"启动失败 {file}: {exc.Message}");
        }
    }

    // -- sidecar ------------------------------------------------------------
    private static void CreateJob()
    {
        _job = CreateJobObjectW(IntPtr.Zero, null);
        if (_job == IntPtr.Zero)
        {
            Log("launcher", $"创建 Job Object 失败（Win32 错误 {Marshal.GetLastWin32Error()}）");
            return;
        }
        var info = new JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new JobObjectBasicLimitInformation
            {
                LimitFlags = JobObjectLimitKillOnJobClose,
            },
        };
        if (!SetInformationJobObject(_job, JobObjectExtendedLimitInformationClass, ref info,
                (uint)Marshal.SizeOf<JobObjectExtendedLimitInformation>()))
        {
            Log("launcher", $"设置 Job Object 失败（Win32 错误 {Marshal.GetLastWin32Error()}）");
            _job = IntPtr.Zero;
        }
    }

    private static void StartCore()
    {
        var exe = FindCore();
        if (exe == null)
        {
            Log("launcher", "未找到 aoc-core.exe");
            return;
        }
        var staticDir = Path.Combine(_root, "app");
        var args = new List<string> { "--port", "0", "--home", _home, "--static-dir", staticDir };
        StartProcess(exe, args, "core");
    }

    private static void StartSimlink()
    {
        var exe = Path.Combine(_root, "apps", "simlink", "aoc-simlink.exe");
        if (!File.Exists(exe))
        {
            exe = Path.Combine(_root, "simlink", "aoc-simlink.exe");
        }
        if (!File.Exists(exe))
        {
            Log("launcher", "未找到 aoc-simlink.exe，遥测不可用");
            return;
        }
        StartProcess(exe, new List<string> { "--port", "0", "--home", _home }, "simlink");
    }

    private static string? FindCore()
    {
        string[] candidates =
        {
            Path.Combine(_root, "aoc-core", "aoc-core.exe"),
            Path.Combine(_root, "core", "aoc-core.exe"),
            Path.Combine(_root, "aoc-core.exe"),
        };
        return candidates.FirstOrDefault(File.Exists);
    }

    private static void StartProcess(string exe, List<string> args, string logName)
    {
        try
        {
            var info = new ProcessStartInfo(exe)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = _root,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            foreach (var arg in args)
            {
                info.ArgumentList.Add(arg);
            }
            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) => { if (e.Data != null) Log(logName, e.Data); };
            process.ErrorDataReceived += (_, e) => { if (e.Data != null) Log(logName, e.Data); };
            process.Start();
            if (_job != IntPtr.Zero)
            {
                // 启动器被强杀时由 Job Object 连带结束 sidecar
                AssignProcessToJobObject(_job, process.Handle);
            }
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            lock (Children)
            {
                Children.Add(process);
            }
            Log("launcher", $"{logName} started (pid {process.Id})");
        }
        catch (Exception exc)
        {
            Log("launcher", $"{logName} 启动失败：{exc.Message}");
        }
    }

    private static void Log(string name, string line)
    {
        try
        {
            lock (LogLock)
            {
                File.AppendAllText(Path.Combine(_logs, $"{name}.log"),
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {line}{Environment.NewLine}", Encoding.UTF8);
            }
        }
        catch
        {
            // 日志写不进去不影响运行
        }
    }

    private static void Shutdown()
    {
        lock (Children)
        {
            foreach (var process in Children)
            {
                try
                {
                    if (!process.HasExited)
                    {
                        process.Kill(entireProcessTree: true);
                        process.WaitForExit(3000);
                    }
                }
                catch
                {
                    // 进程可能已自行退出
                }
            }
            Children.Clear();
        }
    }

    // -- 健康检查 -----------------------------------------------------------
    private static async Task OpenWhenReadyAsync()
    {
        var deadline = DateTime.UtcNow.AddSeconds(90);
        while (DateTime.UtcNow < deadline)
        {
            var url = ReadRuntimeUrl();
            if (url != null)
            {
                try
                {
                    using var response = await Http.GetAsync(url.TrimEnd('/') + "/local/health");
                    if (response.IsSuccessStatusCode)
                    {
                        _clientUrl = url;
                        OpenClient();
                        return;
                    }
                }
                catch
                {
                    // 还没起来，继续等
                }
            }
            await Task.Delay(500);
        }
        Log("launcher", "健康检查超时，请手动打开托盘菜单里的客户端");
    }

    private static string? ReadRuntimeUrl()
    {
        try
        {
            var path = Path.Combine(_home, "runtime.json");
            if (!File.Exists(path))
            {
                return null;
            }
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.TryGetProperty("url", out var url))
            {
                var value = url.GetString();
                return string.IsNullOrWhiteSpace(value) ? null : value;
            }
        }
        catch
        {
            // runtime.json 可能正写到一半
        }
        return null;
    }
}
