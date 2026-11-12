# Azure infrastructure

Deploys into the existing resource group
`/subscriptions/51274a9c-b1ad-4d34-8ffe-0ba858eee00f/resourceGroups/rutzsco-enterprise-skills`.
No Docker build, registry creation, or application source is included.

## Resources

- Azure Container Apps Consumption environment and HTTPS container app, with a system-assigned identity.
- Log Analytics workspace with 30-day retention.
- Azure AI Foundry resource (`AIServices`, S0) and project, each with a managed identity.
- Cognitive Services User assignment on Foundry for the container app identity.

The app scales from zero to one replica with 0.25 vCPU and 0.5 GiB memory.
Both services have public endpoints; Foundry requires Microsoft Entra authentication
and has API keys disabled. The placeholder app is publicly accessible without
authentication. Add application authentication before exposing sensitive functionality.
No AI models are deployed; model choice and quota are separate from this infrastructure.
Compute usage, logs, and subsequent AI usage can incur Azure charges.

## Deploy

Requires PowerShell 7+, Azure CLI with Bicep, and `az login` access to the target
subscription. The deployer needs resource creation permissions and permission to
create role assignments (for example, Owner). Provider registration is performed
when needed. The script does not change the default Azure CLI subscription and
does not require the Container Apps CLI extension.

From the repository root:

```powershell
# Preview changes without deploying.
.\infra\deploy.ps1 -Preview

# Provision infrastructure with Microsoft's public placeholder image on port 80.
.\infra\deploy.ps1

# Deploy the other agent's public Docker Hub image when it is available.
.\infra\deploy.ps1 -ContainerImage 'docker.io/OWNER/IMAGE:VERSION' -TargetPort 8080
```

Use the actual image's listening port, not necessarily `8080`. The container must
listen on `0.0.0.0`. Public images need no registry credentials; private Docker Hub
repositories are not configured by this template. Prefer immutable version tags
or digests. Reusing an unchanged mutable tag might not create a new revision.

Resource names are stable across deployments. Keep `AppName` and the target
resource group unchanged when replacing the image. Deployments use incremental
mode and do not delete unrelated resources. Re-running without `-ContainerImage`
will restore the placeholder, so always supply the intended image on updates.

Resources default to the resource group's region. Use `-Location` to override the
Container Apps/logging region and `-FoundryLocation` to independently override the
Foundry region if regional availability or subscription restrictions require it.
Keep regions stable after provisioning; existing resources cannot generally move
between regions through a redeployment.

## Outputs and application integration

The deployment prints the app URL, managed identity principal ID, Foundry resource
and project IDs, and Foundry project endpoint. The app receives the endpoint as
`AZURE_AI_PROJECT_ENDPOINT`. Application code can use `DefaultAzureCredential`
to authenticate with the container app's managed identity; no keys are stored in
the template or app configuration. RBAC changes can take several minutes to propagate.
The placeholder does not call Foundry.

To inspect the deployment later without the Container Apps CLI extension:

```powershell
az deployment group show `
  --subscription 51274a9c-b1ad-4d34-8ffe-0ba858eee00f `
  --resource-group rutzsco-enterprise-skills `
  --name enterprise-skills-infra `
  --query properties.outputs
```
