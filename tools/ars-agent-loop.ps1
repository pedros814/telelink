<#
.SYNOPSIS
    ARS golden-path smoke test for agents/devs.
.DESCRIPTION
    Runs: agent context → ars start → ars next --raw → (optional send) → ars ack → ars next → ars stop.
.PARAMETER Session
    Session slug (e.g. client-ars)
.PARAMETER Contact
    Contact name or phone
.PARAMETER DryRun
    If set, skips actual send and ack
.EXAMPLE
    .\tools\ars-agent-loop.ps1 -Session client-ars -Contact Client -DryRun
    .\tools\ars-agent-loop.ps1 -Session client-ars -Contact Client
#>
param(
    [Parameter(Mandatory=$true)][string]$Session,
    [Parameter(Mandatory=$true)][string]$Contact,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$run = ".\telelink.ps1"

Write-Host "`n=== ARS Golden Path ==="  -ForegroundColor Cyan
Write-Host "Session: $Session  Contact: $Contact  DryRun: $DryRun`n"

# Step 0: Agent context
Write-Host "[0] agent context" -ForegroundColor Yellow
& $run agent context

# Step 1: Start
Write-Host "`n[1] ars start $Session $Contact" -ForegroundColor Yellow
& $run ars start $Session $Contact

# Step 2: Next
Write-Host "`n[2] ars next $Session --raw" -ForegroundColor Yellow
$next = & $run ars next $Session --raw | ConvertFrom-Json
$next | ConvertTo-Json -Depth 5

if ($next.action -eq 'reply') {
    Write-Host "`n[3] Thread:" -ForegroundColor Yellow
    & $run convo $Contact --raw

    if (-not $DryRun) {
        $msg = Read-Host "`nType SMS to send (or Enter to skip)"
        if ($msg) {
            Write-Host "`n[5] send $Contact $msg" -ForegroundColor Yellow
            & $run send $Contact $msg
        }

        Write-Host "`n[6] ars ack $Session" -ForegroundColor Yellow
        & $run ars ack $Session
    } else {
        Write-Host "`n[DRY RUN] skipping send and ack" -ForegroundColor Gray
    }

    Write-Host "`n[7] ars next $Session --raw" -ForegroundColor Yellow
    & $run ars next $Session --raw
} else {
    Write-Host "`nAction is '$($next.action)' - no reply needed" -ForegroundColor Green
}

# Cleanup
Write-Host "`n[8] ars stop $Session" -ForegroundColor Yellow
& $run ars stop $Session

Write-Host "`n=== Done ===`n" -ForegroundColor Cyan
