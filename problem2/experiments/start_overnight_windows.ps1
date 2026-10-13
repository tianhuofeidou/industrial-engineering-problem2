$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$taskOutput = Join-Path $taskRoot 'problem2\results\overnight_windows\run01'
$taskPython = 'D:\python3.14\python.exe'
if (Test-Path -LiteralPath $taskOutput) { throw '输出目录已存在，不重复启动。' }
Push-Location -LiteralPath $taskRoot
try {
    & $taskPython -B -m problem2.experiments.overnight_windows --phase prepare --output $taskOutput
    if ($LASTEXITCODE -ne 0) { throw '起点或配置准备失败。' }
    $taskProcesses = @()
    foreach ($taskWidth in @(3, 5, 7, 9)) {
        $taskArgs = @('-u', '-B', '-m', 'problem2.experiments.overnight_windows',
            '--phase', 'worker', '--output', ('"' + $taskOutput + '"'), '--width', "$taskWidth")
        $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArgs `
            -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $taskOutput "width$taskWidth.stdout.log") `
            -RedirectStandardError (Join-Path $taskOutput "width$taskWidth.stderr.log")
        $taskProcesses += [pscustomobject]@{ Width=$taskWidth; PID=$taskProcess.Id; Threads=4 }
    }
    [pscustomobject]@{ CreatedUtc=[DateTimeOffset]::UtcNow.ToString('o'); Processes=$taskProcesses;
        LauncherSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash;
        Output=$taskOutput } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskOutput 'launcher.json') -Encoding utf8
    $taskProcesses | ConvertTo-Json -Depth 3 -Compress
} finally {
    Pop-Location
}
