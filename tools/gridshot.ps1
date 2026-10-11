param([string]$Out="work/grid.png",[int]$Div=2)
# Capture the Rance7 window, crop the game canvas (origin 3,67 in the
# window PNG, size 1600x1200), scale it down by $Div, and overlay a grid
# labelled in CANVAS coordinates every 100 canvas px.
# Whatever coordinate you read off the grid image IS the value to pass
# to cclick.ps1 — no further conversion needed.
Add-Type @"
using System;using System.Runtime.InteropServices;
public class M {
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
public struct RECT{public int Left,Top,Right,Bottom;}
}
"@
[M]::SetProcessDpiAwarenessContext(-4) | Out-Null
$p = Get-Process -Name Rance7 -ErrorAction Stop
$h = $p.MainWindowHandle
$rc = New-Object M+RECT; [M]::GetWindowRect($h,[ref]$rc) | Out-Null
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap ($rc.Right-$rc.Left),($rc.Bottom-$rc.Top)
$g=[System.Drawing.Graphics]::FromImage($bmp); $hdc=$g.GetHdc()
[M]::PrintWindow($h,$hdc,2)|Out-Null; $g.ReleaseHdc($hdc)
# crop canvas region
$canvas = New-Object System.Drawing.Bitmap 1600,1200
$g2=[System.Drawing.Graphics]::FromImage($canvas)
$g2.DrawImage($bmp,(New-Object System.Drawing.Rectangle 0,0,1600,1200),(New-Object System.Drawing.Rectangle 3,67,1600,1200),[System.Drawing.GraphicsUnit]::Pixel)
$g2.Dispose(); $bmp.Dispose()
# scale down
$W=1600/$Div; $H=1200/$Div
$sc = New-Object System.Drawing.Bitmap $W,$H
$g3=[System.Drawing.Graphics]::FromImage($sc)
$g3.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g3.DrawImage($canvas,0,0,$W,$H)
$canvas.Dispose()
# overlay grid every 100 canvas px -> every 100/$Div scaled px
$pen=New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(160,255,0,0)),1
$font=New-Object System.Drawing.Font("Consolas",[Math]::Max(9,14/$Div))
$brush=[System.Drawing.Brushes]::Yellow
$bg=[System.Drawing.Brushes]::Black
for($x=0;$x -le 1600;$x+=100){
  $sx=[int]($x/$Div)
  $g3.DrawLine($pen,$sx,0,$sx,$H)
  for($y=0;$y -le 1200;$y+=100){
    $sy=[int]($y/$Div)
    if($x -eq 0){ $g3.DrawLine($pen,0,$sy,$W,$sy) }
    if($x -gt 0 -and $y -gt 0){ $g3.DrawString("$x,$y",$font,$bg,$sx+1,$sy+1); $g3.DrawString("$x,$y",$font,$brush,$sx,$sy) }
  }
}
$g3.Dispose()
$sc.Save($Out)
Write-Output "saved $Out ($W x $H, canvas coords labelled)"
