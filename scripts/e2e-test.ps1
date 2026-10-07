<#
.SYNOPSIS
  End-to-end test of the complete Docker Compose environment (phase 5).

.DESCRIPTION
  Boots the full stack (postgres + redis + web + worker), then drives it over
  HTTP exactly as a browser would:
    1. every container reports healthy and /health says both deps are ok
    2. register + login + vote -> message shown, item lands on vote_queue
    3. the worker drains the queue and the vote reaches Postgres
    4. /results reflects the vote once the cache expires
    5. a second vote is rejected (one vote per user)
    6. /admin totals match
    7. web + worker logs are the structured JSON we ship
  Finally it tears the containers down.

  All count assertions are DELTAS against a baseline read at startup, so the
  script passes against a database volume that already holds earlier data.
  The postgres_data volume is never removed.

  The service-free suites (app/tests, worker/tests) do NOT need Docker; this
  script is the complement that proves the containers wire together.

.EXAMPLE
  ./scripts/e2e-test.ps1
  ./scripts/e2e-test.ps1 -KeepStack      # leave the stack running afterwards
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://localhost:5000',
    # Leave the stack up for manual poking instead of `docker compose down`.
    [switch]$KeepStack,
    # How long to wait for the stack to report healthy.
    [int]$ReadyTimeoutSec = 180,
    # How long to wait for the worker to drain a queued vote.
    [int]$WorkerTimeoutSec = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$CookieJar = Join-Path ([IO.Path]::GetTempPath()) 'voting-e2e-cookies.txt'
$Stamp = Get-Date -Format 'yyyyMMddHHmmss'
$Username = "e2e-$Stamp"
$Password = 'e2e-password-1!'

$script:Checks = 0
$script:Failures = 0

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert([bool]$Condition, [string]$Message) {
    $script:Checks++
    if ($Condition) {
        Write-Host "  [PASS] $Message" -ForegroundColor Green
    } else {
        $script:Failures++
        Write-Host "  [FAIL] $Message" -ForegroundColor Red
    }
}

# One HTTP round-trip. GETs follow redirects with -L. POSTs never do: curl 8.13
# re-issues the redirect target as POST *without a body*, so Flask would see an
# empty form (bad login, choice=null votes). Instead we read the 3xx Location
# and issue the follow-up GET ourselves, exactly like a browser. The POST's own
# status is kept in StatusCode and the final page in Body.
function Invoke-Web {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [hashtable]$Form,
        [switch]$NoRedirect,
        [switch]$NoCookies
    )
    $Body = [IO.Path]::GetTempFileName()
    $CurlArgs = @('-sS', '-o', $Body, '-w', '%{http_code}')
    if (-not $NoCookies) { $CurlArgs += @('-b', $CookieJar, '-c', $CookieJar) }
    if ($null -eq $Form) {
        if (-not $NoRedirect) { $CurlArgs += '-L' }
    } else {
        $Headers = [IO.Path]::GetTempFileName()
        $CurlArgs += @('-D', $Headers)
        $Pairs = foreach ($Key in $Form.Keys) { "$Key=$([uri]::EscapeDataString([string]$Form[$Key]))" }
        $CurlArgs += @('-X', 'POST', '--data', ($Pairs -join '&'))
        $Code = & curl.exe @CurlArgs $Uri 2>$null
        if ($LASTEXITCODE -ne 0) {
            Remove-Item $Body, $Headers -ErrorAction SilentlyContinue
            throw "curl failed talking to $Uri (exit $LASTEXITCODE)"
        }
        $Content = Get-Content -Raw -ErrorAction SilentlyContinue $Body
        $Location = ''
        foreach ($Line in Get-Content $Headers) {
            if ($Line -like 'Location:*') { $Location = ($Line -replace '^Location:\s*', '').Trim() }
        }
        Remove-Item $Body, $Headers -ErrorAction SilentlyContinue
        if ($Location -notmatch '^https?://') { $Location = "$BaseUrl$Location" }
        $Follow = if ($Location -and -not $NoRedirect) { Invoke-Web -Uri $Location } else { $null }
        return [pscustomobject]@{
            StatusCode = [int]$Code
            Location   = $Location
            Body       = if ($Follow) { $Follow.Body } else { [string]$Content }
        }
    }
    $Code = & curl.exe @CurlArgs $Uri 2>$null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $Body -ErrorAction SilentlyContinue
        throw "curl failed talking to $Uri (exit $LASTEXITCODE)"
    }
    $Content = Get-Content -Raw -ErrorAction SilentlyContinue $Body
    Remove-Item $Body -ErrorAction SilentlyContinue
    [pscustomobject]@{
        StatusCode = [int]$Code
        Location   = ''
        Body       = [string]$Content
    }
}

# Poll until the script block returns $true, or give up after the timeout.
function Wait-Until {
    param(
        [Parameter(Mandatory)][scriptblock]$Condition,
        [int]$TimeoutSec = 30,
        [int]$IntervalSec = 2,
        [string]$Because = 'condition'
    )
    $Deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $Deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Seconds $IntervalSec
    }
    Write-Host "  [WARN] timed out after ${TimeoutSec}s waiting for $Because" -ForegroundColor Yellow
    return $false
}

