targetScope = 'resourceGroup'

@description('New private deployment name. Do not reuse the existing public app name: ACA environment networking is immutable.')
@minLength(2)
@maxLength(32)
param appName string = 'enterprise-skills-private'
param location string = resourceGroup().location

@description('Published, accessible application image. Prefer an immutable digest. No placeholder default.')
param containerImage string
@description('Existing function-calling deployment in the Foundry project.')
@minLength(1)
param modelDeployment string
param foundryName string = 'enterprise-skills-ai-${uniqueString(resourceGroup().id)}'
param foundryProjectName string = 'enterprise-skills-project'
param vnetAddressPrefix string = '10.42.0.0/16'
param appSubnetPrefix string = '10.42.0.0/23'
param endpointsSubnetPrefix string = '10.42.2.0/27'

var suffix = uniqueString(resourceGroup().id, appName)
var projectEndpoint = 'https://${foundryName}.services.ai.azure.com/api/projects/${foundryProjectName}'
var databaseName = 'enterprise-memory'
var containerName = 'registry'
var tags = { application: appName, managedBy: 'bicep' }

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${appName}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [vnetAddressPrefix] }
    subnets: [
      {
        name: 'apps'
        properties: {
          addressPrefix: appSubnetPrefix
          delegations: [
            {
              name: 'container-apps'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
      {
        name: 'endpoints'
        properties: {
          addressPrefix: endpointsSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${appName}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${appName}-env'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: vnet.properties.subnets[0].id
      internal: true
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

module appDns 'private-app-dns.bicep' = {
  name: '${appName}-dns'
  params: {
    domain: environment.properties.defaultDomain
    address: environment.properties.staticIp
    vnetId: vnet.id
    linkName: '${appName}-link'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: 'em${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'None' }
  }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}
resource packages 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'skills'
  properties: { publicAccess: 'None' }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' = {
  name: '${appName}-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0 } ]
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    isVirtualNetworkFilterEnabled: true
    networkAclBypass: 'None'
  }
}
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-04-15' = {
  parent: cosmos
  name: databaseName
  properties: { resource: { id: databaseName } }
}
resource registry 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-04-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: { paths: ['/workspace'], kind: 'Hash', version: 2 }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [ { path: '/workspace/?' } ]
        excludedPaths: [ { path: '/*' } ]
      }
    }
  }
}

var privateServices = [
  { name: 'blob', resourceId: storage.id, zone: 'privatelink.blob.${az.environment().suffixes.storage}', group: 'blob' }
  { name: 'cosmos', resourceId: cosmos.id, zone: 'privatelink.documents.azure.com', group: 'Sql' }
]
resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for service in privateServices: {
  name: service.zone
  location: 'global'
}]
resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (service, i) in privateServices: {
  parent: zones[i]
  name: '${appName}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}]
resource endpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for service in privateServices: {
  name: '${appName}-${service.name}-pe'
  location: location
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: service.name
        properties: { privateLinkServiceId: service.resourceId, groupIds: [service.group] }
      }
    ]
  }
}]
resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (service, i) in privateServices: {
  parent: endpoints[i]
  name: 'default'
  properties: { privateDnsZoneConfigs: [ { name: service.name, properties: { privateDnsZoneId: zones[i].id } } ] }
}]

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = { name: foundryName }
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${appName}-identity'
  location: location
}
resource blobAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(packages.id, identity.id, 'blob')
  scope: packages
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource cosmosAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'registry-data')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: '${cosmos.id}/dbs/${databaseName}/colls/${containerName}'
  }
}
resource foundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, identity.id, 'foundry')
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '64702f94-c441-49e6-a78b-ef80e0188fee')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [blobAccess, cosmosAccess, foundryAccess, registry, zoneGroups, appDns]
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      // External within the INTERNAL environment, reachable from the VNet, not the public internet.
      ingress: { external: true, allowInsecure: false, targetPort: 8000, transport: 'auto' }
    }
    template: {
      containers: [
        {
          name: 'app'
          image: containerImage
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
            { name: 'FOUNDRY_MODEL_DEPLOYMENT', value: modelDeployment }
            { name: 'FOUNDRY_AGENT_PREFIX', value: appName }
            { name: 'MEMORY_STORAGE_BACKEND', value: 'azure' }
            { name: 'MEMORY_COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'MEMORY_COSMOS_DATABASE', value: databaseName }
            { name: 'MEMORY_COSMOS_CONTAINER', value: containerName }
            { name: 'MEMORY_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
            { name: 'MEMORY_ALLOWED_HOSTS', value: '${appName}.${environment.properties.defaultDomain},127.0.0.1,localhost' }
            { name: 'MEMORY_ALLOWED_ORIGINS', value: 'https://${appName}.${environment.properties.defaultDomain}' }
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/health', port: 8000 }
              periodSeconds: 10
              failureThreshold: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 8000 }
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output containerAppUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output containerAppPrincipalId string = identity.properties.principalId
output foundryProjectEndpoint string = projectEndpoint
output privateVnetId string = vnet.id
output storageAccountName string = storage.name
output cosmosAccountName string = cosmos.name
output privateAppDomain string = environment.properties.defaultDomain
