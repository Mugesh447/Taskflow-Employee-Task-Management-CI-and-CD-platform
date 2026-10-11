import os
import json
import csv
import io
import hashlib
import re
import secrets
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from functools import wraps

from flask import Flask, Response, g, jsonify, request, send_from_directory, session, stream_with_context
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import URL, func, inspect, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


db = SQLAlchemy()


class Workspace(db.Model):
    __tablename__ = "workspace"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Task(db.Model):
    __tablename__ = "task"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="Pending")
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    due_date = db.Column(db.String(20), nullable=True)
    description = db.Column(db.Text, nullable=True)
    assignee = db.Column(db.String(80), nullable=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)

    def to_dict(self):
        assignee = db.session.get(Employee, self.assignee_id) if self.assignee_id else None
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "due_date": self.due_date,
            "description": self.description,
            "assignee": assignee.name if assignee else self.assignee,
            "assignee_id": self.assignee_id,
            "comment_count": TaskComment.query.filter_by(task_id=self.id).count() if self.id else 0,
            "position": self.position,
        }


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(160), nullable=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Employee")
    two_factor_enabled = db.Column(db.Boolean, nullable=False, default=False)
    two_factor_secret = db.Column(db.String(64), nullable=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)


class LoginActivity(db.Model):
    __tablename__ = "login_activity"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    success = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "success": self.success, "created_at": self.created_at.isoformat()}


class PasswordReset(db.Model):
    __tablename__ = "password_reset"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(128), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class TaskAttachment(db.Model):
    __tablename__ = "task_attachment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "url": self.url, "created_at": self.created_at.isoformat()}


class TaskComment(db.Model):
    __tablename__ = "task_comment"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def to_dict(self):
        author = db.session.get(User, self.user_id)
        return {
            "id": self.id,
            "body": self.body,
            "author": author.username if author else "Unknown",
            "created_at": self.created_at.isoformat(),
        }


class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(240), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    task_id = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)

    def to_dict(self):
        return {"id": self.id, "message": self.message, "task_id": self.task_id, "created_at": self.created_at.isoformat()}


class Employee(db.Model):
    __tablename__ = "employee"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(80), nullable=False, default="Employee")
    account_role = db.Column(db.String(20), nullable=False, default="Employee")
    status = db.Column(db.String(20), nullable=False, default="Active")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)
    linked_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, unique=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "account_role": self.account_role,
            "status": self.status,
            "account_linked": self.linked_user_id is not None,
        }


class WorkspaceInvitation(db.Model):
    __tablename__ = "workspace_invitation"

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(160), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    account_role = db.Column(db.String(20), nullable=False, default="Employee")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=True)


class Notification(db.Model):
    __tablename__ = "notification"
    __table_args__ = (db.Index("uq_notification_dedupe_key", "dedupe_key", unique=True),)

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(240), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="info")
    read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    dedupe_key = db.Column(db.String(255), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "message": self.message,
            "kind": self.kind,
            "read": self.read,
            "created_at": self.created_at.isoformat(),
        }


class PipelineRun(db.Model):
    __tablename__ = "pipeline_run"

    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(120), nullable=False)
    branch = db.Column(db.String(120), nullable=False, default="main")
    status = db.Column(db.String(20), nullable=False, default="Queued")
    build_number = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "job_name": self.job_name,
            "branch": self.branch,
            "status": self.status,
            "build_number": self.build_number,
            "started_at": self.started_at.isoformat(),
        }


def _database_uri_from_environment():
    database_variables = ("TASKFLOW_DB_HOST", "TASKFLOW_DB_USER", "TASKFLOW_DB_PASSWORD", "TASKFLOW_DB_NAME")
    configured_database_variables = [name for name in database_variables if name in os.environ]
    database_uri = os.environ.get("TASKFLOW_DATABASE_URI")
    if database_uri is not None:
        return database_uri
    if not configured_database_variables:
        return "sqlite:///taskflow.db"
    if len(configured_database_variables) != len(database_variables):
        missing_variables = sorted(set(database_variables) - set(configured_database_variables))
        raise RuntimeError(f"Missing database configuration: {', '.join(missing_variables)}")

    return URL.create(
        "postgresql+psycopg",
        username=os.environ["TASKFLOW_DB_USER"],
        password=os.environ["TASKFLOW_DB_PASSWORD"],
        host=os.environ["TASKFLOW_DB_HOST"],
        port=int(os.environ.get("TASKFLOW_DB_PORT", "5432")),
        database=os.environ["TASKFLOW_DB_NAME"],
    )


