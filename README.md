# TaskFlow

TaskFlow is a small employee task manager with account registration, private task lists, status tracking, search, and filters. The Flask API serves the frontend and uses SQLite for storage.

## Run locally with Docker

1. Copy `.env.example` to `.env` and replace the sample `TASKFLOW_SECRET_KEY` with a unique value. Keep `.env` private; changing the key invalidates existing login sessions.
2. Build and start the app:

	```powershell
	docker compose up --build -d
	```

3. Open [http://localhost:5001](http://localhost:5001), create an account, and add tasks.
4. Stop the app with `docker compose down`. The `taskflow_data` volume keeps the SQLite database between restarts. To intentionally remove all local data, use `docker compose down -v`.

Port `5001` is used on the host so TaskFlow does not conflict with other local applications. The container listens on `5000`.

## Features

- Register and sign in using password hashes and an HTTP-only, same-site session cookie.
- Create, rename, complete/reopen, search, filter, and delete tasks.
- Manage employees with authenticated CRUD APIs and assign them to tasks.
- Receive persisted notifications for task, employee, and pipeline events.
- Trigger Jenkins jobs through `JENKINS_URL` and view pipeline run history.
- Discuss tasks with comments, activity history, analytics, and due-date calendar views.
- Receive push-style dashboard updates through Server-Sent Events.
- Send optional email alerts through SMTP configuration.
- Keep task data private to its owner. Existing unowned tasks in a pre-upgrade SQLite database are assigned to the first account registered after upgrade.
- Validate account and task input on the server.
- Store SQLite data in a Docker volume.

## Test and build

With Python 3.12+ installed:

```powershell
python -m pip install -r backend/requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q backend
docker compose config
```

The Jenkins pipeline runs the Python tests and syntax compilation, then builds the Docker image. If the Jenkins job has a `KUBE_CONTEXT` environment variable, it also rolls out the image to the `taskflow` Kubernetes deployment.

## Kubernetes

Build or load the `taskflow:latest` image into the target cluster, then create the session secret without committing it to source control:

```powershell
kubectl create secret generic taskflow-secret --from-literal=secret-key="replace-with-a-long-random-value"
kubectl apply -f k8s/configmap.yaml -f k8s/persistentvolumeclaim.yaml -f k8s/deployment.yaml -f k8s/service.yaml
kubectl port-forward service/taskflow 8080:80
```

Open [http://localhost:8080](http://localhost:8080). The cluster needs a storage class that can provision the included 1 GiB persistent volume claim. Configure HTTPS before enabling secure-only cookies.

For an image registry, replace `taskflow:latest` in `k8s/deployment.yaml` with the pushed image tag before applying it. The included [k8s/secret.example.yaml](k8s/secret.example.yaml) documents the required secret shape; do not apply it with its placeholder value.

## Configuration

- `TASKFLOW_SECRET_KEY`: secret used to sign sessions. Set a strong random value for every deployment.
- `TASKFLOW_DATABASE_URI`: optional SQLAlchemy database URL; defaults to SQLite in Flask's instance directory.
- `TASKFLOW_COOKIE_SECURE`: set to `true` only when requests use HTTPS.
- `JENKINS_URL`: optional Jenkins base URL used by the Run pipeline action.
- `JENKINS_JOB`: optional Jenkins job name; defaults to `taskflow`.
- `TASKFLOW_SMTP_HOST`, `TASKFLOW_SMTP_PORT`, `TASKFLOW_SMTP_USER`, `TASKFLOW_SMTP_PASSWORD`: optional SMTP alert configuration.
- `TASKFLOW_ALERT_EMAIL`: optional recipient for task, employee, and pipeline alerts.
- `REDIS_URL`: optional Redis connection string for future background workers.

To run the production support services locally, use `docker compose --profile production up --build -d` and set `TASKFLOW_DATABASE_URI` to `postgresql+psycopg://taskflow:change-me@postgres:5432/taskflow`. Use a reverse proxy for HTTPS and set `TASKFLOW_COOKIE_SECURE=true` after TLS is active.

The Terraform directory currently contains only a project-name variable; cloud resource provisioning needs a target provider and deployment requirements before it can be completed safely.
