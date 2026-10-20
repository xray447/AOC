namespace SimLinkProbe;

/// <summary>从 1Hz 样本中提取落地指标与阶段事件（V-02）。</summary>
public static class Analyzer
{
    public const double RunwayMatchRadiusNm = 2.0;

    /// <summary>相邻样本间隔超过该值认为中间有暂停/瞬移，不做起降转换判定。</summary>
    public const double MaxSampleGapS = 3.0;

    public static (List<Touchdown>, List<FlightEvent>) Analyze(
        List<TrackSample> samples, List<Runway> runways, string? airportFilter = null)
    {
        var touchdowns = new List<Touchdown>();
        var events = new List<FlightEvent>();
        for (int i = 1; i < samples.Count; i++)
        {
            var p = samples[i - 1];
            var s = samples[i];
            bool fresh = s.T - p.T <= MaxSampleGapS;

            if (fresh && !p.OnGround && s.OnGround)
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
                if (rw != null && dist <= RunwayMatchRadiusNm
                    && (airportFilter == null || rw.Airport == airportFilter.ToUpperInvariant()))
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
                events.Add(new FlightEvent { T = s.T, Type = "touchdown",
                    Detail = td.RunwayName != null ? $"{td.Airport}/{td.RunwayName}" : "runway_unknown" });
            }
            else if (fresh && p.OnGround && !s.OnGround)
            {
                events.Add(new FlightEvent { T = s.T, Type = "liftoff", Detail = "" });
            }

            if (fresh && p.Gear != s.Gear)
                events.Add(new FlightEvent { T = s.T, Type = "gear", Detail = s.Gear == 1 ? "down" : "up" });
            if (fresh && p.Flaps != s.Flaps)
                events.Add(new FlightEvent { T = s.T, Type = "flaps", Detail = s.Flaps.ToString() });
        }
        return (touchdowns, events);
    }
}
