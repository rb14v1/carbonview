# Database Restore Procedure

**Application:** carbon_view_acb  
**Database engine:** Azure Database for PostgreSQL – Flexible Server  
**Last tested:** _(record the date here after each test)_

---

## Overview

Automated backups run continuously and are retained for **35 days**.  
Backups are stored in the Azure-paired region (northeurope → westeurope),
satisfying the cross-region storage requirement.

Point-in-time recovery (PITR) is available for any timestamp within the
retention window.  Full and differential backups are taken automatically by
Azure; no manual backup job is required.

---

## 1. Restore using the Azure Portal (recommended for ad-hoc recovery)

1. Open the [Azure Portal](https://portal.azure.com) and navigate to
   **Azure Database for PostgreSQL flexible servers**.
2. Select the source server (e.g. `<postgres_server_name>`).
3. Click **Restore** in the left-hand menu.
4. Choose **Point-in-time restore** and select the target date/time
   (must be within the last 35 days and at least 5 minutes in the past).
5. Enter a **new server name** for the restored instance – never overwrite
   the production server in place.
6. Confirm the region (defaults to northeurope); leave **Geo-redundant
   restore** checked when recovering from a regional failure.
7. Click **Review + create**, then **Create**.  Provisioning typically takes
   5–10 minutes.
8. After the restore completes, update the application's `POSTGRES_HOST`
   environment variable to point to the new server FQDN and restart the
   App Service.

---

## 2. Restore using the Azure CLI

```bash
# Variables – replace with actual values
SOURCE_SERVER="<postgres_server_name>"
TARGET_SERVER="${SOURCE_SERVER}-restored"
RESOURCE_GROUP="<resource_group_name>"
RESTORE_TIME="2026-10-14T12:00:00Z"   # ISO-8601, UTC

az postgres flexible-server restore \
  --resource-group "$RESOURCE_GROUP" \
  --name "$TARGET_SERVER" \
  --source-server "$SOURCE_SERVER" \
  --restore-time "$RESTORE_TIME"
```

After the command completes, retrieve the new FQDN:

```bash
az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$TARGET_SERVER" \
  --query fullyQualifiedDomainName \
  --output tsv
```

Update `POSTGRES_HOST` in the App Service application settings:

```bash
APP_SERVICE="<app_service_name>"
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_SERVICE" \
  --settings POSTGRES_HOST="<new-fqdn>"
```

Restart the App Service:

```bash
az webapp restart --resource-group "$RESOURCE_GROUP" --name "$APP_SERVICE"
```

---

## 3. Geo-redundant restore (regional failure)

When the primary region (northeurope) is unavailable, restore from the
paired-region backup:

```bash
az postgres flexible-server geo-restore \
  --resource-group "$RESOURCE_GROUP" \
  --name "${SOURCE_SERVER}-geo-restored" \
  --source-server "$SOURCE_SERVER" \
  --location westeurope
```

---

## 4. Verify the restored database

After any restore, run the Django check and migration commands against the
restored server before redirecting production traffic:

```bash
# In the backend directory
export POSTGRES_HOST="<restored-server-fqdn>"
python manage.py check --database default
python manage.py migrate --run-syncdb
```

Confirm row counts match expectations for at least one critical table, e.g.:

```bash
python manage.py shell -c "
from apps.emission.models import Emission
print('Emission rows:', Emission.objects.count())
"
```

---

## 5. Pre-go-live test checklist

- [ ] Trigger a PITR restore to a staging server.
- [ ] Run `python manage.py check --database default` against the restored
      server – no errors expected.
- [ ] Verify row counts in at least two tables.
- [ ] Confirm the application starts and the `/api/` health endpoint returns
      HTTP 200 against the restored database.
- [ ] Record the test date at the top of this document.
- [ ] Delete the temporary restored server after the test.

---

## 6. RPO / RTO targets

| Metric | Target |
|--------|--------|
| Recovery Point Objective (RPO) | ≤ 5 minutes (PITR granularity) |
| Recovery Time Objective (RTO) | ≤ 60 minutes |

---

## References

- [Azure PITR documentation](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-restore-server-portal)
- [Geo-restore documentation](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-restore-server-portal#geo-restore)
- Terraform source: [`infra/postgres_backup.tf`](../infra/postgres_backup.tf)
