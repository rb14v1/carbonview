###############################################################################
# Azure Database for PostgreSQL – Flexible Server
#
# Backup policy (satisfies rel.backup_configured):
#   • backup_retention_days      = 35  (≥ 30-day minimum requirement)
#   • geo_redundant_backup_enabled = true
#       Backups are stored in an Azure-paired region separate from the primary
#       server (e.g. northeurope → westeurope), satisfying the cross-region
#       storage requirement.
#   • Point-in-time recovery (PITR) is enabled by default on every Flexible
#       Server and works within the backup_retention_days window.
###############################################################################

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = var.postgres_server_name
  resource_group_name = var.resource_group_name
  location            = var.location

  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password

  sku_name   = var.postgres_sku_name
  version    = var.postgres_version
  storage_mb = var.postgres_storage_mb

  # -------------------------------------------------------------------------
  # Backup configuration – rel.backup_configured
  # -------------------------------------------------------------------------
  # 35-day retention satisfies the ≥ 30-day policy requirement.
  backup_retention_days = var.backup_retention_days

  # Geo-redundant backup replicates automated backups to the Azure-paired
  # region (northeurope → westeurope), fulfilling the "separate region"
  # requirement.  Note: geo_redundant_backup_enabled cannot be changed after
  # server creation, so it must be set before go-live.
  geo_redundant_backup_enabled = true

  # Point-in-time recovery (PITR) is automatically available for the full
  # backup_retention_days window on every Flexible Server; no extra flag is
  # needed.  See docs/restore-procedure.md for step-by-step PITR instructions.

  tags = {
    backup_policy          = "35-day-geo-redundant"
    pitr_enabled           = "true"
    compliance_requirement = "rel.backup_configured"
  }
}

###############################################################################
# Outputs – useful for referencing the server in other Terraform modules or
# in the application's environment variables.
###############################################################################

output "postgres_server_fqdn" {
  description = "Fully-qualified domain name of the PostgreSQL Flexible Server."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_server_id" {
  description = "Azure resource ID of the PostgreSQL Flexible Server."
  value       = azurerm_postgresql_flexible_server.main.id
}
