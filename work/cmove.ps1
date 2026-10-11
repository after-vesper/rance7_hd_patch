param([int]$X,[int]$Y,[double]$Scale=1.0)
# Move the mouse cursor to GAME CANVAS coordinates (no click).
# Uses the same conversion as click.ps1: ClientToScreen + frame offsets
# derived from the window rect. Fails loudly if the window is not found.
Add-Type @"
using System;using System.Runtime.InteropServices;
public class MV {
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref PT p);
public struct PT{public int X,Y;}
public struct RECT{public int Left,Top,Right,Bottom;}
}
"@
[MV]::SetProcessDpiAwarenessContext(-4) | Out-Null
$p = Get-Process -Name Rance7 -ErrorAction Stop
$h = $p.MainWindowHandle
if ($h -eq 0) { throw "Rance7 has no main window handle" }
$rc = New-Object MV+RECT
if (-not [MV]::GetWindowRect($h,[ref]$rc)) { throw "GetWindowRect failed" }
$w = $rc.Right-$rc.Left; $hh = $rc.Bottom-$rc.Top
if ($w -lt 1600 -or $hh -lt 1200) { throw "unexpected window rect ${w}x${hh}" }
$offX = ($w-1600)/2
$offY = ($hh-1200) - $offX
$pt = New-Object MV+PT; $pt.X=0; $pt.Y=0
if (-not [MV]::ClientToScreen($h,[ref]$pt)) { throw "ClientToScreen failed" }
$X = [int]($X*$Scale); $Y = [int]($Y*$Scale)
$scrx = $pt.X + ($X-$offX) + $offX   # = pt.X + X (client coords)
[MV]::SetCursorPos($pt.X + $X, $pt.Y + $Y) | Out-Null
Write-Output "cursor -> canvas ($X,$Y) = screen ($($pt.X+$X),$($pt.Y+$Y))"
