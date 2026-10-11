# Production Deployment

## Docker Compose with PostgreSQL and Redis

Set required secrets in `.env`, then run:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production up --build -d
```

The application listens on port `5001`. PostgreSQL stores application data and Redis is available for other background work. The overdue reminder worker is enabled through `TASKFLOW_START_REMINDER_SCHEDULER=true` in the supplied Docker Compose and Kubernetes configurations; it checks every 300 seconds by default. In multi-worker deployments, a unique database key prevents duplicate reminders. Set `TASKFLOW_REMINDER_INTERVAL_SECONDS` to change the check interval (minimum 30 seconds).

## Kubernetes

1. Build and push the image named in `k8s/deployment.yaml`.
2. Create a real secret from `k8s/secret.example.yaml` with `secret-key` and `database-uri` values.
3. Apply the deployment, service, Ingress, and HPA:

```powershell
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/ingress.yaml -f k8s/hpa.yaml
kubectl rollout status deployment/taskflow
```

Replace `taskflow.example.com`, the TLS issuer, image tag, and PostgreSQL hostname before production use.

## GitHub Actions

- Every pull request runs compilation, tests, and coverage.
- Pushes to `main` publish an image to GHCR.
- Set repository variable `KUBE_DEPLOY=true` and base64-encoded `KUBE_CONFIG` to enable the Kubernetes rollout job.
