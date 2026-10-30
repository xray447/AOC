using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;

namespace AocSimLink;

internal static class Program
{
    private sealed class CommandRequest
    {
        [JsonPropertyName("action")] public string Action { get; set; } = "";
        [JsonPropertyName("hz")] public double? Hz { get; set; }
        [JsonPropertyName("enabled")] public bool? Enabled { get; set; }
        /// <summary>`set_auto_start_mode`：engine / taxi / takeoff。</summary>
        [JsonPropertyName("mode")] public string? Mode { get; set; }
        /// <summary>`set_auto_stop_hold`：连续静止/停机刹车保持秒数。</summary>
        [JsonPropertyName("seconds")] public double? Seconds { get; set; }
    }

    private static async Task<int> Main(string[] args)
    {
        var opts = ParseArgs(args);
        string home = opts.GetValueOrDefault("home")
                      ?? Environment.GetEnvironmentVariable("AOC_HOME")
                      ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AOC");
        Directory.CreateDirectory(home);
        int port = int.Parse(opts.GetValueOrDefault("port", "0"));
        string token = opts.GetValueOrDefault("token") ?? Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
        string runtimePath = opts.GetValueOrDefault("runtime", Path.Combine(home, "simlink-runtime.json"));
        bool auto = !opts.ContainsKey("no-auto");
        double hz = double.Parse(opts.GetValueOrDefault("hz", "1"), System.Globalization.CultureInfo.InvariantCulture);

        ISimSource source;
        if (opts.TryGetValue("replay", out var replay))
            source = new ReplaySource(replay, double.Parse(opts.GetValueOrDefault("replay-speed", "4"),
                System.Globalization.CultureInfo.InvariantCulture));
        else if (opts.ContainsKey("demo") || opts.GetValueOrDefault("source") == "demo")
            source = new DemoSource(double.Parse(opts.GetValueOrDefault("demo-speed", "12"),
                System.Globalization.CultureInfo.InvariantCulture));
        else
            source = new SimConnectSource();

        using var engine = new Engine(source, home) { AutoStart = auto };
        engine.SetRate(hz);

        var builder = WebApplication.CreateBuilder();
        builder.Logging.ClearProviders();
        builder.WebHost.ConfigureKestrel(options => options.Listen(IPAddress.Loopback, port));

        var app = builder.Build();
        app.Use(async (ctx, next) =>
        {
            var path = ctx.Request.Path.Value ?? "";
            bool protectedPath = path.StartsWith("/status") || path.StartsWith("/samples")
                                 || path.StartsWith("/events") || path.StartsWith("/command")
                                 || path.StartsWith("/latest");
            if (protectedPath && ctx.Request.Headers["X-SimLink-Token"] != token)
            {
                ctx.Response.StatusCode = 401;
                await ctx.Response.WriteAsJsonAsync(new { code = "AUTH_INVALID", message = "bad simlink token" });
                return;
            }
            await next();
        });

        app.MapGet("/health", () => Results.Json(new { ok = true, version = "0.1.0" }));
        app.MapGet("/status", () => Results.Json(engine.Status()));
        app.MapGet("/latest", () => Results.Json(new { sample = engine.LatestSample() }));
        app.MapGet("/samples", (long? since, int? limit) =>
        {
            var (samples, last) = engine.Samples(since ?? -1, limit ?? 3000);
            return Results.Json(new { samples, last_seq = last, count = samples.Count });
        });
        app.MapGet("/events", (long? since, int? limit) =>
        {
            var (events, last) = engine.Events(since ?? -1, limit ?? 500);
            return Results.Json(new { events, last_seq = last, count = events.Count });
        });
        app.MapPost("/command", (CommandRequest cmd) =>
        {
            switch (cmd.Action)
            {
                case "start_recording":
                    return Results.Json(engine.StartRecording(manual: true));
                case "stop_recording":
                    return Results.Json(engine.StopRecording());
                case "set_rate":
                    engine.SetRate(cmd.Hz ?? 1.0);
                    return Results.Json(engine.Status());
                case "set_auto_start":
                    engine.AutoStart = cmd.Enabled ?? true;
                    return Results.Json(engine.Status());
                case "set_auto_start_mode":
                    engine.AutoStartMode = (cmd.Mode ?? "engine").ToLowerInvariant() switch
                    {
                        "taxi" => "taxi",
                        "takeoff" => "takeoff",
                        _ => "engine",
                    };
                    return Results.Json(engine.Status());
                case "set_auto_stop_hold":
                    engine.AutoStopHoldS = Math.Clamp(cmd.Seconds ?? 60.0, 30.0, 300.0);
                    return Results.Json(engine.Status());
                case "reconnect":
                    // 立即重建 SimConnect；后台循环本来也会按 5s 退避重试
                    engine.ReconnectSource();
                    return Results.Json(engine.Status());
                default:
                    return Results.Json(new { ok = false, error = $"unknown action: {cmd.Action}" });
            }
        });

        try
        {
            engine.Start();
        }
        catch (Exception exc)
        {
            Console.Error.WriteLine($"source start failed: {exc.GetType().Name}: {exc.Message}");
        }

        await app.StartAsync();
        var addresses = app.Services.GetRequiredService<IServer>()
            .Features.Get<IServerAddressesFeature>()?.Addresses;
        var address = addresses?.FirstOrDefault() ?? $"http://127.0.0.1:{port}";
        if (Uri.TryCreate(address, UriKind.Absolute, out var uri)) port = uri.Port;
        var runtime = new RuntimeInfo
        {
            Pid = Environment.ProcessId,
            Port = port,
            Url = $"http://127.0.0.1:{port}",
            Token = token,
            StartedAt = TimeUtil.Iso(DateTime.UtcNow),
            Source = source.Name,
        };
        File.WriteAllText(runtimePath, JsonSerializer.Serialize(runtime,
            new JsonSerializerOptions { WriteIndented = true }));
        Console.Error.WriteLine($"aoc-simlink {source.Name} listening on {runtime.Url} (auto={auto}, hz={hz})");

        var stop = new TaskCompletionSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            stop.TrySetResult();
        };
        AppDomain.CurrentDomain.ProcessExit += (_, _) => stop.TrySetResult();
        await stop.Task;
        engine.Stop();
        await app.StopAsync();
        return 0;
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < args.Length; i++)
        {
            var a = args[i];
            if (!a.StartsWith("--")) continue;
            var key = a[2..];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--"))
                d[key] = args[++i];
            else
                d[key] = "1";
        }
        return d;
    }
}
