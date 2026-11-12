#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $SubscriptionId = '51274a9c-b1ad-4d34-8ffe-0ba858eee00f',

    [ValidateNotNullOrEmpty()]
    [string] $ResourceGroupName = 'rutzsco-enterprise-skills',

    [ValidatePattern('^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$')]
    [ValidateLength(2, 32)]
    [string] $AppName = 'enterprise-skills-private',

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $ContainerImage,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $ModelDeployment,

    [string] $Location,
    [string] $FoundryName,
    [string] $FoundryProjectName,
    [string] $VnetAddressPrefix,
    [string] $AppSubnetPrefix,
    [string] $EndpointsSubnetPrefix,
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
    foreach ($namespace in @('Microsoft.App', 'Microsoft.OperationalInsights', 'Microsoft.CognitiveServices', 'Microsoft.Network', 'Microsoft.Storage', 'Microsoft.DocumentDB', 'Microsoft.ManagedIdentity')) {
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
    "modelDeployment=$ModelDeployment"
)
if ($Location) {
    $parameters += "location=$Location"
}
foreach ($option in @('FoundryName', 'FoundryProjectName', 'VnetAddressPrefix', 'AppSubnetPrefix', 'EndpointsSubnetPrefix')) {
    $value = Get-Variable -Name $option -ValueOnly
    if ($value) {
        $parameterName = $option.Substring(0, 1).ToLowerInvariant() + $option.Substring(1)
        $parameters += "$parameterName=$value"
    }
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
