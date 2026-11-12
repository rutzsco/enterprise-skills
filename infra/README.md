# Private Azure MVP

This template deploys the actual Enterprise Memory image behind private ingress, with private Azure Blob Storage and Cosmos DB for NoSQL. It reuses an existing Foundry account/project and **does not deploy a model**.

## Boundary and resources

- VNet-integrated **internal** ACA environment; HTTPS app ingress is available to approved VNet clients, not the public internet. `external: true` on the app means external to the app within this internal environment, not internet-facing.
- Blob and Cosmos DB have `publicNetworkAccess: Disabled`, private endpoints and VNet-linked private DNS. Blob anonymous/shared-key access and Cosmos key authentication are disabled.
- Blob packages are create-only in application code, with storage versioning and soft deletion enabled. This is not a WORM retention-policy guarantee.
- Cosmos metadata uses a single `/workspace` partition for transactional release publication. The app never depends on ephemeral container storage for cloud data.
- User-assigned managed identity: container-scoped Storage Blob Data Contributor, container-scoped Cosmos data contributor, and project-scoped Azure AI Developer for real registered-agent operations.
- Log Analytics, one application process, and zero-to-one replica scaling. Managed identities use Entra internally; **there is no end-user sign-in**, user-role authorization, or skill ACL enforcement.

All permitted app users can review/publish. All permitted MCP callers can read the published catalog. Restrict network membership accordingly. Private endpoints alone do not prove compliance with MCAPS or any other policy.

## Prerequisites

PowerShell 7+, Azure CLI/Bicep, an approved subscription/resource group, resource and role-assignment permissions, an accessible versioned application image, and a function-calling model deployed in the existing Foundry project.

Defaults target the existing `rutzsco-enterprise-skills` resource group and legacy Foundry names. The **new app defaults to `enterprise-skills-private`**: an existing public ACA environment cannot be converted in place to the proposed VNet topology. The template does not delete or move the existing `enterprise-skills` public app. Do not point that old app at sensitive data; retirement of old public resources is a separate explicit operation.

The app's Foundry endpoint variable is `FOUNDRY_PROJECT_ENDPOINT`, its model variable is `FOUNDRY_MODEL_DEPLOYMENT`, and the image listens on port **8000**. There is no placeholder-image or port-80 fallback.

The existing Foundry network posture is not changed. Review Foundry egress/private-network requirements and regional availability against the actual applicable MCAPS policies before deployment. Model deployment, network peering/VPN, corporate DNS forwarding, private image-registry connectivity, and private-runner access are not provisioned here.

## Preview and deploy

Build/publish the application image through the repository's existing container workflow or your approved process. Use a public-readable image or extend registry access with the approved private-registry configuration; this template does not silently store registry credentials.

From the repository root:

```powershell
az login

# Supply a real image and existing model deployment; preview does not create resources.
.\infra\deploy.ps1 -Preview `
  -ContainerImage 'ghcr.io/rutzsco/enterprise-skills@sha256:<published-digest>' `
  -ModelDeployment '<existing-function-calling-deployment>'

# After network/policy review, use the same parameters without -Preview.
```

Optional overrides: `-SubscriptionId`, `-ResourceGroupName`, `-AppName`, `-Location`, `-FoundryName`, `-FoundryProjectName`, `-VnetAddressPrefix`, `-AppSubnetPrefix`, and `-EndpointsSubnetPrefix`. Confirm nonoverlapping CIDRs and approved regions before applying. The defaults create a new VNet rather than guessing which corporate network to modify.

Every CLI operation targets the requested subscription without changing the user's CLI default. Provider registrations occur only on real deployment. Role propagation may delay initial startup. Incremental deployments do not remove unrelated resources.

## Reaching the private app

The outputs include the app URL, VNet ID, private app domain, account names, Foundry endpoint, and managed-identity principal. To use the browser or a separate MCP consumer, connect through an approved network path (for example, existing VPN/peering with correct private DNS forwarding). An ordinary public browser or public GitHub-hosted runner cannot reach these endpoints.

ACA's generated internal domain is mapped to the internal load-balancer address in a private DNS zone; Blob and Cosmos private endpoint zones are linked to the VNet. An independently hosted consumer needs both private routing and resolution, not merely the app URL. Never enable public storage or app access to make a demonstration work.

## Required live validation

1. Compile Bicep and inspect the deployment preview/policy results before applying.
2. From an allowed private-network runner, resolve app/Blob/Cosmos names to private addresses and connect using managed identity. Verify persistent data after replacing the app revision.
3. Inspect resource properties and attempt access from outside the permitted network: app/data access must fail, both data services must deny public access, and anonymous/key access must remain disabled.
4. Verify actual Foundry agent registration, conversation invocation, and the selected model with the assigned project permissions. An environment variable or role assignment alone is not proof of a working run.
5. Use the separate consumer to initialize MCP, read metadata and approved packages, compare real isolated answers before/after publication, and confirm reviewed rollback changes subsequent active reads without agent redeployment.
6. Retain the actual policy/network/run evidence. Unit tests, a successful Bicep build, and private-endpoint declarations are not live-deployment or compliance evidence.

Deployment, compute, data storage, logs, private endpoints, and inference can incur Azure charges.
