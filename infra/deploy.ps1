#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $SubscriptionId = '51274a9c-b1ad-4d34-8ffe-0ba858eee00f',

    [ValidateNotNullOrEmpty()]
    [string] $ResourceGroupName = 'rutzsco-enterprise-skills',

    [ValidatePattern('^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$')]
    [ValidateLength(2, 32)]
    [string] $AppName = 'enterprise-skills',

    [ValidateNotNullOrEmpty()]
    [string] $ContainerImage = 'mcr.microsoft.com/k8se/quickstart:latest',

    [ValidateRange(1, 65535)]
    [int] $TargetPort = 80,

    [string] $Location,
    [string] $FoundryLocation,
    [switch] $Preview
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Invoke-AzureCli {
    param([Parameter(Mandatory)][string[]] $Arguments)

    $result = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed (exit code $LASTEXITCODE): az $($Arguments -join ' ')"
    }
    return $result
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required. Install it and run az login before deploying.'
}

# Every command targets the requested subscription without changing the user's CLI default.
$null = Invoke-AzureCli -Arguments @(
    'group', 'show', '--subscription', $SubscriptionId,
    '--name', $ResourceGroupName, '--output', 'none'
)

if (-not $Preview) {
    foreach ($namespace in @('Microsoft.App', 'Microsoft.OperationalInsights', 'Microsoft.CognitiveServices')) {
        $state = Invoke-AzureCli -Arguments @(
            'provider', 'show', '--subscription', $SubscriptionId,
            '--namespace', $namespace, '--query', 'registrationState', '--output', 'tsv'
        )
        if ($state -ne 'Registered') {
            Write-Host "Registering $namespace..."
            $null = Invoke-AzureCli -Arguments @(
                'provider', 'register', '--subscription', $SubscriptionId,
                '--namespace', $namespace, '--wait', '--output', 'none'
            )
        }
    }
}

$parameters = @(
    "appName=$AppName"
    "containerImage=$ContainerImage"
    "targetPort=$TargetPort"
)
if ($Location) {
    $parameters += "location=$Location"
}
if ($FoundryLocation) {
    $parameters += "foundryLocation=$FoundryLocation"
}

$action = if ($Preview) { 'what-if' } else { 'create' }
$arguments = @(
    'deployment', 'group', $action,
    '--subscription', $SubscriptionId,
    '--resource-group', $ResourceGroupName,
    '--name', "$AppName-infra",
    '--mode', 'Incremental',
    '--template-file', (Join-Path $PSScriptRoot 'main.bicep'),
    '--parameters'
) + $parameters

if (-not $Preview) {
    $arguments += @('--query', 'properties.outputs', '--output', 'json')
}

Invoke-AzureCli -Arguments $arguments