def _send_password_reset_email(recipient, reset_url):
    smtp_host = os.environ.get("TASKFLOW_SMTP_HOST")
    if not smtp_host:
        raise RuntimeError("Password reset email requires TASKFLOW_SMTP_HOST")

    username = os.environ.get("TASKFLOW_SMTP_USER")
    password = os.environ.get("TASKFLOW_SMTP_PASSWORD")
    if bool(username) != bool(password):
        raise ValueError("Both TASKFLOW_SMTP_USER and TASKFLOW_SMTP_PASSWORD must be configured")

    email = EmailMessage()
    email["Subject"] = "Reset your TaskFlow password"
    email["From"] = os.environ.get("TASKFLOW_SMTP_FROM", username or "taskflow@localhost")
    email["To"] = recipient
    email.set_content(
        "We received a request to reset your TaskFlow password.\n\n"
        f"Use this link within 30 minutes to choose a new password:\n{reset_url}\n\n"
        "If you did not request this change, you can ignore this email."
    )
    with smtplib.SMTP(smtp_host, int(os.environ.get("TASKFLOW_SMTP_PORT", "587")), timeout=10) as smtp:
        if os.environ.get("TASKFLOW_SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(email)


def create_app(test_config=None):
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.config.update(
        SECRET_KEY=os.environ.get("TASKFLOW_SECRET_KEY", "dev-only-change-this-secret"),
        SQLALCHEMY_DATABASE_URI=_database_uri_from_environment(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TASKFLOW_COOKIE_SECURE", "false").lower() == "true",
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    upload_directory = os.path.join(app.instance_path, "uploads")
    os.makedirs(upload_directory, exist_ok=True)

    db.init_app(app)
    request_metrics = {"count": 0, "errors": 0, "total_ms": 0.0}

    @app.before_request
    def start_request_timer():
        g.request_started = time.perf_counter()

    @app.after_request
    def record_request_metrics(response):
        request_metrics["count"] += 1
        request_metrics["errors"] += int(response.status_code >= 500)
        request_metrics["total_ms"] += (time.perf_counter() - getattr(g, "request_started", time.perf_counter())) * 1000
        return response

    with app.app_context():
        db.create_all()
        employee_columns = {column["name"] for column in inspect(db.engine).get_columns("employee")}
        if "account_role" not in employee_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE employee ADD COLUMN account_role VARCHAR(20) NOT NULL DEFAULT 'Employee'"
                ))
        invitation_columns = {column["name"] for column in inspect(db.engine).get_columns("workspace_invitation")}
        if "account_role" not in invitation_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE workspace_invitation ADD COLUMN account_role VARCHAR(20) NOT NULL DEFAULT 'Employee'"
                ))
        task_columns = {column["name"] for column in inspect(db.engine).get_columns("task")}
        if "user_id" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN user_id INTEGER REFERENCES user(id)"
                ))
        if "priority" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN priority VARCHAR(20) NOT NULL DEFAULT 'Medium'"
                ))
        if "due_date" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN due_date VARCHAR(20)"
                ))
        if "description" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN description TEXT"
                ))
        if "assignee" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN assignee VARCHAR(80)"
                ))
        if "position" not in task_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE task ADD COLUMN position INTEGER NOT NULL DEFAULT 0"
                ))
        user_columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
        if "email" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE user ADD COLUMN email VARCHAR(160)"))
        if "role" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE user ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'Employee'"
                ))
        if "two_factor_enabled" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE user ADD COLUMN two_factor_enabled BOOLEAN NOT NULL DEFAULT 0"
                ))
        if "two_factor_secret" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE user ADD COLUMN two_factor_secret VARCHAR(64)"
                ))

        migration_columns = {
            "user": {"workspace_id": "INTEGER REFERENCES workspace(id)"},
            "task": {
                "workspace_id": "INTEGER REFERENCES workspace(id)",
                "assignee_id": "INTEGER REFERENCES employee(id)",
            },
            "employee": {
                "workspace_id": "INTEGER REFERENCES workspace(id)",
                "linked_user_id": "INTEGER REFERENCES user(id)",
            },
            "activity_log": {"workspace_id": "INTEGER REFERENCES workspace(id)"},
            "pipeline_run": {"workspace_id": "INTEGER REFERENCES workspace(id)"},
            "notification": {"dedupe_key": "VARCHAR(255)"},
        }
        for table_name, columns_to_add in migration_columns.items():
            existing_columns = {column["name"] for column in inspect(db.engine).get_columns(table_name)}
            for column_name, column_type in columns_to_add.items():
                if column_name not in existing_columns:
                    with db.engine.begin() as connection:
                        connection.execute(text(
                            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                        ))

        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_linked_user_id ON employee(linked_user_id)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_dedupe_key ON notification(dedupe_key)"
            ))

        legacy_users = User.query.filter(User.workspace_id.is_(None)).order_by(User.id.asc()).all()
        legacy_workspace = Workspace.query.filter_by(name="TaskFlow Team").order_by(Workspace.id.asc()).first()
        if legacy_users and legacy_workspace is None:
            legacy_workspace = Workspace(name="TaskFlow Team")
            db.session.add(legacy_workspace)
            db.session.flush()
        if legacy_workspace is not None:
            for user in legacy_users:
                user.workspace_id = legacy_workspace.id

        db.session.flush()
        for employee in Employee.query.filter(Employee.workspace_id.is_(None)).all():
            owner = db.session.get(User, employee.user_id)
            if owner is not None:
                employee.workspace_id = owner.workspace_id
        for task in Task.query.filter(Task.workspace_id.is_(None), Task.user_id.isnot(None)).all():
            owner = db.session.get(User, task.user_id)
            if owner is not None:
                task.workspace_id = owner.workspace_id
        for activity in ActivityLog.query.filter(ActivityLog.workspace_id.is_(None)).all():
            owner = db.session.get(User, activity.user_id)
            if owner is not None:
                activity.workspace_id = owner.workspace_id
        for pipeline in PipelineRun.query.filter(PipelineRun.workspace_id.is_(None)).all():
            owner = db.session.get(User, pipeline.user_id)
            if owner is not None:
                pipeline.workspace_id = owner.workspace_id
        for task in Task.query.filter(Task.assignee_id.is_(None), Task.assignee.isnot(None)).all():
            matches = Employee.query.filter(
                Employee.workspace_id == task.workspace_id,
                func.lower(Employee.name) == task.assignee.strip().lower(),
            ).all()
            if len(matches) == 1:
                task.assignee_id = matches[0].id
        db.session.commit()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            if user_id is None or db.session.get(User, user_id) is None:
                session.clear()
                return jsonify({"message": "Authentication required"}), 401
            return view(*args, **kwargs)
        return wrapped

    def require_roles(*roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if db.session.get(User, session["user_id"]).role not in roles:
                    return jsonify({"message": "Insufficient permissions"}), 403
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def current_workspace_id():
        user = db.session.get(User, session["user_id"])
        return user.workspace_id

    def current_user():
        return db.session.get(User, session["user_id"])

    def recovery_email_for(user):
        if user.email:
            return user.email
        employee = Employee.query.filter_by(linked_user_id=user.id).first()
        return employee.email if employee else None

    def is_valid_email(email):
        return (
            isinstance(email, str)
            and len(email) <= 160
            and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()) is not None
        )

    def visible_tasks_query():
        query = Task.query.filter_by(workspace_id=current_workspace_id())
        user = current_user()
        if user.role == "Employee":
            employee_ids = db.session.query(Employee.id).filter_by(
                workspace_id=user.workspace_id,
                linked_user_id=user.id,
            )
            query = query.filter((Task.assignee_id.in_(employee_ids)) | (Task.user_id == user.id))
        return query

    def add_notification(message, kind="info"):
        db.session.add(Notification(
            message=message,
            kind=kind,
            user_id=session["user_id"],
        ))
        send_email_alert(message)

    def send_email_alert(message):
        smtp_host = os.environ.get("TASKFLOW_SMTP_HOST")
        recipient = os.environ.get("TASKFLOW_ALERT_EMAIL")
        if not smtp_host or not recipient:
            return
        email = EmailMessage()
        email["Subject"] = f"TaskFlow alert: {message}"
        email["From"] = os.environ.get("TASKFLOW_SMTP_USER", "taskflow@localhost")
        email["To"] = recipient
        email.set_content(message)
        try:
            with smtplib.SMTP(smtp_host, int(os.environ.get("TASKFLOW_SMTP_PORT", "587")), timeout=5) as smtp:
                smtp.starttls()
                username = os.environ.get("TASKFLOW_SMTP_USER")
                password = os.environ.get("TASKFLOW_SMTP_PASSWORD")
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(email)
        except (OSError, smtplib.SMTPException, ValueError):
            app.logger.warning("TaskFlow email alert could not be sent", exc_info=True)

    @app.route("/api/events")
    @login_required
    def events():
        user_id = session["user_id"]

        @stream_with_context
        def event_stream():
            last_notification_id = 0
            while True:
                latest = Notification.query.filter_by(user_id=user_id).order_by(Notification.id.desc()).first()
                latest_id = latest.id if latest else 0
                if latest_id != last_notification_id:
                    payload = {"type": "notification", "latest_id": latest_id, "unread": Notification.query.filter_by(user_id=user_id, read=False).count()}
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_notification_id = latest_id
                else:
                    yield ": keepalive\n\n"
                time.sleep(5)

        return Response(event_stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/employees", methods=["GET"])
    @login_required
    def get_employees():
        user = current_user()
        query = Employee.query.filter_by(workspace_id=user.workspace_id)
        if user.role == "Employee":
            query = query.filter_by(linked_user_id=user.id)
        employees = query.order_by(Employee.name.asc()).all()
        return jsonify([employee.to_dict() for employee in employees])

    @app.route("/api/employees", methods=["POST"])
    @require_roles("Admin", "Manager")
    def create_employee():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "A JSON employee is required"}), 400
        name = data.get("name")
        email = data.get("email")
        role = data.get("role", "Employee")
        account_role = data.get("account_role", "Employee")
        status = data.get("status", "Active")
        if account_role not in {"Employee", "Manager"}:
            return jsonify({"message": "Account access must be Employee or Manager"}), 400
        if account_role == "Manager" and current_user().role != "Admin":
            return jsonify({"message": "Only an Admin can create a Manager account"}), 403
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 80:
            return jsonify({"message": "Name must contain 2 to 80 characters"}), 400
        if not isinstance(email, str):
            return jsonify({"message": "A valid email is required"}), 400
        email = email.strip()
        if not email or "@" not in email or any(character.isspace() for character in email) or len(email) > 160:
            return jsonify({"message": "A valid email is required"}), 400
        if Employee.query.filter(
            Employee.workspace_id == current_workspace_id(),
            func.lower(Employee.email) == email.lower(),
        ).first():
            return jsonify({"message": "An employee with this email already exists"}), 409
        if not isinstance(role, str) or len(role.strip()) > 80:
            return jsonify({"message": "Role must be 80 characters or fewer"}), 400
        if not isinstance(status, str) or status not in {"Active", "On leave", "Inactive"}:
            return jsonify({"message": "Status must be Active, On leave, or Inactive"}), 400
        employee = Employee(
            name=name.strip(),
            email=email,
            role=role.strip() or "Employee",
            account_role=account_role,
            status=status,
            user_id=session["user_id"],
            workspace_id=current_workspace_id(),
        )
        db.session.add(employee)
        add_notification(f"New employee added: {employee.name}", "success")
        db.session.commit()
        return jsonify(employee.to_dict()), 201

    @app.route("/api/employees/<int:employee_id>", methods=["PATCH", "DELETE"])
    @require_roles("Admin", "Manager")
    def update_employee(employee_id):
        employee = Employee.query.filter_by(
            id=employee_id,
            workspace_id=current_workspace_id(),
        ).first()
        if employee is None:
            return jsonify({"message": "Employee not found"}), 404
        if request.method == "DELETE":
            if employee.linked_user_id is not None:
                return jsonify({"message": "This employee has a login account. Set the employee to Inactive instead."}), 409
            Task.query.filter_by(
                workspace_id=current_workspace_id(),
                assignee_id=employee.id,
            ).update({Task.assignee_id: None, Task.assignee: None}, synchronize_session=False)
            WorkspaceInvitation.query.filter_by(employee_id=employee.id, accepted_at=None).delete()
            db.session.delete(employee)
            add_notification(f"Employee removed: {employee.name}", "warning")
            db.session.commit()
            return jsonify({"message": "Employee deleted"})
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data or set(data) - {"name", "email", "role", "status", "account_role"}:
            return jsonify({"message": "Provide a valid employee update"}), 400
        if "name" in data and isinstance(data["name"], str) and 2 <= len(data["name"].strip()) <= 80:
            employee.name = data["name"].strip()
        elif "name" in data:
            return jsonify({"message": "Name must contain 2 to 80 characters"}), 400
        if "email" in data:
            email = data["email"]
            if not isinstance(email, str):
                return jsonify({"message": "A valid email is required"}), 400
            email = email.strip()
            if not email or "@" not in email or any(character.isspace() for character in email) or len(email) > 160:
                return jsonify({"message": "A valid email is required"}), 400
            duplicate = Employee.query.filter(
                Employee.workspace_id == current_workspace_id(),
                Employee.id != employee.id,
                func.lower(Employee.email) == email.lower(),
            ).first()
            if duplicate:
                return jsonify({"message": "An employee with this email already exists"}), 409
            employee.email = email
        if "role" in data:
            if not isinstance(data["role"], str) or len(data["role"].strip()) > 80:
                return jsonify({"message": "Role must be 80 characters or fewer"}), 400
            employee.role = data["role"].strip() or "Employee"
        if "status" in data:
            if data["status"] not in {"Active", "On leave", "Inactive"}:
                return jsonify({"message": "Invalid employee status"}), 400
            employee.status = data["status"]
        if "account_role" in data:
            if data["account_role"] not in {"Employee", "Manager"}:
                return jsonify({"message": "Account access must be Employee or Manager"}), 400
            if data["account_role"] == "Manager" and current_user().role != "Admin":
                return jsonify({"message": "Only an Admin can invite a Manager"}), 403
            if employee.linked_user_id is not None:
                return jsonify({"message": "Change access for an existing account in Admin control"}), 409
            employee.account_role = data["account_role"]
        db.session.commit()
        return jsonify(employee.to_dict())

    @app.route("/api/employees/<int:employee_id>/invite", methods=["POST"])
    @require_roles("Admin", "Manager")
    def invite_employee(employee_id):
        employee = Employee.query.filter_by(
            id=employee_id,
            workspace_id=current_workspace_id(),
        ).first()
        if employee is None:
            return jsonify({"message": "Employee not found"}), 404
        if employee.linked_user_id is not None:
            return jsonify({"message": "This employee already has an account"}), 409

        data = request.get_json(silent=True) or {}
        account_role = data.get("account_role", employee.account_role) if isinstance(data, dict) else None
        if account_role not in {"Employee", "Manager"}:
            return jsonify({"message": "Account access must be Employee or Manager"}), 400
        if account_role == "Manager" and current_user().role != "Admin":
            return jsonify({"message": "Only an Admin can invite a Manager"}), 403

        public_url = os.environ.get("TASKFLOW_PUBLIC_URL", "").strip().rstrip("/")
        if public_url:
            parsed_public_url = urlsplit(public_url)
            is_local_url = parsed_public_url.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                parsed_public_url.scheme not in ({"http", "https"} if is_local_url else {"https"})
                or not parsed_public_url.hostname
                or parsed_public_url.username
                or parsed_public_url.password
                or parsed_public_url.query
                or parsed_public_url.fragment
            ):
                return jsonify({"message": "TASKFLOW_PUBLIC_URL must be a valid public HTTPS URL"}), 500
        else:
            request_host = urlsplit(request.url_root).hostname
            if request_host not in {"localhost", "127.0.0.1", "::1"}:
                return jsonify({"message": "Invitation links require TASKFLOW_PUBLIC_URL outside localhost"}), 503
            public_url = request.url_root.rstrip("/")

        token = secrets.token_urlsafe(32)
        invitation = WorkspaceInvitation(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            email=employee.email,
            workspace_id=current_workspace_id(),
            employee_id=employee.id,
            created_by=session["user_id"],
            account_role=account_role,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        WorkspaceInvitation.query.filter_by(employee_id=employee.id, accepted_at=None).delete()
        db.session.add(invitation)
        db.session.commit()
        invite_url = f"{public_url}/register.html?invite={token}"
        return jsonify({"invite_url": invite_url, "email": employee.email, "account_role": account_role, "expires_at": invitation.expires_at.isoformat()}), 201

    @app.route("/api/invitations/<token>", methods=["GET"])
    def get_invitation(token):
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        invitation = WorkspaceInvitation.query.filter_by(token_hash=token_hash).first()
        expires_at = invitation.expires_at if invitation else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if invitation is None or invitation.accepted_at or expires_at <= datetime.now(timezone.utc):
            return jsonify({"message": "This invitation is invalid or expired"}), 404
        employee = db.session.get(Employee, invitation.employee_id)
        workspace = db.session.get(Workspace, invitation.workspace_id)
        if employee is None or employee.linked_user_id is not None or workspace is None:
            return jsonify({"message": "This invitation is no longer available"}), 404
        return jsonify({"email": invitation.email, "employee_name": employee.name, "workspace_name": workspace.name, "account_role": invitation.account_role or "Employee"})

    @app.route("/api/invitations/accept", methods=["POST"])
    def accept_invitation():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "Invitation details are required"}), 400
        token = data.get("invite_token")
        username = data.get("username")
        password = data.get("password")
        if not isinstance(token, str) or not isinstance(username, str) or not isinstance(password, str):
            return jsonify({"message": "Invitation, username, and password are required"}), 400
        username = username.strip()
        if not 3 <= len(username) <= 80 or not 8 <= len(password) <= 128:
            return jsonify({"message": "Username must be 3 to 80 characters and password 8 to 128 characters"}), 400
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            return jsonify({"message": "User already exists"}), 409

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        invitation = WorkspaceInvitation.query.filter_by(token_hash=token_hash).first()
        expires_at = invitation.expires_at if invitation else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if invitation is None or invitation.accepted_at or expires_at <= datetime.now(timezone.utc):
            return jsonify({"message": "This invitation is invalid or expired"}), 404
        employee = Employee.query.filter_by(
            id=invitation.employee_id,
            workspace_id=invitation.workspace_id,
            linked_user_id=None,
        ).first()
        if employee is None:
            return jsonify({"message": "This invitation is no longer available"}), 404

        user = User(
            username=username,
            email=employee.email.strip().lower(),
            password=generate_password_hash(password),
            role=invitation.account_role or "Employee",
            workspace_id=invitation.workspace_id,
        )
        db.session.add(user)
        db.session.flush()
        employee.linked_user_id = user.id
        invitation.accepted_at = datetime.now(timezone.utc)
        db.session.commit()
        session.clear()
        session["user_id"] = user.id
        return jsonify({"message": "Invitation accepted", "invited": True, "role": user.role}), 201

    @app.route("/api/notifications", methods=["GET"])
    @login_required
    def get_notifications():
        user_id = session["user_id"]
        notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).limit(20).all()
        return jsonify([notification.to_dict() for notification in notifications])

    @app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
    @login_required
    def mark_notification_read(notification_id):
        notification = Notification.query.filter_by(id=notification_id, user_id=session["user_id"]).first()
        if notification is None:
            return jsonify({"message": "Notification not found"}), 404
        notification.read = True
        db.session.commit()
        return jsonify(notification.to_dict())

    @app.route("/api/pipelines", methods=["GET"])
    @require_roles("Admin", "Manager")
    def get_pipelines():
        pipelines = PipelineRun.query.filter_by(workspace_id=current_workspace_id()).order_by(PipelineRun.started_at.desc()).limit(10).all()
        return jsonify([pipeline.to_dict() for pipeline in pipelines])

    @app.route("/api/pipelines/trigger", methods=["POST"])
    @require_roles("Admin", "Manager")
    def trigger_pipeline():
        data = request.get_json(silent=True) or {}
        job_name = data.get("job_name", os.environ.get("JENKINS_JOB", "taskflow"))
        branch = data.get("branch", "main")
        pipeline = PipelineRun(job_name=job_name, branch=branch, status="Queued", user_id=session["user_id"], workspace_id=current_workspace_id())
        db.session.add(pipeline)
        jenkins_url = os.environ.get("JENKINS_URL")
        triggered = False
        if jenkins_url:
            try:
                request_url = f"{jenkins_url.rstrip('/')}/job/{job_name}/buildWithParameters?BRANCH={branch}"
                with urlopen(Request(request_url, method="POST"), timeout=5) as response:
                    triggered = 200 <= response.status < 300
            except (HTTPError, URLError, TimeoutError):
                triggered = False
        pipeline.status = "Running" if triggered else "Queued"
        add_notification(f"Pipeline {job_name} queued for {branch}", "info")
        db.session.commit()
        return jsonify({"pipeline": pipeline.to_dict(), "jenkins_triggered": triggered}), 202

    def owned_task_or_404(task_id):
        task = visible_tasks_query().filter_by(id=task_id).first()
        if task is None:
            return None, (jsonify({"message": "Task not found"}), 404)
        return task, None

    def add_activity(message, task_id=None):
        db.session.add(ActivityLog(message=message, task_id=task_id, user_id=session["user_id"], workspace_id=current_workspace_id()))

    @app.route("/api/users", methods=["GET"])
    @require_roles("Admin")
    def list_users():
        users = User.query.filter_by(workspace_id=current_workspace_id()).order_by(User.username.asc()).all()
        return jsonify([{"id": user.id, "username": user.username, "role": user.role, "two_factor_enabled": user.two_factor_enabled} for user in users])

    @app.route("/api/users/<int:user_id>/role", methods=["PATCH"])
    @require_roles("Admin")
    def update_user_role(user_id):
        user = User.query.filter_by(id=user_id, workspace_id=current_workspace_id()).first()
        data = request.get_json(silent=True) or {}
        if (
            not isinstance(data, dict)
            or user is None
            or not isinstance(data.get("role"), str)
            or data["role"] not in {"Admin", "Manager", "Employee"}
        ):
            return jsonify({"message": "User or role is invalid"}), 400
        if user.role == "Admin" and data["role"] != "Admin":
            admin_count = User.query.filter_by(
                workspace_id=current_workspace_id(),
                role="Admin",
            ).count()
            if admin_count <= 1:
                return jsonify({"message": "A workspace must keep at least one Admin"}), 409
        user.role = data["role"]
        employee = Employee.query.filter_by(linked_user_id=user.id).first()
        if employee is not None:
            employee.account_role = user.role
        db.session.commit()
        return jsonify({"id": user.id, "username": user.username, "role": user.role})

    @app.route("/api/security/2fa", methods=["POST"])
    @login_required
    def toggle_two_factor():
        user = db.session.get(User, session["user_id"])
        user.two_factor_enabled = bool((request.get_json(silent=True) or {}).get("enabled", True))
        db.session.commit()
        return jsonify({"enabled": user.two_factor_enabled})

    @app.route("/api/security/2fa/setup", methods=["POST"])
    @login_required
    def setup_two_factor():
        try:
            import pyotp
        except ImportError:
            return jsonify({"message": "OTP dependency is not installed"}), 503
        user = db.session.get(User, session["user_id"])
        user.two_factor_secret = pyotp.random_base32()
        db.session.commit()
        uri = pyotp.TOTP(user.two_factor_secret).provisioning_uri(name=user.username, issuer_name="TaskFlow")
        return jsonify({"secret": user.two_factor_secret, "otpauth_uri": uri})

    @app.route("/api/security/2fa/verify", methods=["POST"])
    @login_required
    def verify_two_factor():
        try:
            import pyotp
        except ImportError:
            return jsonify({"message": "OTP dependency is not installed"}), 503
        user = db.session.get(User, session["user_id"])
        code = str((request.get_json(silent=True) or {}).get("code", ""))
        if not user.two_factor_secret or not pyotp.TOTP(user.two_factor_secret).verify(code):
            return jsonify({"message": "Invalid OTP code"}), 400
        user.two_factor_enabled = True
        db.session.commit()
        return jsonify({"enabled": True})

    @app.route("/api/security/login-activity", methods=["GET"])
    @login_required
    def login_activity():
        activity = LoginActivity.query.filter_by(user_id=session["user_id"]).order_by(LoginActivity.created_at.desc()).limit(30).all()
        return jsonify([item.to_dict() for item in activity])

    @app.route("/api/password-reset/request", methods=["POST"])
    def request_password_reset():
        data = request.get_json(silent=True)
        identifier = str(data.get("identifier", data.get("username", ""))).strip().lower() if isinstance(data, dict) else ""
        user = User.query.filter(
            (func.lower(User.username) == identifier) | (func.lower(User.email) == identifier)
        ).first()
        recipient = recovery_email_for(user) if user else None
        if user is None or not recipient:
            return jsonify({"message": "If the account exists and email delivery is configured, reset instructions will be sent to its recovery email."})

        token = secrets.token_urlsafe(48)
        reset = PasswordReset(
            token=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            user_id=user.id,
        )
        PasswordReset.query.filter_by(user_id=user.id, used=False).delete()
        db.session.add(reset)
        db.session.commit()
        try:
            public_url = os.environ.get("TASKFLOW_PUBLIC_URL")
            if public_url:
                public_url = public_url.rstrip("/")
            elif request.host.split(":", 1)[0] in {"localhost", "127.0.0.1"}:
                public_url = request.url_root.rstrip("/")
            else:
                raise RuntimeError("Password reset email requires TASKFLOW_PUBLIC_URL outside localhost")
            reset_url = f"{public_url}/login.html#reset_token={token}"
            _send_password_reset_email(recipient, reset_url)
        except (OSError, RuntimeError, smtplib.SMTPException, ValueError):
            db.session.delete(reset)
            db.session.commit()
            app.logger.warning("TaskFlow password reset email could not be sent", exc_info=True)
        return jsonify({"message": "If the account exists and email delivery is configured, reset instructions will be sent to its recovery email."})

    @app.route("/api/password-reset/confirm", methods=["POST"])
    def confirm_password_reset():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if isinstance(token, str) else ""
        reset = PasswordReset.query.filter_by(token=token_hash, used=False).first()
        expiry = reset.expires_at.replace(tzinfo=timezone.utc) if reset and reset.expires_at.tzinfo is None else reset.expires_at if reset else None
        if reset is None or expiry <= datetime.now(timezone.utc):
            return jsonify({"message": "Reset token is invalid or expired"}), 400
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            return jsonify({"message": "Password must contain 8 to 128 characters"}), 400
        user = db.session.get(User, reset.user_id)
        user.password = generate_password_hash(password)
        reset.used = True
        db.session.commit()
        return jsonify({"message": "Password reset successful"})

    @app.route("/")
    def home():
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id is not None else None
        page = "dashboard.html" if user else "index.html"
        return app.send_static_file(page)

    @app.route("/api/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            database = "up"
        except SQLAlchemyError:
            database = "down"
        status_code = 200 if database == "up" else 503
        return jsonify({
            "status": "success" if database == "up" else "degraded",
            "message": "TaskFlow Backend is running!",
            "database": database,
        }), status_code

    @app.route("/api/metrics")
    @require_roles("Admin", "Manager")
    def metrics():
        return jsonify({
            "tasks": Task.query.filter_by(workspace_id=current_workspace_id()).count(),
            "employees": Employee.query.filter_by(workspace_id=current_workspace_id()).count(),
            "notifications": Notification.query.filter_by(user_id=session["user_id"], read=False).count(),
            "pipelines": PipelineRun.query.filter_by(workspace_id=current_workspace_id()).count(),
            "requests": request_metrics,
        })

    @app.route("/api/metrics/prometheus")
    def prometheus_metrics():
        average = request_metrics["total_ms"] / request_metrics["count"] if request_metrics["count"] else 0
        body = "\n".join([
            f"taskflow_http_requests_total {request_metrics['count']}",
            f"taskflow_http_errors_total {request_metrics['errors']}",
            f"taskflow_http_request_duration_ms_average {average}",
        ]) + "\n"
        return Response(body, mimetype="text/plain")

    @app.route("/api/admin/backup", methods=["POST"])
    @require_roles("Admin")
    def create_backup():
        backup_directory = os.path.join(app.instance_path, "backups")
        os.makedirs(backup_directory, exist_ok=True)
        workspace_id = current_workspace_id()
        workspace = db.session.get(Workspace, workspace_id)
        if workspace is None:
            return jsonify({"message": "Workspace not found"}), 404
        backup_name = f"taskflow-workspace-{workspace_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        backup_path = os.path.join(backup_directory, backup_name)
        backup_data = {
            "workspace": {"id": workspace.id, "name": workspace.name},
            "members": [
                {"username": user.username, "role": user.role}
                for user in User.query.filter_by(workspace_id=workspace_id).order_by(User.username.asc()).all()
            ],
            "employees": [employee.to_dict() for employee in Employee.query.filter_by(workspace_id=workspace_id).order_by(Employee.name.asc()).all()],
            "tasks": [task.to_dict() for task in Task.query.filter_by(workspace_id=workspace_id).order_by(Task.id.asc()).all()],
            "activity": [item.to_dict() for item in ActivityLog.query.filter_by(workspace_id=workspace_id).order_by(ActivityLog.created_at.asc()).all()],
            "pipelines": [item.to_dict() for item in PipelineRun.query.filter_by(workspace_id=workspace_id).order_by(PipelineRun.started_at.asc()).all()],
        }
        with open(backup_path, "w", encoding="utf-8") as backup_file:
            json.dump(backup_data, backup_file, indent=2)
        return jsonify({"message": "Workspace export created", "file": backup_name, "download_url": f"/api/admin/backup/{backup_name}"})

    @app.route("/api/admin/backup/<path:filename>")
    @require_roles("Admin")
    def download_workspace_backup(filename):
        workspace_id = current_workspace_id()
        if not filename.startswith(f"taskflow-workspace-{workspace_id}-") or secure_filename(filename) != filename:
            return jsonify({"message": "Backup not found"}), 404
        backup_directory = os.path.join(app.instance_path, "backups")
        if not os.path.isfile(os.path.join(backup_directory, filename)):
            return jsonify({"message": "Backup not found"}), 404
        return send_from_directory(backup_directory, filename, as_attachment=True, download_name=filename)

    @app.route("/api/session")
    def get_session():
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id is not None else None
        if user is None:
            session.clear()
            return jsonify({"message": "Authentication required"}), 401
        return jsonify({"id": user.id, "username": user.username, "role": user.role, "workspace_id": user.workspace_id, "two_factor_enabled": user.two_factor_enabled, "recovery_email": recovery_email_for(user) or ""})

    @app.route("/api/account/recovery-email", methods=["PUT"])
    @login_required
    def update_recovery_email():
        data = request.get_json(silent=True) or {}
        email = data.get("email")
        if not is_valid_email(email):
            return jsonify({"message": "Enter a valid recovery email address"}), 400
        user = current_user()
        user.email = email.strip().lower()
        db.session.commit()
        return jsonify({"recovery_email": user.email, "message": "Recovery email updated."})

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session.clear()
        return jsonify({"message": "Logged out"})

    @app.route("/api/tasks", methods=["GET"])
    @login_required
    def get_tasks():
        tasks = visible_tasks_query().order_by(Task.position.asc(), Task.id.desc()).all()
        return jsonify([task.to_dict() for task in tasks])

    @app.route("/api/tasks/bulk", methods=["PATCH", "DELETE"])
    @require_roles("Admin", "Manager")
    def bulk_tasks():
        data = request.get_json(silent=True) or {}
        ids = data.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(task_id, int) for task_id in ids):
            return jsonify({"message": "A non-empty task id list is required"}), 400
        tasks = visible_tasks_query().filter(Task.id.in_(ids)).all()
        if len(tasks) != len(set(ids)):
            return jsonify({"message": "One or more tasks were not found"}), 404
        if request.method == "DELETE":
            for task in tasks:
                add_activity(f"Task deleted: {task.title}", task.id)
                db.session.delete(task)
        else:
            status = data.get("status")
            priority = data.get("priority")
            if status is not None and status not in {"Pending", "To Do", "In Progress", "Review", "Completed"}:
                return jsonify({"message": "Invalid workflow status"}), 400
            if priority is not None and priority not in {"Low", "Medium", "High"}:
                return jsonify({"message": "Invalid priority"}), 400
            for task in tasks:
                if status is not None:
                    task.status = status
                if priority is not None:
                    task.priority = priority
                add_activity(f"Task updated in bulk: {task.title}", task.id)
        db.session.commit()
        return jsonify({"updated": len(tasks)})

    @app.route("/api/tasks/<int:task_id>/comments", methods=["GET", "POST"])
    @login_required
    def task_comments(task_id):
        task, error = owned_task_or_404(task_id)
        if error:
            return error
        if request.method == "GET":
            comments = TaskComment.query.filter_by(task_id=task.id).order_by(TaskComment.created_at.asc()).all()
            return jsonify([comment.to_dict() for comment in comments])
        data = request.get_json(silent=True) or {}
        body = data.get("body")
        if not isinstance(body, str) or not body.strip() or len(body.strip()) > 1000:
            return jsonify({"message": "Comment must contain 1 to 1000 characters"}), 400
        comment = TaskComment(body=body.strip(), task_id=task.id, user_id=session["user_id"])
        db.session.add(comment)
        add_activity(f"Comment added to {task.title}", task.id)
        add_notification(f"New comment on {task.title}", "info")
        db.session.commit()
        return jsonify(comment.to_dict()), 201

    @app.route("/api/tasks/<int:task_id>/attachments", methods=["GET", "POST"])
    @login_required
    def task_attachments(task_id):
        task, error = owned_task_or_404(task_id)
        if error:
            return error
        if request.method == "GET":
            attachments = TaskAttachment.query.filter_by(task_id=task.id).order_by(TaskAttachment.created_at.desc()).all()
            return jsonify([attachment.to_dict() for attachment in attachments])
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("name"), str) or not data["name"].strip() or not isinstance(data.get("url"), str) or not data["url"].startswith(("http://", "https://")):
            return jsonify({"message": "Attachment name and http(s) URL are required"}), 400
        attachment = TaskAttachment(name=data["name"].strip()[:160], url=data["url"].strip()[:500], task_id=task.id, user_id=session["user_id"])
        db.session.add(attachment)
        add_activity(f"Attachment added to {task.title}", task.id)
        db.session.commit()
        return jsonify(attachment.to_dict()), 201

    @app.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
    @login_required
    def delete_attachment(attachment_id):
        attachment = TaskAttachment.query.join(Task).filter(
            TaskAttachment.id == attachment_id,
            Task.workspace_id == current_workspace_id(),
        ).first()
        if attachment is None:
            return jsonify({"message": "Attachment not found"}), 404
        stored_file = os.path.join(upload_directory, os.path.basename(attachment.url))
        if os.path.exists(stored_file):
            os.remove(stored_file)
        db.session.delete(attachment)
        db.session.commit()
        return jsonify({"message": "Attachment deleted"})

    @app.route("/api/tasks/<int:task_id>/attachments/upload", methods=["POST"])
    @login_required
    def upload_task_attachment(task_id):
        task, error = owned_task_or_404(task_id)
        if error:
            return error
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"message": "Choose a file to upload"}), 400
        filename = secure_filename(uploaded.filename)
        if not filename:
            return jsonify({"message": "The file name is invalid"}), 400
        stored_name = f"{secrets.token_hex(8)}-{filename}"
        uploaded.save(os.path.join(upload_directory, stored_name))
        attachment = TaskAttachment(name=filename, url=f"/api/uploads/{stored_name}", task_id=task.id, user_id=session["user_id"])
        db.session.add(attachment)
        add_activity(f"File attached to {task.title}", task.id)
        db.session.commit()
        return jsonify(attachment.to_dict()), 201

    @app.route("/api/uploads/<path:filename>")
    @login_required
    def download_upload(filename):
        allowed = TaskAttachment.query.join(Task).filter(
            TaskAttachment.url == f"/api/uploads/{filename}",
            Task.workspace_id == current_workspace_id(),
        ).first()
        if allowed is None:
            return jsonify({"message": "File not found"}), 404
        return send_from_directory(upload_directory, filename, as_attachment=False)

    @app.route("/api/reports/tasks.csv")
    @login_required
    def task_report():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "title", "status", "priority", "assignee", "due_date", "comments"])
        tasks_query = visible_tasks_query()
        from_date = request.args.get("from")
        to_date = request.args.get("to")
        if from_date:
            tasks_query = tasks_query.filter(Task.due_date >= from_date)
        if to_date:
            tasks_query = tasks_query.filter(Task.due_date <= to_date)
        tasks = tasks_query.order_by(Task.id.asc()).all()
        for task in tasks:
            writer.writerow([task.id, task.title, task.status, task.priority, task.assignee or "", task.due_date or "", TaskComment.query.filter_by(task_id=task.id).count()])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=taskflow-report.csv"})

    @app.route("/api/reports/tasks.pdf")
    @login_required
    def task_pdf_report():
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            return jsonify({"message": "PDF reporting dependency is not installed"}), 503
        output = io.BytesIO()
        document = canvas.Canvas(output, pagesize=letter)
        document.setTitle("TaskFlow task report")
        document.drawString(48, 750, "TaskFlow Task Report")
        y = 720
        tasks_query = visible_tasks_query()
        if request.args.get("from"):
            tasks_query = tasks_query.filter(Task.due_date >= request.args["from"])
        if request.args.get("to"):
            tasks_query = tasks_query.filter(Task.due_date <= request.args["to"])
        for task in tasks_query.order_by(Task.position.asc()).all():
            line = f"{task.id}. {task.title[:55]} | {task.status} | {task.priority} | {task.due_date or 'No due date'}"
            document.drawString(48, y, line)
            y -= 18
            if y < 48:
                document.showPage()
                y = 750
        document.save()
        return Response(output.getvalue(), mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=taskflow-report.pdf"})

    @app.route("/api/activity", methods=["GET"])
    @login_required
    def get_activity():
        query = ActivityLog.query.filter_by(workspace_id=current_workspace_id())
        if current_user().role == "Employee":
            query = query.filter_by(user_id=session["user_id"])
        activity = query.order_by(ActivityLog.created_at.desc()).limit(50).all()
        return jsonify([item.to_dict() for item in activity])

    @app.route("/api/analytics", methods=["GET"])
    @login_required
    def get_analytics():
        tasks_query = visible_tasks_query()
        from_date = request.args.get("from")
        to_date = request.args.get("to")
        if from_date:
            tasks_query = tasks_query.filter(Task.due_date >= from_date)
        if to_date:
            tasks_query = tasks_query.filter(Task.due_date <= to_date)
        tasks = tasks_query.all()
        return jsonify({
            "total": len(tasks),
            "completed": sum(task.status == "Completed" for task in tasks),
            "pending": sum(task.status == "Pending" for task in tasks),
            "priority": {priority: sum(task.priority == priority for task in tasks) for priority in ("High", "Medium", "Low")},
            "due": {"overdue": sum(bool(task.due_date and task.due_date < datetime.now(timezone.utc).date().isoformat() and task.status != "Completed") for task in tasks), "scheduled": sum(bool(task.due_date) for task in tasks)},
        })

    @app.route("/api/calendar", methods=["GET"])
    @login_required
    def get_calendar():
        tasks = visible_tasks_query().filter(Task.due_date.isnot(None)).order_by(Task.due_date.asc()).all()
        return jsonify([task.to_dict() for task in tasks])

    @app.route("/api/workload", methods=["GET"])
    @require_roles("Admin", "Manager")
    def get_workload():
        workspace_id = current_workspace_id()
        today = datetime.now(timezone.utc).date()
        due_soon_limit = (today + timedelta(days=7)).isoformat()
        employees = Employee.query.filter_by(workspace_id=workspace_id).order_by(Employee.name.asc()).all()
        tasks = Task.query.filter_by(workspace_id=workspace_id).all()
        workload = []
        for employee in employees:
            assigned = [task for task in tasks if task.assignee_id == employee.id]
            active = [task for task in assigned if task.status != "Completed"]
            workload.append({
                "employee_id": employee.id,
                "name": employee.name,
                "role": employee.role,
                "active_tasks": len(active),
                "overdue_tasks": sum(bool(task.due_date and task.due_date < today.isoformat()) for task in active),
                "due_soon_tasks": sum(bool(task.due_date and today.isoformat() <= task.due_date <= due_soon_limit) for task in active),
            })
        return jsonify(workload)

    @app.route("/api/tasks", methods=["POST"])
    @require_roles("Admin", "Manager")
    def create_task():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "A JSON task is required"}), 400

        title = data.get("title")
        status = data.get("status", "Pending")
        priority = data.get("priority", "Medium")
        due_date = data.get("due_date")
        description = data.get("description")
        assignee = data.get("assignee")
        assignee_id = data.get("assignee_id")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            return jsonify({"message": "Title must contain 1 to 200 characters"}), 400
        if not isinstance(status, str) or status not in {"Pending", "To Do", "In Progress", "Review", "Completed"}:
            return jsonify({"message": "Status must be To Do, In Progress, Review, or Completed"}), 400
        if not isinstance(priority, str) or priority not in {"Low", "Medium", "High"}:
            return jsonify({"message": "Priority must be Low, Medium, or High"}), 400
        if due_date is not None and (not isinstance(due_date, str) or len(due_date) != 10):
            return jsonify({"message": "Due date must be in YYYY-MM-DD format"}), 400
        if description is not None and (not isinstance(description, str) or len(description.strip()) > 1000):
            return jsonify({"message": "Description must contain at most 1000 characters"}), 400
        if assignee is not None and (not isinstance(assignee, str) or len(assignee.strip()) > 80):
            return jsonify({"message": "Assignee must contain at most 80 characters"}), 400
        assigned_employee = None
        if assignee_id not in (None, ""):
            if type(assignee_id) is not int:
                return jsonify({"message": "Assignee must be a valid employee"}), 400
            assigned_employee = Employee.query.filter_by(id=assignee_id, workspace_id=current_workspace_id()).first()
            if assigned_employee is None:
                return jsonify({"message": "Assignee must belong to this workspace"}), 400
        elif isinstance(assignee, str) and assignee.strip():
            assigned_employee = Employee.query.filter(
                Employee.workspace_id == current_workspace_id(),
                func.lower(Employee.name) == assignee.strip().lower(),
            ).first()

        task = Task(
            title=title.strip(),
            status=status,
            priority=priority,
            due_date=due_date,
            description=description.strip() if isinstance(description, str) and description.strip() else None,
            assignee=assigned_employee.name if assigned_employee else assignee.strip() if isinstance(assignee, str) and assignee.strip() else None,
            assignee_id=assigned_employee.id if assigned_employee else None,
            position=(db.session.query(func.max(Task.position)).filter_by(workspace_id=current_workspace_id()).scalar() or -1) + 1,
            user_id=session["user_id"],
            workspace_id=current_workspace_id(),
        )
        db.session.add(task)
        add_activity(f"Task created: {task.title}")
        add_notification(f"Task created: {task.title}", "success")
        db.session.commit()
        return jsonify(task.to_dict()), 201

    @app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
    @login_required
    def update_task(task_id):
        task, error = owned_task_or_404(task_id)
        if error:
            return error

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data or set(data) - {"title", "status", "priority", "due_date", "description", "assignee", "assignee_id", "position"}:
            return jsonify({"message": "Provide a valid task update"}), 400
        if current_user().role == "Employee" and set(data) != {"status"}:
            return jsonify({"message": "Employees can only update task status"}), 403

        if "title" in data:
            title = data["title"]
            if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
                return jsonify({"message": "Title must contain 1 to 200 characters"}), 400
            task.title = title.strip()
        if "status" in data:
            status = data["status"]
            if not isinstance(status, str) or status not in {"Pending", "To Do", "In Progress", "Review", "Completed"}:
                return jsonify({"message": "Status must be To Do, In Progress, Review, or Completed"}), 400
            task.status = status
        if "priority" in data:
            priority = data["priority"]
            if not isinstance(priority, str) or priority not in {"Low", "Medium", "High"}:
                return jsonify({"message": "Priority must be Low, Medium, or High"}), 400
            task.priority = priority
        if "due_date" in data:
            due_date = data["due_date"]
            if due_date is not None and (not isinstance(due_date, str) or len(due_date) != 10):
                return jsonify({"message": "Due date must be in YYYY-MM-DD format"}), 400
            task.due_date = due_date
        if "description" in data:
            description = data["description"]
            if description is not None and (not isinstance(description, str) or len(description.strip()) > 1000):
                return jsonify({"message": "Description must contain at most 1000 characters"}), 400
            task.description = description.strip() if isinstance(description, str) and description.strip() else None
        if "assignee_id" in data or "assignee" in data:
            assignee = data.get("assignee")
            assignee_id = data.get("assignee_id")
            if assignee_id not in (None, ""):
                if type(assignee_id) is not int:
                    return jsonify({"message": "Assignee must be a valid employee"}), 400
                assigned_employee = Employee.query.filter_by(id=assignee_id, workspace_id=current_workspace_id()).first()
                if assigned_employee is None:
                    return jsonify({"message": "Assignee must belong to this workspace"}), 400
                task.assignee_id = assigned_employee.id
                task.assignee = assigned_employee.name
            elif assignee is not None and (not isinstance(assignee, str) or len(assignee.strip()) > 80):
                return jsonify({"message": "Assignee must contain at most 80 characters"}), 400
            elif isinstance(assignee, str) and assignee.strip():
                task.assignee = assignee.strip()
                assigned_employee = Employee.query.filter(
                    Employee.workspace_id == current_workspace_id(),
                    func.lower(Employee.name) == task.assignee.lower(),
                ).first()
                task.assignee_id = assigned_employee.id if assigned_employee else None
            else:
                task.assignee = None
                task.assignee_id = None
        if "position" in data:
            if not isinstance(data["position"], int) or data["position"] < 0:
                return jsonify({"message": "Position must be a non-negative integer"}), 400
            task.position = data["position"]

        add_activity(f"Task updated: {task.title}", task.id)
        add_notification(f"Task updated: {task.title}", "info")
        db.session.commit()
        return jsonify(task.to_dict())

    @app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
    @require_roles("Admin", "Manager")
    def delete_task(task_id):
        task, error = owned_task_or_404(task_id)
        if error:
            return error
        db.session.delete(task)
        add_activity(f"Task deleted: {task.title}", task.id)
        db.session.commit()
        return jsonify({"message": "Task deleted successfully"})

    @app.route("/api/register", methods=["POST"])
    def register():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "A JSON account is required"}), 400

        username = data.get("username")
        password = data.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return jsonify({"message": "Username and password are required"}), 400
        username = username.strip()
        if not 3 <= len(username) <= 80:
            return jsonify({"message": "Username must contain 3 to 80 characters"}), 400
        if not 8 <= len(password) <= 128:
            return jsonify({"message": "Password must contain 8 to 128 characters"}), 400

        existing_user = User.query.filter(func.lower(User.username) == username.lower()).first()
        if existing_user:
            return jsonify({"message": "User already exists"}), 409

        invite_token = data.get("invite_token")
        invitation = None
        employee = None
        if invite_token is not None:
            if not isinstance(invite_token, str):
                return jsonify({"message": "Invitation is invalid or expired"}), 404
            token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
            invitation = WorkspaceInvitation.query.filter_by(token_hash=token_hash).first()
            expires_at = invitation.expires_at if invitation else None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if invitation is None or invitation.accepted_at or expires_at <= datetime.now(timezone.utc):
                return jsonify({"message": "Invitation is invalid or expired"}), 404
            employee = Employee.query.filter_by(
                id=invitation.employee_id,
                workspace_id=invitation.workspace_id,
                linked_user_id=None,
            ).first()
            if employee is None:
                return jsonify({"message": "This invitation is no longer available"}), 404
            workspace = db.session.get(Workspace, invitation.workspace_id)
            if workspace is None:
                return jsonify({"message": "This invitation is no longer available"}), 404
            recovery_email = employee.email
        else:
            recovery_email = data.get("email")
            if not is_valid_email(recovery_email):
                return jsonify({"message": "A valid recovery email address is required"}), 400
            workspace = Workspace(name=f"{username}'s Workspace")
            db.session.add(workspace)
            db.session.flush()

        assigned_role = (invitation.account_role or "Employee") if invitation else "Admin"
        user = User(
            username=username,
            email=recovery_email.strip().lower(),
            password=generate_password_hash(password),
            role=assigned_role,
            workspace_id=workspace.id,
        )
        db.session.add(user)
        try:
            db.session.flush()
            if invitation is None:
                Task.query.filter(Task.user_id.is_(None), Task.workspace_id.is_(None)).update(
                    {Task.user_id: user.id, Task.workspace_id: workspace.id},
                    synchronize_session=False,
                )
            else:
                employee.linked_user_id = user.id
                invitation.accepted_at = datetime.now(timezone.utc)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"message": "User already exists"}), 409
        if invitation:
            session.clear()
            session["user_id"] = user.id
            return jsonify({"message": "Invitation accepted", "invited": True, "role": user.role}), 201
        return jsonify({"message": "Registration successful", "invited": False, "role": user.role}), 201

    @app.route("/api/registration-info")
    def registration_info():
        return jsonify({"role": "Admin"})

    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "Username and password are required"}), 400

        username = data.get("username")
        password = data.get("password")
        login_role = data.get("login_role")
        if not isinstance(username, str) or not isinstance(password, str):
            return jsonify({"message": "Username and password are required"}), 400
        if login_role is not None and login_role not in ("Employee", "Admin"):
            return jsonify({"message": "Login type must be Employee or Admin"}), 400

        identity = username.strip()
        user = User.query.filter(func.lower(User.username) == identity.lower()).first()
        if user is None and "@" in identity:
            matching_users = User.query.outerjoin(
                Employee,
                Employee.linked_user_id == User.id,
            ).filter(
                or_(
                    func.lower(User.email) == identity.lower(),
                    func.lower(Employee.email) == identity.lower(),
                ),
            ).limit(2).all()
            if len(matching_users) == 1:
                user = matching_users[0]
        if user is None or not check_password_hash(user.password, password):
            db.session.add(LoginActivity(username=identity, success=False, user_id=user.id if user else None))
            db.session.commit()
            return jsonify({"message": "Invalid username or password"}), 401

        if login_role == "Employee" and user.role != "Employee":
            db.session.add(LoginActivity(username=user.username, success=False, user_id=user.id))
            db.session.commit()
            return jsonify({"message": "This account does not have Employee access"}), 403
        if login_role == "Admin" and user.role not in {"Admin", "Manager"}:
            db.session.add(LoginActivity(username=user.username, success=False, user_id=user.id))
            db.session.commit()
            return jsonify({"message": "This account does not have Admin access"}), 403

        if user.two_factor_enabled:
            try:
                import pyotp
            except ImportError:
                return jsonify({"message": "OTP dependency is not installed"}), 503
            otp = str(data.get("otp", ""))
            if not user.two_factor_secret or not pyotp.TOTP(user.two_factor_secret).verify(otp):
                return jsonify({"message": "One-time password required", "two_factor_required": True}), 202

        session.clear()
        session["user_id"] = user.id
        session["role"] = user.role
        session.permanent = data.get("remember_me") is True
        db.session.add(LoginActivity(username=user.username, success=True, user_id=user.id))
        db.session.commit()
        return jsonify({"message": "Login successful", "username": user.username, "role": user.role})

    return app