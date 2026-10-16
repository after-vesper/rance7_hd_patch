# Rance7 ウィンドウ全体キャプチャ (4K/150% DPI 環境対応)
# 使い方: powershell -File tools/cap.ps1 <出力png> -Keys "down,down,enter"
param(
    [Parameter(Mandatory=$true)][string]$Out,
    [string]$Keys = "",
    [int]$KeyDelay = 400
)
Add-Type @"
using System;using System.Runtime.InteropServices;
public class K {
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern void keybd_event(byte k,byte s,uint f,IntPtr e);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
public struct RECT{public int Left,Top,Right,Bottom;}
}
"@
# 重要: 呼び出し側プロセスを PerMonitorV2 にしてから座標を取る
[K]::SetProcessDpiAwarenessContext(-4) | Out-Null
Add-Type -AssemblyName System.Drawing

$p = Get-Process -Name Rance7 -ErrorAction Stop
$h = $p.MainWindowHandle
[K]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 600

function Send-Key([byte]$vk) {
    [K]::keybd_event($vk,0,0,[IntPtr]::Zero)
    Start-Sleep -Milliseconds 120
    [K]::keybd_event($vk,0,2,[IntPtr]::Zero)
}
$map = @{ 'up'=0x26; 'down'=0x28; 'left'=0x25; 'right'=0x27; 'enter'=0x0D; 'esc'=0x1B; 'space'=0x20 }
foreach ($k in ($Keys -split ',' | Where-Object { $_ })) {
    Send-Key $map[$k.Trim()]
    Start-Sleep -Milliseconds $KeyDelay
}

# ウィンドウ全体 (タイトルバー含む)
$rc = New-Object K+RECT
[K]::GetWindowRect($h,[ref]$rc) | Out-Null
$w = $rc.Right - $rc.Left; $hh = $rc.Bottom - $rc.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[K]::PrintWindow($h, $hdc, 2) | Out-Null   # PW_RENDERFULLCONTENT
$g.ReleaseHdc($hdc)
$bmp.Save($Out)
Write-Output "saved $Out ${w}x${hh}"
