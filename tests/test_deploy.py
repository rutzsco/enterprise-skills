import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


POWERSHELL = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell 7 is required for deployment-script tests.")
DEPLOY_SCRIPT = Path(__file__).resolve().parents[1] / "infra" / "deploy.ps1"
MOCK_AZ = r"""
$ErrorActionPreference = 'Stop'
$options = Get-Content -LiteralPath $env:DEPLOY_TEST_OPTIONS -Raw | ConvertFrom-Json -AsHashtable
function global:az {
    $cli = @($args)
    $global:LASTEXITCODE = 0
    Add-Content -LiteralPath $env:DEPLOY_TEST_CALLS -Value 'az'
    if ($cli[0] -eq 'deployment') {
        $index = [Array]::IndexOf($cli, '--parameters')
        if ($index -lt 0) { throw 'No deployment parameters were supplied.' }
        $parameterPath = $cli[$index + 1].Substring(1)
        Get-Content -LiteralPath $parameterPath -Raw |
            Set-Content -LiteralPath $env:DEPLOY_TEST_OUTPUT
    } elseif ($cli[0] -eq 'network') {
        $env:DEPLOY_TEST_NETWORKS
    } elseif ($cli[0] -eq 'provider') {
        'Registered'
    }
}
& $env:DEPLOY_TEST_SCRIPT @options
"""


@pytest.fixture
def deploy(tmp_path):
    def run(existing_subnets=None, **options):
        options_path = tmp_path / "options.json"
        output_path = tmp_path / "parameters.json"
        calls_path = tmp_path / "calls.txt"
        options_path.write_text(json.dumps({"Preview": True, **options}), encoding="utf-8")
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", MOCK_AZ],
            env={
                **os.environ,
                "DEPLOY_TEST_SCRIPT": str(DEPLOY_SCRIPT),
                "DEPLOY_TEST_OPTIONS": str(options_path),
                "DEPLOY_TEST_OUTPUT": str(output_path),
                "DEPLOY_TEST_CALLS": str(calls_path),
                "DEPLOY_TEST_NETWORKS": json.dumps([{"subnets": existing_subnets}] if existing_subnets else []),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        parameters = json.loads(output_path.read_text(encoding="utf-8-sig"))["parameters"] if output_path.exists() else None
        return result, parameters, calls_path.exists()

    return run


def test_public_ingress_requires_an_allowlist_before_azure_calls(deploy):
    result, parameters, called = deploy(PublicIngress=True)
    assert result.returncode != 0
    assert "Public ingress requires AllowedIngressIpRanges" in result.stderr
    assert parameters is None and not called


@pytest.mark.parametrize("ip_range", ["0.0.0.0/0", "203.0.113.12/33", "300.0.0.1/32", "::1/128"])
def test_public_ingress_rejects_invalid_or_unrestricted_ranges(deploy, ip_range):
    result, parameters, called = deploy(PublicIngress=True, AllowedIngressIpRanges=[ip_range])
    assert result.returncode != 0
    assert "Invalid ingress range" in result.stderr
    assert parameters is None and not called


def test_private_ingress_does_not_silently_ignore_an_allowlist(deploy):
    result, parameters, called = deploy(AllowedIngressIpRanges=["203.0.113.12/32"])
    assert result.returncode != 0
    assert "AllowedIngressIpRanges requires PublicIngress" in result.stderr
    assert parameters is None and not called


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, {"mode": "Private"}),
        (
            {
                "PublicIngress": True,
                "AllowedIngressIpRanges": ["203.0.113.12/32", "198.51.100.0/24", "203.0.113.12/32"],
            },
            {"mode": "Public", "allowedIpRanges": ["203.0.113.12/32", "198.51.100.0/24"]},
        ),
    ],
)
def test_deploy_constructs_explicit_network_mode(deploy, options, expected):
    result, parameters, called = deploy(**options)
    assert result.returncode == 0, result.stderr
    assert called and parameters["ingress"]["value"] == expected


def test_public_ingress_preserves_private_registry_secret_reference(deploy):
    result, parameters, _ = deploy(
        PublicIngress=True,
        AllowedIngressIpRanges=["203.0.113.12/32"],
        RegistryUsername="package-reader",
        RegistryTokenVaultId="/subscriptions/test/resourceGroups/test/providers/Microsoft.KeyVault/vaults/test",
        RegistryTokenSecretName="registry-pull",
    )
    assert result.returncode == 0, result.stderr
    assert parameters["registryPassword"] == {
        "reference": {
            "keyVault": {"id": "/subscriptions/test/resourceGroups/test/providers/Microsoft.KeyVault/vaults/test"},
            "secretName": "registry-pull",
        }
    }


def test_redeployment_preserves_existing_subnet_security_groups(deploy):
    result, parameters, _ = deploy(
        PublicIngress=True,
        AllowedIngressIpRanges=["203.0.113.12/32"],
        existing_subnets=[
            {"name": "apps", "networkSecurityGroup": {"id": "/test/nsg/apps"}},
            {"name": "endpoints", "networkSecurityGroup": {"id": "/test/nsg/endpoints"}},
        ],
    )
    assert result.returncode == 0, result.stderr
    assert parameters["appNetworkSecurityGroupId"]["value"] == "/test/nsg/apps"
    assert parameters["endpointsNetworkSecurityGroupId"]["value"] == "/test/nsg/endpoints"


def test_replacement_environment_does_not_change_data_resource_names(deploy):
    result, parameters, _ = deploy(
        PublicIngress=True,
        AllowedIngressIpRanges=["203.0.113.12/32"],
        AppName="existing-app",
        EnvironmentName="replacement-vnet-env",
    )
    assert result.returncode == 0, result.stderr
    assert parameters["appName"]["value"] == "existing-app"
    assert parameters["environmentName"]["value"] == "replacement-vnet-env"
