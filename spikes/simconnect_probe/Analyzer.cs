namespace SimLinkProbe;

/// <summary>从 1Hz 样本中提取落地指标与阶段事件（V-02）。</summary>
public static class Analyzer
{
    public const double RunwayMatchRadiusNm = 2.0;

    public static (List<Touchdown>, List<FlightEvent>) Analyze(
        List<TrackSample> samples, List<Runway> runways, string? airportFilter = null)
    {
        var touchdowns = new List<Touchdown>();
        var events = new List<FlightEvent>();
        for (int i = 1; i < samples.Count; i++)
        {
            var p = samples[i - 1];
            var s = samples[i];

            if (!p.OnGround && s.OnGround)
            {
                var td = new Touchdown
                {
                    T = s.T, Lat = s.Lat, Lon = s.Lon, VsFpm = s.VsFpm, GForce = s.GForce,
                    AoaDeg = s.AoaDeg, IasKt = s.IasKt, HdgDeg = s.HdgDeg,
                };
                var (rw, dist) = Runways.Nearest(s.Lat, s.Lon, runways);
                if (rw != null && dist <= RunwayMatchRadiusNm
                    && (airportFilter == null || rw.Airport == airportFilter.ToUpperInvariant()))
                {
                    td.Airport = rw.Airport;
                    td.RunwayName = rw.Name;
                    td.RunwayDistNm = Math.Round(dist, 3);
                    td.RunwayHdgDiffDeg = Math.Round(Runways.HeadingDiff(s.HdgDeg, rw.Heading), 1);
                }
                touchdowns.Add(td);
                events.Add(new FlightEvent { T = s.T, Type = "touchdown",
                    Detail = td.RunwayName != null ? $"{td.Airport}/{td.RunwayName}" : "runway_unknown" });
            }
            else if (p.OnGround && !s.OnGround)
            {
                events.Add(new FlightEvent { T = s.T, Type = "liftoff", Detail = "" });
            }

            if (p.Gear != s.Gear)
                events.Add(new FlightEvent { T = s.T, Type = "gear", Detail = s.Gear == 1 ? "down" : "up" });
            if (p.Flaps != s.Flaps)
                events.Add(new FlightEvent { T = s.T, Type = "flaps", Detail = s.Flaps.ToString() });
        }
        return (touchdowns, events);
    }
}
