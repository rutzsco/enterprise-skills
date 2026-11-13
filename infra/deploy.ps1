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
    [string] $EnvironmentName,

    [ValidateNotNullOrEmpty()]
    [string] $ContainerImage = 'ghcr.io/rutzsco/enterprise-skills:sha-23fecf5',

    [string] $ModelDeployment = '',
    [switch] $InfrastructureOnly,
    [switch] $PublicIngress,
    [string[]] $AllowedIngressIpRanges = @(),
    [string] $RegistryUsername,
    [string] $RegistryTokenVaultId,
    [string] $RegistryTokenSecretName,

    [string] $Location,
    [string] $FoundryName,
    [string] $FoundryProjectName,
    [string] $FoundryLocation,
    [string] $VnetAddressPrefix,
    [string] $AppSubnetPrefix,
    [string] $EndpointsSubnetPrefix,
    [string] $AppNetworkSecurityGroupId,
    [string] $EndpointsNetworkSecurityGroupId,
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
$registryArgumentCount = @(
    @($RegistryUsername, $RegistryTokenVaultId, $RegistryTokenSecretName) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
).Count
if (-not $InfrastructureOnly -and $registryArgumentCount -notin @(0, 3)) {
    throw 'For private GHCR images, supply RegistryUsername, RegistryTokenVaultId and RegistryTokenSecretName together. Omit all three for anonymous public-image pulls. Never pass the token value in source or command-line arguments.'
}
if ($PublicIngress -and $AllowedIngressIpRanges.Count -eq 0) {
    throw 'Public ingress requires AllowedIngressIpRanges. Use an approved client IPv4 /32 or network CIDR; this app has no user authentication.'
}
if (-not $PublicIngress -and $AllowedIngressIpRanges.Count -gt 0) {
    throw 'AllowedIngressIpRanges requires PublicIngress. Omit both options for internal-only ingress.'
}
foreach ($range in $AllowedIngressIpRanges) {
    $address = $null
    if ($range -notmatch '^([0-9]{1,3}(?:\.[0-9]{1,3}){3})/([1-9]|[12][0-9]|3[0-2])$' -or
        -not [System.Net.IPAddress]::TryParse($Matches[1], [ref] $address) -or
        $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        $address.ToString() -cne $Matches[1]) {
        throw "Invalid ingress range '$range'. Supply canonical IPv4 CIDRs with prefixes 1-32; unrestricted /0 access is not allowed."
    }
}

# Every command targets the requested subscription without changing the user's CLI default.
$null = Invoke-AzureCli -Arguments @(
    'group', 'show', '--subscription', $SubscriptionId,
    '--name', $ResourceGroupName, '--output', 'none'
)

$existingNetworks = Invoke-AzureCli -Arguments @(
    'network', 'vnet', 'list', '--subscription', $SubscriptionId,
    '--resource-group', $ResourceGroupName,
    '--query', "[?name=='${AppName}-vnet']", '--output', 'json'
) | ConvertFrom-Json
foreach ($network in $existingNetworks) {
    foreach ($subnet in $network.subnets) {
        if ($subnet.name -eq 'apps' -and -not $PSBoundParameters.ContainsKey('AppNetworkSecurityGroupId')) {
            $AppNetworkSecurityGroupId = $subnet.networkSecurityGroup.id
        }
        if ($subnet.name -eq 'endpoints' -and -not $PSBoundParameters.ContainsKey('EndpointsNetworkSecurityGroupId')) {
            $EndpointsNetworkSecurityGroupId = $subnet.networkSecurityGroup.id
        }
    }
}

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

$parameters = @{
    appName = @{ value = $AppName }
    containerImage = @{ value = $ContainerImage }
    modelDeployment = @{ value = $ModelDeployment }
    deployApplication = @{ value = -not $InfrastructureOnly.IsPresent }
    ingress = @{ value = if ($PublicIngress) {
        @{ mode = 'Public'; allowedIpRanges = @($AllowedIngressIpRanges | Select-Object -Unique) }
    } else {
        @{ mode = 'Private' }
    } }
}
if (-not $InfrastructureOnly -and $registryArgumentCount -eq 3) {
    $parameters.registryUsername = @{ value = $RegistryUsername }
    $parameters.registryPassword = @{
        reference = @{
            keyVault = @{ id = $RegistryTokenVaultId }
            secretName = $RegistryTokenSecretName
        }
    }
}
if ($Location) {
    $parameters.location = @{ value = $Location }
}
foreach ($option in @('EnvironmentName', 'FoundryName', 'FoundryProjectName', 'FoundryLocation', 'VnetAddressPrefix', 'AppSubnetPrefix', 'EndpointsSubnetPrefix', 'AppNetworkSecurityGroupId', 'EndpointsNetworkSecurityGroupId')) {
    $value = Get-Variable -Name $option -ValueOnly
    if ($value) {
        $parameterName = $option.Substring(0, 1).ToLowerInvariant() + $option.Substring(1)
        $parameters[$parameterName] = @{ value = $value }
    }
}

$action = if ($Preview) { 'what-if' } else { 'create' }
$arguments = @(
    'deployment', 'group', $action,
    '--subscription', $SubscriptionId,
    '--resource-group', $ResourceGroupName,
    '--name', "$AppName-infra",
    '--mode', 'Incremental',
    '--template-file', (Join-Path $PSScriptRoot 'main.bicep')
)

if (-not $Preview) {
    $arguments += @('--query', 'properties.outputs', '--output', 'json')
}

$parameterFile = Join-Path ([System.IO.Path]::GetTempPath()) ("enterprise-memory-" + [guid]::NewGuid().ToString('N') + '.parameters.json')
try {
    # This file contains only public settings and a Key Vault reference, never the secret value.
    @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'; contentVersion = '1.0.0.0'; parameters = $parameters } |
        ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    Invoke-AzureCli -Arguments ($arguments + @('--parameters', "@$parameterFile"))
}
finally {
    Remove-Item -LiteralPath $parameterFile -ErrorAction SilentlyContinue
}
