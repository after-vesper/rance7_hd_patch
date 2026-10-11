param([string]$Out="work/cursor.png",[int]$W=500,[int]$H=320)
# Capture the real screen around the mouse cursor (cursor IS visible,
# unlike PrintWindow). Use after cmove.ps1 to verify where the pointer
# actually sits before clicking.
Add-Type @"
using System;using System.Runtime.InteropServices;
public class CP {
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out PT p);
public struct PT{public int X,Y;}
}
"@
[CP]::SetProcessDpiAwarenessContext(-4) | Out-Null
$pt = New-Object CP+PT; [CP]::GetCursorPos([ref]$pt) | Out-Null
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $W,$H
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($pt.X-[int]($W/2), $pt.Y-[int]($H/2), 0,0, $bmp.Size)
$bmp.Save($Out)
Write-Output "saved $Out (cursor at screen $($pt.X),$($pt.Y))"
