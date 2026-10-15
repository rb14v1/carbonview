# Carbon Footprint

Full-stack carbon footprint dashboard with a Django REST Framework backend and a Vite React frontend.

## Backend

```powershell
cd backend
python -m pip install -r requirements.txt
$env:POSTGRES_DB="carbonfootprint"
$env:POSTGRES_USER="postgres"
$env:POSTGRES_PASSWORD="postgres"
$env:POSTGRES_HOST="localhost"
$env:POSTGRES_PORT="5432"
python manage.py migrate
python manage.py runserver
```

To load demo data for the dashboard:

```powershell
python manage.py seed_demo_data
```

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Set the frontend API base URL for production builds (Vite reads this at build time):

```powershell
$env:VITE_API_BASE_URL="https://carbonview-backend-ahbwdrctb0d3h2hk.northeurope-01.azurewebsites.net"
npm.cmd run build
```

Use a full URL including `https://`.

The frontend runs at `http://localhost:5173` and proxies API calls to Django at `http://127.0.0.1:8000`.

## Azure App Service Startup

Use a startup command that points to the Django `config` package and changes directory into `backend`:

```bash
gunicorn --chdir backend config.wsgi:application
```

Using `backend.wsgi:application` is incorrect for this project structure.

## PostgreSQL Helper

If Docker is available, start a matching local database from the project root:

```powershell
docker compose up -d postgres
```

Then run the backend migrations.
