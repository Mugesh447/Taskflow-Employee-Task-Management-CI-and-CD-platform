# TaskFlow

TaskFlow is an employee task manager with workspace accounts, task assignments, workload tracking, and scheduled overdue reminders. The Flask API serves the frontend and uses SQLite by default.

## Run locally with Docker

1. Copy `.env.example` to `.env` and replace the sample `TASKFLOW_SECRET_KEY` with a unique value. Keep `.env` private; changing the key invalidates existing login sessions.
2. Build and start the app:

	```powershell
	docker compose up --build -d
	```

3. Open [http://localhost:5001](http://localhost:5001), create an account, and add tasks.
4. Stop the app with `docker compose down`. The `taskflow_data` volume keeps the SQLite database between restarts. To intentionally remove all local data, use `docker compose down -v`.

Port `5001` is used on the host so TaskFlow does not conflict with other local applications. The container listens on `5000`.

## Seed optional demo data

To populate a local database with sample employees and tasks, set `TASKFLOW_DEMO_USERNAME` and `TASKFLOW_DEMO_PASSWORD` in your shell (minimum 3 and 8 characters, respectively), then run `python seed_demo_data.py` from the `backend` directory. The script has no default account or password; keep the values private and use only a local or non-production database.

## Features

- Choose between creating a new Admin-owned workspace and joining as an Employee with an Admin-issued invitation; public sign-up cannot self-assign Employee access, and the server validates invitation roles.
- Recover forgotten passwords using a 30-minute, single-use reset link sent to the account recovery email; reset tokens are stored hashed.
- Create, rename, complete/reopen, search, filter, and delete tasks.
- Organize users, employees, tasks, and pipelines inside isolated workspaces; existing accounts are migrated together into the legacy TaskFlow Team workspace.
- Invite employees with a seven-day link to create a workspace account, then assign tasks through employee IDs.
- Review each employee's active, overdue, and due-soon task workload.
- Generate persisted overdue reminders in the background every five minutes by default; the database deduplicates reminders across application workers.
- Give Admins workspace-wide task, employee, account-access, pipeline, monitoring, and backup controls. Employees see only their own assigned or created tasks and can update task status without changing task details or deleting work.
- Manage employees with Admin/Manager-only create, edit, invite, and removal actions; linked accounts must be deactivated rather than deleted. A workspace must retain at least one Admin.
- Admins and Managers can add an employee from the Employees dashboard; TaskFlow then generates a seven-day invitation link that can be copied and shared securely. Existing unlinked employees can be invited from their row.
- Receive persisted notifications for task, employee, and pipeline events.
- Trigger Jenkins jobs through `JENKINS_URL` and view pipeline run history.
- Discuss tasks with comments, activity history, analytics, and due-date calendar views.
- Receive push-style dashboard updates through Server-Sent Events.
- Send optional email alerts through SMTP configuration.
- Keep task data private to its workspace. Unowned legacy tasks are assigned to the first registered account and its workspace during migration.
- Export workspace-scoped JSON backups without exposing other workspaces' data.
- Validate account and task input on the server.
- Store SQLite data in a Docker volume.
- Deploy to AWS ECS Fargate with HTTPS, private PostgreSQL, shared encrypted upload storage, and least-privilege runtime database credentials.
- Provision AWS infrastructure, encrypted daily backups, CloudWatch Container Insights/alarms for service health, response latency, and application warnings, and GitHub Actions deployments using short-lived OIDC credentials with health verification and task-definition rollback.
- Run non-production AWS Backup restore drills for RDS and EFS, and use an encrypted/versioned S3 Terraform state backend with locking for shared infrastructure operations.

## Test and build

With Python 3.12+ installed:

```powershell
python -m pip install -r backend/requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q backend
docker compose config
terraform -chdir=terraform fmt -check
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

GitHub Actions runs tests and Terraform validation on pull requests. Pushes to `main` build an immutable ECR image and deploy it to ECS using GitHub OIDC. See [docs/aws-deployment.md](docs/aws-deployment.md) for the one-time AWS setup, secret provisioning, and operations guide.

## Kubernetes

Build or load the `taskflow:latest` image into the target cluster, then create the session secret without committing it to source control:

```powershell
kubectl create secret generic taskflow-secret --from-literal=secret-key="replace-with-a-long-random-value"
kubectl apply -f k8s/configmap.yaml -f k8s/persistentvolumeclaim.yaml -f k8s/deployment.yaml -f k8s/service.yaml
kubectl port-forward service/taskflow 8080:80
```

Open [http://localhost:8080](http://localhost:8080). The cluster needs a storage class that can provision the included 1 GiB persistent volume claim. Configure HTTPS before enabling secure-only cookies.

For an image registry, replace `taskflow:latest` in `k8s/deployment.yaml` with the pushed image tag before applying it. The included [k8s/secret.example.yaml](k8s/secret.example.yaml) documents the required secret shape; do not apply it with its placeholder value. AWS ECS deployment is documented separately in [docs/aws-deployment.md](docs/aws-deployment.md).

## Configuration

- `TASKFLOW_SECRET_KEY`: secret used to sign sessions. Set a strong random value for every deployment.
- `TASKFLOW_DATABASE_URI`: optional SQLAlchemy database URL; defaults to SQLite in Flask's instance directory.
- `TASKFLOW_COOKIE_SECURE`: set to `true` only when requests use HTTPS.
- `JENKINS_URL`: optional Jenkins base URL used by the Run pipeline action.
- `JENKINS_JOB`: optional Jenkins job name; defaults to `taskflow`.
- `TASKFLOW_SMTP_HOST`, `TASKFLOW_SMTP_PORT`, `TASKFLOW_SMTP_USER`, `TASKFLOW_SMTP_PASSWORD`: SMTP configuration for password reset links and optional alerts. Password recovery requires SMTP; set `TASKFLOW_SMTP_STARTTLS=false` only for a trusted local mail relay that does not support STARTTLS.
- `TASKFLOW_SMTP_FROM`: optional sender address for password reset email; defaults to `TASKFLOW_SMTP_USER` or `taskflow@localhost`.
- `TASKFLOW_PUBLIC_URL`: public TaskFlow base URL used to build password-reset and employee-invitation links. Docker Compose defaults to `http://localhost:5001`; set the real HTTPS origin for deployments outside localhost. Terraform sets the AWS ECS URL from `app_domain`. Kubernetes reads SMTP host/from/TLS and public URL from `taskflow-config`, and SMTP username/password from `taskflow-secret`.
- `TASKFLOW_ALERT_EMAIL`: optional recipient for task, employee, and pipeline alerts.
- `TASKFLOW_START_REMINDER_SCHEDULER`: enable the in-process overdue reminder worker; Docker Compose and Kubernetes enable it by default.
- `TASKFLOW_REMINDER_INTERVAL_SECONDS`: reminder check interval in seconds; defaults to `300` and cannot be set below `30`.
- `REDIS_URL`: optional Redis connection string for other background work.

To run the production support services locally, use `docker compose --profile production up --build -d` and set `TASKFLOW_DATABASE_URI` to `postgresql+psycopg://taskflow:change-me@postgres:5432/taskflow`. Use a reverse proxy for HTTPS and set `TASKFLOW_COOKIE_SECURE=true` after TLS is active.

The Terraform configuration provisions the AWS environment described in [docs/aws-deployment.md](docs/aws-deployment.md). AWS provisioning is not performed automatically by local development; review expected costs, bootstrap a protected Terraform state backend, and follow the deployment guide before applying infrastructure.
