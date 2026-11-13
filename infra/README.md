# VNet-connected Azure MVP

This template deploys Enterprise Memory in a VNet-connected Container Apps environment, with private Azure Blob Storage, Cosmos DB for NoSQL, and Foundry connectivity. App ingress is internal by default, with an explicit IP-restricted public HTTPS option. The default image is `ghcr.io/rutzsco/enterprise-skills:sha-23fecf5`. It reuses an existing Foundry account/project and **does not deploy a model**.

## Boundary and resources

- VNet-integrated ACA environment with a dedicated delegated subnet. Internal mode exposes HTTPS only to permitted VNet clients; `-PublicIngress` creates an external environment and requires approved client IPv4 CIDRs. The app always uses HTTPS on port 8000 behind ACA ingress.
- Blob and Cosmos DB have `publicNetworkAccess: Disabled`, private endpoints and VNet-linked private DNS. Blob anonymous/shared-key access and Cosmos key authentication are disabled.
- Foundry public network access is disabled. Its account private endpoint integrates the `services.ai`, `cognitiveservices`, and `openai` private DNS zones.
- Blob packages are create-only in application code, with storage versioning and soft deletion enabled. This is not a WORM retention-policy guarantee.
- Cosmos metadata uses a single `/workspace` partition for transactional release publication. The app never depends on ephemeral container storage for cloud data.
- User-assigned managed identity: container-scoped Storage Blob Data Contributor, container-scoped Cosmos data contributor, and project-scoped Cognitive Services Data Contributor (Preview) for Foundry agent/data operations. The available Azure AI Developer role does not include `AIServices/agents` actions; the selected data role has no management-plane permissions and is limited to this project.
- Log Analytics, one application process, and zero-to-one replica scaling. Managed identities use Entra internally; **there is no end-user sign-in**, user-role authorization, or skill ACL enforcement.

All permitted app users can review/publish. All permitted MCP callers can read the published catalog. Restrict network membership or public source-IP access accordingly. Everyone behind an allowed public egress IP shares this trust; IP filtering is not user authentication. Private endpoints alone do not prove compliance with MCAPS or any other policy.

## Prerequisites

PowerShell 7+, Azure CLI/Bicep, an approved subscription/resource group, resource and role-assignment permissions, and an accessible versioned application image. Live AI additionally requires an existing function-calling model deployment; leaving `-ModelDeployment` empty keeps live AI explicitly unconfigured while library/MCP remain available.

Defaults target the existing `rutzsco-enterprise-skills` resource group and legacy Foundry names. The app defaults to `enterprise-skills-private`; its name is a stable resource identifier, not a guarantee of ingress mode. Do not change `-AppName` merely to change ingress: it also changes the data/identity resource names. The template does not delete or move the old `enterprise-skills` placeholder app.

To retain the legacy placeholder without public exposure, disable its ingress explicitly:

```powershell
az containerapp ingress disable --subscription 51274a9c-b1ad-4d34-8ffe-0ba858eee00f `
  --resource-group rutzsco-enterprise-skills --name enterprise-skills
```

For an existing real workload rather than the placeholder, coordinate its cutover before disabling ingress. Incremental deployment of the new template alone does not close an old public route.

The app's Foundry endpoint variable is `FOUNDRY_PROJECT_ENDPOINT`, its model variable is `FOUNDRY_MODEL_DEPLOYMENT`, and the image listens on port **8000**. There is no placeholder-image or port-80 fallback.
The template removes Cosmos's explicit default `:443` port from its endpoint URL, preserving HTTPS and the same account hostname in the format accepted by the published image.

The deployment disables public Foundry access, including for existing callers. Confirm all required service callers have private routing and DNS before applying. Review Foundry regional availability against the actual applicable MCAPS policies. Model deployment, network peering/VPN, corporate DNS forwarding, a private registry mirror, and private-runner access are not provisioned here. GHCR is an external registry accessed over HTTPS; private service endpoints do not make registry traffic private. Public image visibility is independent of the app's ingress mode and data-service boundaries.

## Preview and deploy

Build/publish the application image through the repository's existing container workflow or your approved process. The default GHCR package is public and is pulled anonymously when registry parameters are omitted. Repository visibility and package visibility are separate settings.

For private GHCR images, supply all three registry parameters together. Store an approved, read-only `read:packages` credential in Key Vault and supply its reference, not its value. The vault must support ARM template secret references and the deployer must have permission to use them. ARM resolves the secure parameter directly; the script never reads the token or writes it to a local parameter file. ACA stores it as a registry secret. Use your organization's rotation process.

From the repository root:

```powershell
az login

# Deploy the public sha-23fecf5 image with anonymous pulls and private app/data networking.
.\infra\deploy.ps1 -Preview
.\infra\deploy.ps1

# Public HTTPS from an approved client IP; all data services remain private.
# An existing internal environment must be replaced first, as described below.
.\infra\deploy.ps1 -EnvironmentName 'enterprise-skills-vnet-env' `
  -PublicIngress -AllowedIngressIpRanges '<your-public-IPv4>/32' -Preview
.\infra\deploy.ps1 -EnvironmentName 'enterprise-skills-vnet-env' `
  -PublicIngress -AllowedIngressIpRanges '<your-public-IPv4>/32'

# Optionally provision only private network/data services.
# This deliberately does NOT create/update the application or claim an image rollout.
.\infra\deploy.ps1 -InfrastructureOnly -Preview
.\infra\deploy.ps1 -InfrastructureOnly

