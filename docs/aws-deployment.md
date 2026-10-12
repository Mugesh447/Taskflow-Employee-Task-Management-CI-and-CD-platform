# TaskFlow AWS deployment

This deployment provisions TaskFlow as an AWS ECS Fargate service behind an HTTPS Application Load Balancer. PostgreSQL runs in private subnets, uploads use encrypted shared EFS storage, and AWS Backup creates daily recovery points. GitHub Actions publishes immutable images to ECR and deploys them using short-lived GitHub OIDC credentials.

## AWS resources and controls

- A VPC spans two Availability Zones. The public load balancer redirects HTTP to HTTPS; application tasks accept inbound traffic only from that load balancer. RDS and EFS mount targets use private subnets.
- RDS PostgreSQL is encrypted, not publicly accessible, protected from accidental deletion, and retains 14 days of native point-in-time backups. AWS Secrets Manager generates and manages its administrator password.
- EFS is encrypted at rest and in transit, shared between app tasks, and restricted to NFS traffic from the app security group. Containers run as a non-root user.
- AWS Backup takes daily recovery points of tagged database and file-storage resources and retains them for 35 days. Failed backup jobs, high ECS/RDS CPU, low database storage, and load-balancer errors send CloudWatch/SNS alerts. Set `alert_email` to receive email notifications and confirm the SNS subscription.
- CloudWatch Container Insights, 30-day application/VPC-flow logs, ECR image scanning, immutable image tags, and KMS encryption provide operational and security visibility.
- GitHub Actions can assume an IAM deployment role only for the configured repository and branch. It uses OIDC; no long-lived AWS access key is stored in GitHub.

## Prerequisites

1. Install AWS CLI, Terraform 1.5+, Docker, and `psql`; authenticate locally with an AWS identity permitted to create the resources in `terraform/`.
2. Register a DNS name and request an ACM certificate for it in the same AWS region as the deployment. Complete DNS validation and wait for the certificate status to become `ISSUED`.
3. Choose the AWS region, the GitHub repository in `owner/repository` format, and (optionally) a Route 53 hosted-zone ID.
4. Review the estimated cost before applying. The ALB, RDS, Fargate, EFS, KMS, CloudWatch, and backup resources incur AWS charges. Multi-AZ RDS is optional and disabled by default.

## Provision the infrastructure once

First complete **Configure a remote Terraform state backend** below and define `$StateBucket`, `$StateRegion`, and `$LockTable`. Then, from the repository root in PowerShell:

```powershell
Set-Location terraform
terraform init `
  -backend-config="bucket=$StateBucket" `
  -backend-config="key=taskflow/production/terraform.tfstate" `
  -backend-config="region=$StateRegion" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=false" `
  -backend-config="dynamodb_table=$LockTable"
terraform fmt -check
terraform validate
terraform plan `
  -var="app_domain=taskflow.example.com" `
  -var="certificate_arn=arn:aws:acm:ap-south-1:123456789012:certificate/replace-me" `
  -var="github_repository=owner/repository" `
  -var="desired_count=0"
```

Review the plan, then apply it with the same variables:

```powershell
terraform apply `
  -var="app_domain=taskflow.example.com" `
  -var="certificate_arn=arn:aws:acm:ap-south-1:123456789012:certificate/replace-me" `
  -var="github_repository=owner/repository" `
  -var="desired_count=0"
```

If Route 53 hosts the domain, add `-var="hosted_zone_id=Z1234567890"` to both commands. Otherwise, create an A/ALIAS or CNAME record at your DNS provider pointing `app_domain` to `terraform output -raw load_balancer_dns_name`.

The first apply creates the ECR repository, HTTPS endpoint, database, encrypted upload storage, empty Secrets Manager entries, backup plan, alarms, and GitHub deploy role, without starting tasks before their image and credentials exist. `terraform output` lists the created resource names and the secret ARNs required below.

Terraform state contains sensitive infrastructure metadata. This stack requires the protected, encrypted, versioned remote backend described below; do not keep production state in a local file or Git.

### Configure a remote Terraform state backend

The application stack intentionally does not create its own state bucket: the backend must exist before Terraform can initialize this stack. Bootstrap a dedicated S3 bucket and DynamoDB lock table once, preferably in a separate security/bootstrap stack. Enable S3 versioning, block all public access, enable default SSE-KMS encryption, and restrict bucket/table access to the infrastructure operators. Keep the state bucket in a region where the team can recover it independently of this application stack.

For example, create the bucket and lock table with AWS CLI after selecting the account and region. Use globally unique bucket and table names; do not put state files or generated credentials in the repository:

```powershell
$StateBucket = "replace-with-a-globally-unique-taskflow-state-bucket"
$StateRegion = "ap-south-1"
$LockTable = "taskflow-terraform-locks"
aws s3api create-bucket --bucket $StateBucket --region $StateRegion --create-bucket-configuration LocationConstraint=$StateRegion
aws s3api put-public-access-block --bucket $StateBucket --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket $StateBucket --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket $StateBucket --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'
aws dynamodb create-table --table-name $LockTable --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST --region $StateRegion
```

For regions that require a location constraint, the command above is appropriate outside `us-east-1`; omit `--create-bucket-configuration` in `us-east-1`. If organizational policy requires a customer-managed KMS key, specify its ARN in the bucket encryption configuration and grant the Terraform operator only the required encrypt/decrypt permissions.

After creating the backend, run Terraform from `terraform/` and supply backend configuration interactively or through a protected local config file outside Git:

```powershell
terraform init `
  -backend-config="bucket=$StateBucket" `
  -backend-config="key=taskflow/production/terraform.tfstate" `
  -backend-config="region=$StateRegion" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=false" `
  -backend-config="dynamodb_table=$LockTable"
