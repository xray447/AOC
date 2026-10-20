namespace AocSimLink;

/// <summary>
/// 自适应保存（与 aoc-core/track.py 同口径）。SimLink 内部仍按 1Hz 采样，
/// 这里只决定哪些点进本地队列，便于离线排障；aoc-core 会再做一次分段编码。
/// </summary>
public sealed class AdaptiveSampler
{
    public const string Straight = "STRAIGHT";
    public const string Turn = "TURN";
    public const string Climb = "CLIMB_DESCENT";
    public const string Approach = "APPROACH";
    public const string Taxi = "TAXI";

    public double TurnEnterDps { get; set; } = 4.0;
    public double TurnExitDps { get; set; } = 1.5;
    public double TurnExitHoldS { get; set; } = 4.0;
    public double ClimbVsFpm { get; set; } = 1000.0;
    public double TaxiGsKt { get; set; } = 40.0;
    public double ApproachAglFt { get; set; } = 3000.0;
    public double MaxGapS { get; set; } = 45.0;
    public double ForceHdgDeg { get; set; } = 3.0;
    public double ForceAltFt { get; set; } = 300.0;
    public double ForceDistNm { get; set; } = 2.0;
    public double ForceVsFpm { get; set; } = 800.0;

    private string _mode = Taxi;
    private double? _turnBelowSince;
    private Sample? _lastFrame;
    private Sample? _lastSaved;

    public string Mode => _mode;

    public static double AngDiff(double a, double b) => (a - b + 540.0) % 360.0 - 180.0;

    public static double DistanceNm(double lat1, double lon1, double lat2, double lon2)
    {
        const double r = 3440.065;
        double p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
        double dp = p2 - p1, dl = (lon2 - lon1) * Math.PI / 180;
        double h = Math.Sin(dp / 2) * Math.Sin(dp / 2)
                   + Math.Cos(p1) * Math.Cos(p2) * Math.Sin(dl / 2) * Math.Sin(dl / 2);
        return 2 * r * Math.Asin(Math.Min(1, Math.Sqrt(h)));
    }

    private string Detect(Sample s, double turnRate)
    {
        if (!s.OnGround && s.AglFt < ApproachAglFt && s.VsFpm < 0) return Approach;
        if (turnRate > TurnEnterDps)
        {
            _turnBelowSince = null;
            return Turn;
        }
        if (_mode == Turn)
        {
            if (Math.Abs(turnRate) < TurnExitDps)
            {
                _turnBelowSince ??= s.T;
                if (s.T - _turnBelowSince < TurnExitHoldS) return Turn;
                _turnBelowSince = null;
            }
            else
            {
                _turnBelowSince = null;
                return Turn;
            }
        }
        if (s.OnGround) return s.GsKt < TaxiGsKt ? Taxi : Straight;
        if (Math.Abs(s.VsFpm) > ClimbVsFpm) return Climb;
        return Straight;
    }

    /// <summary>返回该点是否应保存，并写入 Mode/Saved。</summary>
    public bool Update(Sample s)
    {
        var dt = _lastFrame == null ? 1.0 : Math.Max(1e-6, s.T - _lastFrame.T);
        var rate = _lastFrame == null ? 0.0 : Math.Abs(AngDiff(s.HdgTrue, _lastFrame.HdgTrue)) / dt;
        _mode = Detect(s, rate);
        s.Mode = _mode;
        bool save = _lastSaved == null;
        if (_lastSaved != null)
        {
            double elapsed = s.T - _lastSaved.T;
            double interval = _mode switch
            {
                Turn => 2.0,
                Climb => 5.0,
                Approach => 1.0,
                Taxi => 10.0,
                _ => 20.0,
            };
            if (Math.Abs(AngDiff(s.HdgTrue, _lastSaved.HdgTrue)) >= ForceHdgDeg) save = true;
            else if (Math.Abs(s.AltFt - _lastSaved.AltFt) >= ForceAltFt) save = true;
            else if (DistanceNm(_lastSaved.Lat, _lastSaved.Lon, s.Lat, s.Lon) >= ForceDistNm) save = true;
            else if (Math.Abs(s.VsFpm - _lastSaved.VsFpm) >= ForceVsFpm) save = true;
            else if (elapsed >= MaxGapS) save = true;
            else if (elapsed >= interval) save = true;
        }
        s.Saved = save;
        if (save) _lastSaved = s;
        _lastFrame = s;
        return save;
    }
}