# For a private GHCR image, use an approved Key Vault reference instead.
.\infra\deploy.ps1 -Preview `
  -ContainerImage 'ghcr.io/<owner>/<image>:<tag>' `
  -RegistryUsername '<credential-owner>' `
  -RegistryTokenVaultId '/subscriptions/<id>/resourceGroups/<group>/providers/Microsoft.KeyVault/vaults/<vault>' `
  -RegistryTokenSecretName '<ghcr-read-packages-secret>' `
  -ModelDeployment '<existing-function-calling-deployment>'

# After network/policy review, use the same parameters without -Preview.
```

`-PublicIngress` requires `-AllowedIngressIpRanges`, an array of canonical IPv4 CIDRs (a single client uses `/32`). Missing, malformed, IPv6 and unrestricted `/0` rules are rejected before Azure operations. Omit both options for internal-only ingress. For direct Bicep deployment, use `ingress={mode:'Public',allowedIpRanges:[...]}`; its discriminated parameter type requires a nonempty allowlist in public mode.

Optional overrides: `-ContainerImage`, `-SubscriptionId`, `-ResourceGroupName`, `-AppName`, `-EnvironmentName`, `-Location`, `-FoundryName`, `-FoundryProjectName`, `-FoundryLocation`, `-VnetAddressPrefix`, `-AppSubnetPrefix`, `-EndpointsSubnetPrefix`, `-AppNetworkSecurityGroupId`, and `-EndpointsNetworkSecurityGroupId`. The script preserves existing subnet NSG attachments unless explicitly overridden; direct Bicep deployments must supply those IDs themselves. Confirm nonoverlapping CIDRs and approved regions before applying. The defaults create a new VNet rather than guessing which corporate network to modify.

Every CLI operation targets the requested subscription without changing the user's CLI default. Provider registrations occur only on real deployment. Role propagation may delay initial startup. Incremental deployments do not remove unrelated resources.

## Replacing an existing environment

ACA cannot change an environment between internal and external networking or attach a VNet to an existing non-VNet environment. `deploy.ps1` does not delete resources automatically. For a deliberate replacement of this demo:

1. Record the current app/environment configuration, generated app DNS zone, and published catalog versions/digests. Review the new deployment preview and allowlist before taking the app offline.
2. Delete only the application and its old managed environment, then wait for the environment to release its subnet service-association link. Azure can retain a `ScheduledForDelete` record after accepting deletion; do not reuse that environment name while the record remains. Preserve the VNet/subnets, identity, roles, logs, Blob, Cosmos, Foundry and all data-service private DNS zones.
3. Redeploy with the same `-AppName`, image and data parameters, adding `-EnvironmentName 'enterprise-skills-vnet-env' -PublicIngress -AllowedIngressIpRanges '<your-public-IPv4>/32'`. The separate environment name avoids changing data resources while Azure completes old-record cleanup. ACA generates a new public HTTPS domain. Host/origin settings are updated from that domain.
4. Verify the app, REST/package/MCP reads and unchanged release digests before removing the obsolete generated app-domain private DNS zone. The public mode does not create that private app DNS module. Never delete the Blob/Cosmos/Foundry private DNS zones.

This replacement interrupts the app, resets process-local chat sessions and changes its URL, but it does not intentionally delete or recreate the persistent registry or packages. On later redeployments, retain the environment-name and public-mode arguments; omitting them selects the original name/internal mode and cannot move an existing app or convert an external environment back in place.

## Reaching the app

The outputs include the app URL, VNet ID, `containerAppDomain`, `ingressMode`, `allowedIngressIpRanges`, account names, Foundry endpoint, managed environment/identity IDs, requested image, and `applicationDeployed`. The legacy `privateAppDomain` output remains an alias for the generated domain in either mode. In infrastructure-only mode, `applicationDeployed` is false and the app URL is empty.

Internal mode requires approved private routing and DNS (for example VPN/peering). Public mode uses ACA's generated HTTPS URL without a VPN or gateway, but only from allowed source IPs; update the allowlist if your client egress IP changes. A public runner is not allowed unless explicitly listed. The app itself reaches Blob, Cosmos and Foundry through their private endpoints and VNet-linked DNS in either mode. Never enable public data-service access to make a demonstration work.

Use the source addresses seen by Azure, not just an IP-echo website. VPNs, proxies, and split tunneling can use different egress addresses for Azure-bound traffic, and a client can rotate across several addresses. Validate from the actual browser as well as automation: a successful CLI request does not prove browser access. Replace stale client entries instead of accumulating old addresses. Allow only the approved observed `/32`s or a stable approved network CIDR, then check real app requests; do not broaden access to diagnose intermittent `403` responses.

## Required live validation

1. Compile Bicep and inspect the deployment preview/policy results before applying.
2. Resolve Blob/Cosmos/Foundry names privately inside the app VNet and connect using managed identity. Verify app REST/package/MCP reads and persistent data after replacing the app revision or environment.
3. Inspect resource properties and attempt access from outside the permitted network or public IP allowlist: app access must fail, all data services must deny public access, and anonymous/key access must remain disabled.
4. Verify actual Foundry agent registration, conversation invocation, and the selected model with the assigned project permissions. An environment variable or role assignment alone is not proof of a working run.
5. Use the separate consumer to initialize MCP, read metadata and approved packages, compare real isolated answers before/after publication, and confirm reviewed rollback changes subsequent active reads without agent redeployment.
6. Retain the actual policy/network/run evidence. Unit tests, a successful Bicep build, and private-endpoint declarations are not live-deployment or compliance evidence.

Deployment, compute, data storage, logs, private endpoints, and inference can incur Azure charges.

Deployment-script checks use mocked Azure commands and do not create resources: `python -m pytest -q tests\test_deploy.py` (requires pytest and PowerShell 7).
