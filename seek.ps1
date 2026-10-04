# Seeks Apple Music by moving its own progress slider.  Run by seeker.py and kept alive.
#
# Why: Apple Music reports IsPlaybackPositionEnabled = false to Windows' media session and
# silently drops position changes from it, so the only way to seek is its own "LCDScrubber"
# slider, through UI Automation.  WinUI only builds that UI while the window is shown, so a
# hidden (tray) Apple Music is shown for a moment far off-screen as a tool window -- no
# taskbar button, no focus -- the slider is set, and everything is put back as it was.
#
# Protocol: one line in ("seek 83.5"), one line out ("ok 240ms" / "err <reason>").

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices;
public struct AMPoint { public int x, y; }
public struct AMRect { public int l, t, r, b; }
public struct AMPlacement { public int len, flags, show; public AMPoint min, max; public AMRect normal; }
public static class AM {
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowPlacement(IntPtr h, ref AMPlacement p);
  [DllImport("user32.dll")] public static extern bool SetWindowPlacement(IntPtr h, ref AMPlacement p);
  [DllImport("user32.dll")] public static extern long GetWindowLongPtr(IntPtr h, int i);
  [DllImport("user32.dll")] public static extern long SetWindowLongPtr(IntPtr h, int i, long v);
}
'@

$GWL_EXSTYLE = -20
$WS_EX_TOOLWINDOW = 0x80
$WS_EX_APPWINDOW = 0x40000
$Invariant = [Globalization.CultureInfo]::InvariantCulture
$ScrubberId = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'LCDScrubber')

function Find-Scrubber([IntPtr]$hwnd, [int]$waitMs) {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($waitMs)
    do {
        $found = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $ScrubberId)
        if ($found) { return $found }
        Start-Sleep -Milliseconds 25
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Set-Scrubber($scrubber, [double]$seconds) {
    $range = $scrubber.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern)
    $target = [Math]::Max($range.Current.Minimum, [Math]::Min($range.Current.Maximum, $seconds))
    $range.SetValue($target)
}

function Seek([double]$seconds) {
    $hwnd = [AM]::FindWindow('WinUIDesktopWin32WindowClass', 'Apple Music')
    if ($hwnd -eq [IntPtr]::Zero) { return 'err not running' }
    $visible = [AM]::IsWindowVisible($hwnd)
    if ($visible -and -not [AM]::IsIconic($hwnd)) {
        $scrubber = Find-Scrubber $hwnd 500
        if (-not $scrubber) { return 'err no scrubber' }
        Set-Scrubber $scrubber $seconds
        return 'ok'
    }

    $saved = New-Object AMPlacement
    $saved.len = 44
    [void][AM]::GetWindowPlacement($hwnd, [ref]$saved)
    $exStyle = [AM]::GetWindowLongPtr($hwnd, $GWL_EXSTYLE)
    try {
        [void][AM]::SetWindowLongPtr($hwnd, $GWL_EXSTYLE,
            (($exStyle -bor $WS_EX_TOOLWINDOW) -band (-bnot $WS_EX_APPWINDOW)))
        $away = $saved
        $width = $saved.normal.r - $saved.normal.l
        $height = $saved.normal.b - $saved.normal.t
        $away.normal.l = -20000; $away.normal.t = -20000
        $away.normal.r = -20000 + $width; $away.normal.b = -20000 + $height
        $away.show = 4  # SW_SHOWNOACTIVATE
        [void][AM]::SetWindowPlacement($hwnd, [ref]$away)
        $scrubber = Find-Scrubber $hwnd 1500
        if (-not $scrubber) { return 'err no scrubber' }
        Set-Scrubber $scrubber $seconds
        return 'ok'
    } finally {
        [void][AM]::ShowWindow($hwnd, 0)
        [void][AM]::SetWindowLongPtr($hwnd, $GWL_EXSTYLE, $exStyle)
        # Hidden stays hidden; minimized on the taskbar goes back there without taking focus.
        $saved.show = if ($visible) { 7 } else { 0 }
        [void][AM]::SetWindowPlacement($hwnd, [ref]$saved)
    }
}

[Console]::Out.WriteLine('ready')
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line -or $line -eq 'quit') { break }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $parts = $line.Split(' ')
        if ($parts[0] -eq 'seek') {
            $answer = Seek ([double]::Parse($parts[1], $Invariant))
        } else {
            $answer = "err unknown command"
        }
    } catch {
        $answer = "err $($_.Exception.Message -replace '\s+', ' ')"
    }
    [Console]::Out.WriteLine("$answer $($clock.ElapsedMilliseconds)ms")
    [Console]::Out.Flush()
}
