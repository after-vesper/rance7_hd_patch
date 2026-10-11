param([int]$X,[int]$Y,[string]$Out="",[int]$Wait=800,[double]$Scale=1.0)
# Click at GAME CANVAS coordinates (0,0)-(1600,1200) HD / (0,0)-(800,600) vanilla.
# Canvas origin inside the window PNG is (3,67) — verified via ClientToScreen.
$X = [int]($X*$Scale) + 3
$Y = [int]($Y*$Scale) + 67
& "$PSScriptRoot\click.ps1" -X $X -Y $Y -Out $Out -Wait $Wait