```

The stack declares a partial S3 backend in `terraform/main.tf`; bucket, key, region, and lock-table details are deliberately supplied locally and are not committed. For an existing local state, review the bucket/table security and take a protected copy of the local state outside the repository before running the `terraform init` command above with `-migrate-state`; approve the migration prompt only after confirming the destination key. Do not delete the local copy until `terraform state list` and a read-only `terraform plan` succeed from the remote backend. For a new deployment with no local state, use the `terraform init` command above without `-migrate-state`.

## Prepare database and application secrets

Generate and store the Flask signing key and least-privilege database password. These commands keep generated values in local PowerShell variables rather than source files:

```powershell
$AppSecretArn = terraform output -raw application_secret_arn
$AppSecret = aws secretsmanager get-random-password --password-length 48 --exclude-punctuation --query RandomPassword --output text
aws secretsmanager put-secret-value --secret-id $AppSecretArn --secret-string $AppSecret

$DatabaseSecretArn = terraform output -raw application_database_secret_arn
$DatabasePassword = aws secretsmanager get-random-password --password-length 40 --exclude-punctuation --query RandomPassword --output text
$DatabaseSecret = @{ username = "taskflow_app"; password = $DatabasePassword } | ConvertTo-Json -Compress
aws secretsmanager put-secret-value --secret-id $DatabaseSecretArn --secret-string $DatabaseSecret
```

Create the restricted database role using the RDS-generated administrator secret. This is a one-time setup; the runtime ECS task receives only the `taskflow_app` credentials, not the database administrator password.

```powershell
$MasterSecretArn = terraform output -raw database_master_secret_arn
$MasterSecret = aws secretsmanager get-secret-value --secret-id $MasterSecretArn --query SecretString --output text | ConvertFrom-Json
$TaskflowDatabaseSecret = $DatabaseSecret | ConvertFrom-Json
$env:PGPASSWORD = $MasterSecret.password
$env:PGSSLMODE = "require"
$env:TASKFLOW_APP_DB_USER = $TaskflowDatabaseSecret.username
$env:TASKFLOW_APP_DB_PASSWORD = $TaskflowDatabaseSecret.password
psql -h (terraform output -raw database_endpoint) `
  -U $MasterSecret.username `
  -d taskflow `
  -f scripts/create_taskflow_db_user.sql
Remove-Item Env:PGPASSWORD
Remove-Item Env:PGSSLMODE
Remove-Item Env:TASKFLOW_APP_DB_USER
Remove-Item Env:TASKFLOW_APP_DB_PASSWORD
Remove-Variable MasterSecret, TaskflowDatabaseSecret, DatabasePassword, DatabaseSecret, AppSecret
```

If `psql` exits unsuccessfully, stop and resolve the reported connection or SQL error before deploying. Do not print or commit the secret values. If the Route 53/DNS certificate validation or RDS provisioning is still propagating, wait for it to complete before continuing.

## Enable GitHub Actions deployment

In the GitHub repository, add these **Actions variables** from the corresponding `terraform output` values:

| Variable | Terraform output / value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | `github_deploy_role_arn` |
| `AWS_REGION` | `aws_region` |
| `ECR_REPOSITORY` | `taskflow` |
| `ECS_CLUSTER_NAME` | `ecs_cluster_name` |
| `ECS_SERVICE_NAME` | `ecs_service_name` |
| `ECS_TASK_DEFINITION_FAMILY` | `ecs_task_definition_family` |
| `TASKFLOW_PUBLIC_URL` | `https://` followed by the configured `app_domain` |

`AWS_REGION` falls back to `ap-south-1` when the repository variable is unset, matching the Terraform default. If the infrastructure was provisioned in another region, set `AWS_REGION` to the `aws_region` Terraform output before deploying.

Merge or push a commit to `main`. The workflow runs Python tests and Terraform checks on pull requests; on `main`, it builds and pushes an immutable commit-SHA image to ECR (scan-on-push is enabled), records the currently running ECS task definition, deploys the new revision, ensures two tasks are running, and checks the public database-backed `/api/health` endpoint. If ECS stability or the health check fails after deployment begins, the workflow updates ECS back to the previously running task definition and waits for that service to stabilize. Check the failed GitHub Actions run and CloudWatch alarms before retrying; automatic rollback restores the application revision, not database schema or data changes. Open `terraform output -raw application_url` after the deployment succeeds.