# NOTE: every docker flag (-d, -T, -U, ...) must arrive inside the array.
# PowerShell binds bare `-d` on a function call as a *parameter name* and
# silently drops it, which turns `up -d` into an attached `up` that never
# returns. Always call these as  Invoke-Compose -ComposeArgs @('up','-d') .
function Invoke-Compose {
    param([Parameter(Mandatory, Position = 0)][string[]]$ComposeArgs)
    Push-Location $Root
    try {
        & docker compose @ComposeArgs
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose $($ComposeArgs -join ' ') failed (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-ComposeCapture {
    param([Parameter(Mandatory, Position = 0)][string[]]$ComposeArgs)
    Push-Location $Root
    try {
        & docker compose @ComposeArgs 2>$null
        if ($LASTEXITCODE -ne 0) { return @() }
    } finally {
        Pop-Location
    }
}

# Read a single scalar out of Postgres, e.g. Get-SqlScalar 'SELECT count(*) FROM vote'.
function Get-SqlScalar {
    param([Parameter(Mandatory)][string]$Sql)
    $Line = Invoke-ComposeCapture -ComposeArgs @('exec', '-T', 'db', 'psql', '-U', $script:DbUser, '-d', $script:DbName, '-tAc', $Sql) |
        Select-Object -Last 1
    return "$Line".Trim()
}

function Test-AllHealthy {
    $Lines = @(Invoke-ComposeCapture -ComposeArgs @('ps', '--format', '{{.Service}} {{.Status}}'))
    foreach ($Service in 'db', 'redis', 'web', 'worker') {
        $Line = $Lines | Where-Object { $_ -like "$Service *" }
        if ($null -eq $Line -or $Line -notmatch 'healthy') { return $false }
    }
    return $true
}

function Cleanup {
    if ($KeepStack) {
        Write-Host ''
        Write-Host 'Stack left running (-KeepStack). Stop it with: docker compose down' -ForegroundColor Yellow
        return
    }
    Write-Host ''
    Write-Host '==> Tearing the stack down (postgres_data volume is kept)' -ForegroundColor Cyan
    Invoke-Compose down
}

Remove-Item $CookieJar -ErrorAction SilentlyContinue

try {
    Write-Step 'Starting the full stack (docker compose up -d --build)'
    Invoke-Compose -ComposeArgs @('up', '-d', '--build')

    Write-Step "Waiting up to ${ReadyTimeoutSec}s for all four containers to be healthy"
    $Healthy = Wait-Until -TimeoutSec $ReadyTimeoutSec -Because 'all containers healthy' -Condition { Test-AllHealthy }
    Assert $Healthy 'db, redis, web and worker all report healthy'

    if (-not $Healthy) {
        Write-Step 'Diagnostics'
        Push-Location $Root
        try {
            & docker compose ps
            Write-Host ''
            Write-Host '-- last 40 web log lines --' -ForegroundColor Yellow
            & docker compose logs --no-color --tail=40 web
        } finally {
            Pop-Location
        }
        throw 'stack never became healthy'
    }

    # Credentials come from the container, so a custom .env is honoured.
    $script:DbUser = "$(Invoke-ComposeCapture -ComposeArgs @('exec', '-T', 'db', 'printenv', 'POSTGRES_USER') | Select-Object -Last 1)".Trim()
    $script:DbName = "$(Invoke-ComposeCapture -ComposeArgs @('exec', '-T', 'db', 'printenv', 'POSTGRES_DB') | Select-Object -Last 1)".Trim()

    Write-Step 'Baseline counts (assertions below are deltas against these)'
    # public.user, never "user": PowerShell's native-argv quoting drops the
    # embedded double quotes, and bare `FROM user` counts PG's one-row
    # current_user composite instead of the table.
    $BaseUsers = [int](Get-SqlScalar 'SELECT count(*) FROM public.user')
    $BaseVotes = [int](Get-SqlScalar 'SELECT count(*) FROM vote')
    $BaseA = [int](Get-SqlScalar "SELECT count(*) FROM vote WHERE choice = 'A'")
    $BaseB = [int](Get-SqlScalar "SELECT count(*) FROM vote WHERE choice = 'B'")
    Write-Host "  users=$BaseUsers votes=$BaseVotes (A=$BaseA, B=$BaseB)"

    Write-Step 'GET /health reports both dependencies'
    $Health = Invoke-Web -Uri "$BaseUrl/health"
    Assert ($Health.StatusCode -eq 200) "status code 200 (got $($Health.StatusCode))"
    Assert ($Health.Body -match '"status"\s*:\s*"healthy"') 'body says status=healthy'
    Assert ($Health.Body -match '"database"\s*:\s*"ok"') 'database check is ok'
    Assert ($Health.Body -match '"redis"\s*:\s*"ok"') 'redis check is ok'

    Write-Step "Register a fresh user ($Username)"
    $Register = Invoke-Web -Uri "$BaseUrl/register" -Form @{ username = $Username; password = $Password }
    Assert ($Register.StatusCode -eq 302 -and $Register.Location -like '*/login') "register redirects to /login (got $($Register.StatusCode) -> $($Register.Location))"
    Assert ($Register.Body -match 'Registration successful') 'registration succeeded'

    Write-Step 'Log in'
    $Login = Invoke-Web -Uri "$BaseUrl/login" -Form @{ username = $Username; password = $Password }
    Assert ($Login.StatusCode -eq 302 -and $Login.Location -like '*/vote') "login redirects to /vote (got $($Login.StatusCode) -> $($Login.Location))"
    Assert ($Login.Body -match "Hello, $Username!") "session established (Hello, $Username! shown)"

    Write-Step 'GET /vote renders the seeded poll'
    $VotePage = Invoke-Web -Uri "$BaseUrl/vote"
    Assert ($VotePage.StatusCode -eq 200) "status code 200 (got $($VotePage.StatusCode))"
    Assert ($VotePage.Body -match 'Which framework is better\?') 'seeded poll question present'

    Write-Step 'Cast a vote (choice A) — queued for the worker, never written directly'
    $Cast = Invoke-Web -Uri "$BaseUrl/vote" -Form @{ choice = 'A' }
    Assert ($Cast.StatusCode -eq 302 -and $Cast.Location -like '*/results') "vote redirects to /results (got $($Cast.StatusCode) -> $($Cast.Location))"
    Assert ($Cast.Body -match 'Vote submitted') 'vote accepted and queued'

    $ExpectA = $BaseA + 1
    $ExpectB = $BaseB
    $ExpectVotes = $BaseVotes + 1

    Write-Step 'Worker drains vote_queue and inserts into Postgres'
    $Drained = Wait-Until -TimeoutSec $WorkerTimeoutSec -Because 'the worker to persist the vote' -Condition {
        $Results = Invoke-Web -Uri "$BaseUrl/results"
        $Results.Body -match "Flask: $ExpectA votes" -and $Results.Body -match "Node.js: $ExpectB votes"
    }
    Assert $Drained "/results shows Flask: $ExpectA / Node.js: $ExpectB (worker insert + cache refresh)"

    Write-Step 'Queue is empty and the row is in the database'
    $QueueLen = (Invoke-ComposeCapture -ComposeArgs @('exec', '-T', 'redis', 'redis-cli', 'llen', 'vote_queue') | Select-Object -Last 1)
    Assert ("$QueueLen".Trim() -eq '0') "vote_queue length is 0 (got '$QueueLen')"

    $Rows = Get-SqlScalar 'SELECT count(*) FROM vote'
    Assert ($Rows -eq "$ExpectVotes") "vote table holds baseline+1 rows (got $Rows, want $ExpectVotes)"

    Write-Step 'A second vote must be rejected'
    $Second = Invoke-Web -Uri "$BaseUrl/vote" -Form @{ choice = 'B' }
    Assert ($Second.StatusCode -eq 302) "second vote rejected with a redirect (got $($Second.StatusCode))"
    Assert ($Second.Body -match 'already voted') 'second vote rejected with "already voted"'

    $Rows = Get-SqlScalar 'SELECT count(*) FROM vote'
    Assert ($Rows -eq "$ExpectVotes") "still baseline+1 rows after the rejected vote (got $Rows)"

    Write-Step 'Admin dashboard totals'
    $Admin = Invoke-Web -Uri "$BaseUrl/admin"
    Assert ($Admin.StatusCode -eq 200) "status code 200 (got $($Admin.StatusCode))"
    Assert ($Admin.Body -match "Total Registered Users: $($BaseUsers + 1)") 'admin counts the new registration'
    Assert ($Admin.Body -match "Total Votes Cast: $ExpectVotes") 'admin counts the processed vote'

    Write-Step 'Logs are structured JSON on both services'
    $WorkerLogs = (Invoke-ComposeCapture -ComposeArgs @('logs', '--no-color', 'worker')) -join "`n"
    $WebLogs = (Invoke-ComposeCapture -ComposeArgs @('logs', '--no-color', 'web')) -join "`n"
    Assert ($WorkerLogs -match 'vote saved to database') 'worker logged "vote saved to database"'
    Assert ($WorkerLogs -match '"logger"\s*:\s*"voting.worker"') 'worker log lines are structured JSON'
    Assert ($WebLogs -match 'vote queued') 'web logged the queue hand-off'
    Assert ($WebLogs -match '"logger"\s*:\s*"voting.web"') 'web log lines are structured JSON'
} finally {
    Cleanup
    Remove-Item $CookieJar -ErrorAction SilentlyContinue
}

Write-Host ''
if ($script:Failures -gt 0) {
    Write-Host "E2E FAILED: $script:Failures of $script:Checks checks failed" -ForegroundColor Red
    exit 1
}
Write-Host "E2E PASSED: all $script:Checks checks passed" -ForegroundColor Green
exit 0
