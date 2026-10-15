variable "resource_group_name" {
  description = "Name of the Azure resource group that contains the PostgreSQL server."
  type        = string
}

variable "location" {
  description = "Primary Azure region for the PostgreSQL server (e.g. northeurope)."
  type        = string
  default     = "northeurope"
}

variable "postgres_server_name" {
  description = "Name of the Azure Database for PostgreSQL Flexible Server."
  type        = string
}

variable "postgres_admin_login" {
  description = "Administrator login name for the PostgreSQL server."
  type        = string
  sensitive   = true
}

variable "postgres_admin_password" {
  description = "Administrator password for the PostgreSQL server."
  type        = string
  sensitive   = true
}

variable "postgres_sku_name" {
  description = "SKU name for the PostgreSQL Flexible Server (e.g. GP_Standard_D2s_v3)."
  type        = string
  default     = "GP_Standard_D2s_v3"
}

variable "postgres_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "postgres_storage_mb" {
  description = "Maximum storage in MB for the PostgreSQL server."
  type        = number
  default     = 32768
}

variable "backup_retention_days" {
  description = "Number of days to retain automated backups. Must be between 7 and 35."
  type        = number
  default     = 35

  validation {
    condition     = var.backup_retention_days >= 30 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 30 and 35 to satisfy the 30-day minimum retention policy."
  }
}