For an operator-triggered recovery, first inspect the service events and active task definitions. Select a specific revision known to have passed its health check; do not assume the newest revision is healthy:

```powershell
$Cluster = terraform output -raw ecs_cluster_name
$Service = terraform output -raw ecs_service_name
aws ecs describe-services --cluster $Cluster --services $Service --query "services[0].{TaskDefinition:taskDefinition,Desired:desiredCount,Running:runningCount,Events:events[0:5]}" --output table
aws ecs list-task-definitions --family-prefix taskflow --status ACTIVE --sort DESC --output table
$KnownGoodTaskDefinition = "arn:aws:ecs:ap-south-1:123456789012:task-definition/taskflow:REPLACE_WITH_VERIFIED_REVISION"
aws ecs update-service --cluster $Cluster --service $Service --task-definition $KnownGoodTaskDefinition
aws ecs wait services-stable --cluster $Cluster --services $Service
Invoke-RestMethod -Uri "$(terraform output -raw application_url)/api/health" -TimeoutSec 10
```

Replace the example task-definition ARN with the verified revision and confirm its account/region before running the update. If a release contains a database migration or data change, application rollback alone may be unsafe; use the reviewed migration rollback or the non-production-tested database recovery plan before directing production traffic.

## Monitoring, backups, and recovery

- Application logs: CloudWatch Logs group `/ecs/taskflow`.
- Network flow logs: CloudWatch Logs group `/aws/vpc/flowlogs/taskflow`.
- Metrics and alarms: ECS CPU, RDS CPU/storage, ALB 5xx counts, application warning-log volume, and ALB target p90 response time; optional email notifications go to the SNS subscription. Set `alert_email` during Terraform deployment and confirm the SNS subscription email.
- Backups: daily AWS Backup recovery points at 05:00 UTC, retained for 35 days, covering tagged RDS and EFS resources; RDS also has 14-day point-in-time recovery.
- Run a restore drill in a non-production environment before relying on backups. Never restore over production as part of a drill.
- Use **CloudWatch → Alarms** to check alarm state and **CloudWatch → Log groups → `/ecs/taskflow`** to investigate warning/error context. A warning-volume alarm is a signal to investigate, not proof of a service outage; correlate it with the ECS service events, ALB target health, and `/api/health`.

### Non-production restore drill

1. Confirm an authorized operator is in the intended AWS account and region. Record the recovery-point creation time and the test window; use isolated non-production database/network resources and access-controlled test storage.
2. List completed recovery points and select the intended database or file-system recovery point. For example:

   ```powershell
   $Vault = terraform output -raw backup_vault_name
   aws backup list-recovery-points-by-backup-vault --backup-vault-name $Vault --by-resource-type RDS --output table
   aws backup list-recovery-points-by-backup-vault --backup-vault-name $Vault --by-resource-type EFS --output table
   ```

3. In the AWS Backup console, open **Protected resources** or **Backup vaults**, select the recovery point, choose **Restore**, and review every destination setting before starting the job. Give the restored database a unique non-production DB identifier and place it in the isolated non-production DB subnet group/security group. Restore EFS to a new file system; do not select or mount the production file system as the restore destination.
4. Track each restore job in **AWS Backup → Jobs → Restore jobs**. Wait for `COMPLETED`; if it fails, inspect the restore-job status message and correct the IAM role, subnet/security group, KMS access, or capacity issue before retrying.
5. For PostgreSQL, connect only from the approved non-production network with an authorized test identity and verify expected schema, representative workspace/task/employee records, and row counts. For EFS, mount the restored file system read-only where possible and verify representative attachment paths and checksums. Do not copy production secrets or expose restored production data to general test users.
6. Record the selected recovery point, restore job IDs, completion time, observed recovery point age (RPO), elapsed restore time (RTO), and verification results in the team's operations record. After evidence is captured and approval is obtained, delete only the specifically named temporary restored resources using their normal AWS deletion workflow; retain the recovery point.

Use the Terraform output `backup_vault_name` to locate the vault. AWS Backup restore jobs require a role with the service-linked backup restore permissions and appropriate KMS decrypt/grant permissions. If the test VPC, subnet group, or security group does not exist, stop and provision it through the approved non-production infrastructure process rather than targeting production resources.

## Operational notes

- The public endpoint is HTTPS-only. The ACM certificate must cover `app_domain`; HTTP requests are redirected to HTTPS.
- The ECS tasks have public IPs to pull ECR images without a NAT gateway, but their security group rejects inbound traffic from the internet. Database and EFS mount targets remain private.
- Change `database_multi_az` to `true` for higher database availability, and adjust the instance/task sizes for the expected workload.
- RDS deletion protection, load-balancer deletion protection, and the final-snapshot requirement are enabled. Plan a deliberate maintenance window and retained backup before removing production resources.
- AWS provisioning is intentionally not performed by this repository workflow; the initial Terraform apply requires a trusted AWS operator. Subsequent application releases use GitHub OIDC.
