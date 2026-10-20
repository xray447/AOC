using System.Globalization;

namespace SimLinkProbe;

public static class Runways
{
    public static List<Runway> LoadCsv(string path)
    {
        var list = new List<Runway>();
        if (!File.Exists(path)) return list;
        foreach (var line in File.ReadLines(path).Skip(1))
        {
            var p = line.Split(',');
            if (p.Length < 6) continue;
            list.Add(new Runway
            {
                Airport = p[0].Trim().ToUpperInvariant(),
                Name = p[1].Trim().ToUpperInvariant(),
                Heading = double.Parse(p[2], CultureInfo.InvariantCulture),
                Lat = double.Parse(p[3], CultureInfo.InvariantCulture),
                Lon = double.Parse(p[4], CultureInfo.InvariantCulture),
                ElevFt = double.Parse(p[5], CultureInfo.InvariantCulture),
            });
        }
        return list;
    }

    public static double DistanceNm(double lat1, double lon1, double lat2, double lon2)
    {
        const double r = 3440.065;
        double p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
        double dp = p2 - p1, dl = (lon2 - lon1) * Math.PI / 180;
        double h = Math.Sin(dp / 2) * Math.Sin(dp / 2)
                   + Math.Cos(p1) * Math.Cos(p2) * Math.Sin(dl / 2) * Math.Sin(dl / 2);
        return 2 * r * Math.Asin(Math.Min(1, Math.Sqrt(h)));
    }

    public static (Runway? runway, double distNm) Nearest(double lat, double lon, List<Runway> runways)
    {
        Runway? best = null;
        double bestD = double.MaxValue;
        foreach (var r in runways)
        {
            double d = DistanceNm(lat, lon, r.Lat, r.Lon);
            if (d < bestD) { bestD = d; best = r; }
        }
        return (best, bestD);
    }

    public static double HeadingDiff(double a, double b)
    {
        double d = (a - b + 540) % 360 - 180;
        return Math.Abs(d);
    }

    /// <summary>落地点相对跑道入口的纵向距离与横向偏差（右偏为正），单位米。</summary>
    public readonly record struct RunwayFix(double AlongM, double LateralM, double LengthM);

    /// <summary>
    /// 用入口点 + 着陆方向（真航向）建立跑道中心线，把落地点投影上去。
    /// 跑道长度由反向着陆方向那条 CSV 记录（如 36R ↔ 18L）反推，缺失时为 0。
    /// </summary>
    public static RunwayFix Locate(Runway rwy, double lat, double lon, List<Runway> all)
    {
        const double mPerDegLat = 110540.0;
        const double mPerDegLonEquator = 111320.0;
        double dx = (lon - rwy.Lon) * mPerDegLonEquator * Math.Cos(rwy.Lat * Math.PI / 180);
        double dy = (lat - rwy.Lat) * mPerDegLat;
        double th = rwy.Heading * Math.PI / 180;
        double along = dy * Math.Cos(th) + dx * Math.Sin(th);
        double lateral = dx * Math.Cos(th) - dy * Math.Sin(th);
        return new RunwayFix(along, lateral, ReciprocalLengthM(rwy, all));
    }

    private static double ReciprocalLengthM(Runway rwy, List<Runway> all)
    {
        var recip = ReciprocalName(rwy.Name);
        if (recip == null) return 0;
        var other = all.FirstOrDefault(r => r.Airport == rwy.Airport && r.Name == recip);
        return other == null ? 0 : DistanceNm(rwy.Lat, rwy.Lon, other.Lat, other.Lon) * 1852;
    }

    /// <summary>36R → 18L、09 → 27；无法解析时返回 null。</summary>
    public static string? ReciprocalName(string name)
    {
        int i = 0;
        while (i < name.Length && char.IsDigit(name[i])) i++;
        if (i == 0 || !int.TryParse(name[..i], out int num) || num is < 1 or > 36) return null;
        string suffix = name[i..].Trim().ToUpperInvariant();
        int recip = (num + 17) % 36 + 1;
        string recipSuffix = suffix switch { "L" => "R", "R" => "L", _ => suffix };
        return recip.ToString("00", CultureInfo.InvariantCulture) + recipSuffix;
    }
}
