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
}
