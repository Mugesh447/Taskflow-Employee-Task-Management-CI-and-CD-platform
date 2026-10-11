import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy.exc import SQLAlchemyError

from backend.app import app as default_app, create_app, db, User
from backend.app_factory import PasswordReset, _database_uri_from_environment
from backend.reminder_scheduler import create_overdue_reminders


class TaskflowApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    @classmethod
    def tearDownClass(cls):
        with default_app.app_context():
            db.session.remove()
            db.engine.dispose()

    def register(self, username="alice", password="password-123", email=None):
        return self.client.post("/api/register", json={
            "username": username,
            "password": password,
            "email": email or f"{username}@example.com",
        })

    def login(self, username="alice", password="password-123"):
        return self.client.post("/api/login", json={
            "username": username,
            "password": password,
        })

    def test_health_is_available_without_authentication(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")

    def test_health_reports_database_outage_as_service_unavailable(self):
        with self.app.app_context():
            with patch.object(db.session, "execute", side_effect=SQLAlchemyError("database unavailable")):
                response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "degraded")
        self.assertEqual(response.get_json()["database"], "down")

    def test_database_components_build_a_safe_postgres_url(self):
        with patch.dict("os.environ", {
            "TASKFLOW_DB_HOST": "database.example",
            "TASKFLOW_DB_USER": "taskflow_app",
            "TASKFLOW_DB_PASSWORD": "p@ss:/word",
            "TASKFLOW_DB_NAME": "taskflow",
        }, clear=True):
            database_url = _database_uri_from_environment()
        self.assertEqual(database_url.drivername, "postgresql+psycopg")
        self.assertEqual(database_url.password, "p@ss:/word")
        self.assertEqual(database_url.host, "database.example")

    def test_partial_database_configuration_fails_explicitly(self):
        with patch.dict("os.environ", {"TASKFLOW_DB_HOST": "database.example"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing database configuration"):
                _database_uri_from_environment()

    def test_home_selects_public_or_authenticated_page(self):
        with self.client.get("/") as response:
            public_page = response.get_data()
        self.assertIn(b"Create account", public_page)
        with self.client.get("/register.html") as response:
            self.assertEqual(response.status_code, 200)
            registration_page = response.get_data()
        self.assertIn(b"Create an Admin account", registration_page)
        self.assertIn(b"Join as an Employee", registration_page)
        self.assertIn(b"invitation link sent by your workspace Admin", registration_page)
        with self.client.get("/login.html") as response:
            login_page = response.get_data()
        self.assertNotIn(b"Login with AWS", login_page)
        self.register()
        self.login()
        with self.client.get("/") as response:
            dashboard_page = response.get_data()
        self.assertIn(b"Your task list", dashboard_page)

    def test_registration_validation_and_session_lifecycle(self):
        self.assertEqual(self.register(password="short").status_code, 400)
        self.assertEqual(self.register(username="invalid-email", email="not-an-email").status_code, 400)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.login(password="wrong-password").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/session").get_json()["username"], "alice")
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_recovery_email_can_be_updated_only_by_signed_in_account(self):
        self.assertEqual(self.client.put("/api/account/recovery-email", json={"email": "new@example.com"}).status_code, 401)
        self.register()
        self.login()
        self.assertEqual(self.client.put("/api/account/recovery-email", json={"email": "invalid"}).status_code, 400)
        updated = self.client.put("/api/account/recovery-email", json={"email": "New.Recovery@example.com"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["recovery_email"], "new.recovery@example.com")
        self.assertEqual(self.client.get("/api/session").get_json()["recovery_email"], "new.recovery@example.com")

    def test_registration_role_preview_and_login_role_are_server_controlled(self):
        preview = self.client.get("/api/registration-info")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()["role"], "Admin")

        created = self.client.post("/api/register", json={
            "username": "alice",
            "password": "password-123",
            "email": "alice@example.com",
            "role": "Employee",
        })
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["role"], "Admin")
        employee_login = self.client.post("/api/login", json={
            "username": "alice",
            "password": "password-123",
            "login_role": "Employee",
        })
        self.assertEqual(employee_login.status_code, 403)
        employee_admin_login = self.client.post("/api/login", json={
            "username": "alice",
            "password": "password-123",
            "login_role": "Admin",
        })
        self.assertEqual(employee_admin_login.status_code, 200)
        self.client.post("/api/logout")
        admin_email_login = self.client.post("/api/login", json={
            "username": "alice@example.com",
            "password": "password-123",
            "login_role": "Admin",
        })
        self.assertEqual(admin_email_login.status_code, 200)
        self.client.post("/api/logout")
        legacy_manager_login = self.client.post("/api/login", json={
            "username": "alice",
            "password": "password-123",
            "login_role": "Manager",
        })
        self.assertEqual(legacy_manager_login.status_code, 400)
        admin_login = self.client.post("/api/login", json={
            "username": "alice",
            "password": "password-123",
            "login_role": "Admin",
            "remember_me": True,
        })
        self.assertEqual(admin_login.status_code, 200)
        self.assertIn("Expires=", admin_login.headers["Set-Cookie"])

    def test_admin_and_employee_access_are_separate_and_last_admin_is_protected(self):
        self.register()
        self.login()
        self.assertEqual(self.client.get("/api/users").status_code, 200)

        self.assertEqual(
            self.client.patch("/api/users/1/role", json={"role": "Employee"}).status_code,
            409,
        )
        self.assertEqual(self.client.get("/api/session").get_json()["role"], "Admin")

        employee = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
            "account_role": "Employee",
        }).get_json()
        invitation = self.client.post(f"/api/employees/{employee['id']}/invite").get_json()
        token = parse_qs(urlparse(invitation["invite_url"]).query)["invite"][0]
        accepted = self.client.post("/api/register", json={
            "username": "priya_user",
            "password": "password-123",
            "invite_token": token,
            "role": "Admin",
        })
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(accepted.get_json()["role"], "Employee")
        self.assertEqual(self.client.get("/api/users").status_code, 403)
        self.assertEqual(self.client.post("/api/tasks", json={"title": "Forbidden"}).status_code, 403)
        self.assertEqual(self.client.get("/api/pipelines").status_code, 403)
        self.assertEqual(self.client.get("/api/workload").status_code, 403)
        self.assertEqual(self.client.post("/api/admin/backup").status_code, 403)

    def test_task_lifecycle_requires_login_and_validates_fields(self):
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.register()
        self.login()

        self.assertEqual(self.client.post("/api/tasks", json={}).status_code, 400)
        created = self.client.post("/api/tasks", json={"title": "Prepare release"})
        self.assertEqual(created.status_code, 201)
        task_id = created.get_json()["id"]

        self.assertEqual(len(self.client.get("/api/tasks").get_json()), 1)
        invalid_update = self.client.patch(
            f"/api/tasks/{task_id}", json={"status": "Unknown"}
        )
        self.assertEqual(invalid_update.status_code, 400)
        updated = self.client.patch(f"/api/tasks/{task_id}", json={
            "title": "Ship release",
            "status": "Completed",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["title"], "Ship release")
        self.assertEqual(updated.get_json()["status"], "Completed")
        self.assertEqual(self.client.delete(f"/api/tasks/{task_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/tasks").get_json(), [])

    def test_users_cannot_read_or_change_each_others_tasks(self):
        self.register()
        self.login()
        task = self.client.post("/api/tasks", json={"title": "Private task"}).get_json()
        self.client.post("/api/logout")

        self.register(username="bob")
        self.login(username="bob")

        self.assertEqual(self.client.get("/api/tasks").get_json(), [])
        self.assertEqual(
            self.client.patch(f"/api/tasks/{task['id']}", json={"status": "Completed"}).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/api/tasks/{task['id']}").status_code, 404)

    def test_employee_notifications_and_pipeline_workflow(self):
        self.register()
        self.login()

        employee_response = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
            "role": "Designer",
        })
        self.assertEqual(employee_response.status_code, 201)
        employee_id = employee_response.get_json()["id"]
        self.assertEqual(self.client.get("/api/employees").get_json()[0]["name"], "Priya S")
        duplicate_employee = self.client.post("/api/employees", json={
            "name": "Another Priya",
            "email": "PRIYA@example.com",
        })
        self.assertEqual(duplicate_employee.status_code, 409)

        updated_employee = self.client.patch(f"/api/employees/{employee_id}", json={
            "role": "Lead Designer",
            "status": "On leave",
        })
        self.assertEqual(updated_employee.status_code, 200)
        self.assertEqual(updated_employee.get_json()["role"], "Lead Designer")
        self.assertEqual(updated_employee.get_json()["status"], "On leave")

        notifications = self.client.get("/api/notifications").get_json()
        employee_notification = next(item for item in notifications if "Priya S" in item["message"])
        self.assertFalse(employee_notification["read"])
        marked_read = self.client.post(f"/api/notifications/{employee_notification['id']}/read")
        self.assertEqual(marked_read.status_code, 200)
        self.assertTrue(marked_read.get_json()["read"])

        pipeline_response = self.client.post("/api/pipelines/trigger", json={
            "job_name": "taskflow",
            "branch": "main",
        })
        self.assertEqual(pipeline_response.status_code, 202)
        self.assertEqual(pipeline_response.get_json()["pipeline"]["job_name"], "taskflow")
        self.assertTrue(self.client.get("/api/pipelines").get_json())

        self.assertEqual(self.client.delete(f"/api/employees/{employee_id}").status_code, 200)

    def test_employee_creation_requires_admin_or_manager(self):
        self.register()
        self.register(username="bob")
        with self.app.app_context():
            bob = User.query.filter_by(username="bob").one()
            bob.role = "Employee"
            db.session.commit()
        self.login(username="bob")

        response = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
        })

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/employees").get_json(), [])

    def test_employee_directory_is_isolated_between_workspaces(self):
        self.register()
        self.login()
        created = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
        })
        self.assertEqual(created.status_code, 201)
        self.client.post("/api/logout")

        self.register(username="bob")
        self.login(username="bob")
        employees = self.client.get("/api/employees").get_json()

        self.assertEqual(employees, [])

    def test_employee_invitation_links_account_task_and_workload(self):
        self.register()
        self.login()
        workspace_id = self.client.get("/api/session").get_json()["workspace_id"]
        employee = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
            "role": "Designer",
        }).get_json()

        invitation = self.client.post(f"/api/employees/{employee['id']}/invite")
        self.assertEqual(invitation.status_code, 201)
        invite_url = invitation.get_json()["invite_url"]
        token = parse_qs(urlparse(invite_url).query)["invite"][0]
        self.assertEqual(self.client.get(f"/api/invitations/{token}").get_json()["email"], "priya@example.com")

        accepted = self.client.post("/api/register", json={
            "username": "priya_user",
            "password": "password-123",
            "invite_token": token,
        })
        self.assertEqual(accepted.status_code, 201)
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["workspace_id"], workspace_id)
        self.assertEqual(session["role"], "Employee")
        self.assertTrue(self.client.get("/api/employees").get_json()[0]["account_linked"])
        self.client.post("/api/logout")
        employee_login = self.client.post("/api/login", json={
            "username": "priya@example.com",
            "password": "password-123",
            "login_role": "Employee",
        })
        self.assertEqual(employee_login.status_code, 200)
        self.assertEqual(employee_login.get_json()["role"], "Employee")
        self.assertEqual(self.client.post("/api/tasks", json={"title": "Employee cannot create"}).status_code, 403)
        self.client.post("/api/logout")
        self.login()

        due_date = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
        task = self.client.post("/api/tasks", json={
            "title": "Review onboarding",
            "assignee_id": employee["id"],
            "due_date": due_date,
        })
        self.assertEqual(task.status_code, 201)
        self.assertEqual(task.get_json()["assignee_id"], employee["id"])
        workload = self.client.get("/api/workload").get_json()[0]
        self.assertEqual(workload["active_tasks"], 1)
        self.assertEqual(workload["due_soon_tasks"], 1)
        self.assertEqual(workload["overdue_tasks"], 0)
        self.client.post("/api/logout")
        employee_login = self.client.post("/api/login", json={
            "username": "priya@example.com",
            "password": "password-123",
            "login_role": "Employee",
        })
        self.assertEqual(employee_login.status_code, 200)
        visible_tasks = self.client.get("/api/tasks").get_json()
        self.assertEqual([item["id"] for item in visible_tasks], [task.get_json()["id"]])
        self.assertEqual(self.client.patch(f"/api/tasks/{task.get_json()['id']}", json={
            "status": "In Progress",
        }).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/tasks/{task.get_json()['id']}", json={
            "priority": "High",
        }).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/tasks/{task.get_json()['id']}").status_code, 403)
        self.assertEqual(self.client.patch("/api/tasks/bulk", json={
            "ids": [task.get_json()["id"]],
            "status": "Completed",
        }).status_code, 403)
        self.assertEqual(self.client.get("/api/workload").status_code, 403)

    def test_invitation_uses_configured_public_url(self):
        self.register()
        self.login()
        employee = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
        }).get_json()

        with patch.dict("os.environ", {"TASKFLOW_PUBLIC_URL": "https://taskflow.example.com/"}):
            response = self.client.post(f"/api/employees/{employee['id']}/invite")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            response.get_json()["invite_url"].startswith(
                "https://taskflow.example.com/register.html?invite="
            )
        )

    def test_invitation_requires_public_url_for_non_local_requests(self):
        public_origin = "https://taskflow.example.com"
        self.client.post("/api/register", json={
            "username": "alice",
            "password": "password-123",
            "email": "alice@example.com",
        }, base_url=public_origin)
        self.client.post("/api/login", json={
            "username": "alice",
            "password": "password-123",
        }, base_url=public_origin)
        employee = self.client.post("/api/employees", json={
            "name": "Priya S",
            "email": "priya@example.com",
        }, base_url=public_origin).get_json()

        with patch.dict("os.environ", {}, clear=True):
            response = self.client.post(
                f"/api/employees/{employee['id']}/invite",
                base_url=public_origin,
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("TASKFLOW_PUBLIC_URL", response.get_json()["message"])

    def test_comments_activity_analytics_calendar_and_roles(self):
        self.register()
        login = self.login()
        self.assertEqual(login.get_json()["role"], "Admin")

        task = self.client.post("/api/tasks", json={
            "title": "Prepare report",
            "due_date": "2026-10-15",
            "priority": "High",
        }).get_json()
        comment = self.client.post(f"/api/tasks/{task['id']}/comments", json={
            "body": "I started the report.",
        })
        self.assertEqual(comment.status_code, 201)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/comments").get_json()[0]["body"], "I started the report.")
        self.assertTrue(self.client.get("/api/activity").get_json())
        analytics = self.client.get("/api/analytics").get_json()
        self.assertEqual(analytics["total"], 1)
        self.assertEqual(analytics["priority"]["High"], 1)
        self.assertEqual(self.client.get("/api/calendar").get_json()[0]["title"], "Prepare report")

    def test_advanced_admin_ordering_attachments_reports_and_security(self):
        self.register()
        self.login()
        task = self.client.post("/api/tasks", json={"title": "Ordered task"}).get_json()
        moved = self.client.patch(f"/api/tasks/{task['id']}", json={"status": "Review", "position": 4})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.get_json()["position"], 4)
        attachment = self.client.post(f"/api/tasks/{task['id']}/attachments", json={"name": "Design", "url": "https://example.com/design"})
        self.assertEqual(attachment.status_code, 201)
        self.assertEqual(self.client.get("/api/metrics").get_json()["tasks"], 1)
        self.assertIn("Ordered task", self.client.get("/api/reports/tasks.csv").get_data(as_text=True))
        self.assertEqual(self.client.get("/api/users").status_code, 200)
        self.assertEqual(self.client.post("/api/security/2fa", json={"enabled": True}).get_json()["enabled"], True)

    def test_password_reset_uses_private_expiring_single_use_email_tokens(self):
        self.register(email="alice.recovery@example.com")
        sent_links = []
        with patch("backend.app_factory._send_password_reset_email", side_effect=lambda recipient, link: sent_links.append((recipient, link))):
            reset_request = self.client.post("/api/password-reset/request", json={"identifier": "ALICE"})
            unknown_request = self.client.post("/api/password-reset/request", json={"identifier": "missing@example.com"})

        self.assertEqual(reset_request.status_code, 200)
        self.assertEqual(reset_request.get_json(), unknown_request.get_json())
        self.assertNotIn("token", reset_request.get_json())
        self.assertEqual(len(sent_links), 1)
        self.assertEqual(sent_links[0][0], "alice.recovery@example.com")
        token = parse_qs(urlparse(sent_links[0][1]).fragment)["reset_token"][0]
        self.assertNotIn(token, urlparse(sent_links[0][1]).query)
        with self.app.app_context():
            reset_record = PasswordReset.query.filter_by(used=False).one()
            self.assertEqual(reset_record.token, hashlib.sha256(token.encode("utf-8")).hexdigest())
            self.assertNotEqual(reset_record.token, token)

        reset = self.client.post("/api/password-reset/confirm", json={"token": token, "password": "new-password-123"})
        self.assertEqual(reset.status_code, 200)
        reused = self.client.post("/api/password-reset/confirm", json={"token": token, "password": "another-password"})
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(self.client.post("/api/login", json={"username": "alice", "password": "new-password-123"}).status_code, 200)

        with patch("backend.app_factory._send_password_reset_email", side_effect=lambda recipient, link: sent_links.append((recipient, link))):
            self.client.post("/api/password-reset/request", json={"identifier": "alice"})
        expired_token = parse_qs(urlparse(sent_links[-1][1]).fragment)["reset_token"][0]
        with self.app.app_context():
            expired_reset = PasswordReset.query.filter_by(used=False).one()
            expired_reset.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.session.commit()
        expired = self.client.post("/api/password-reset/confirm", json={"token": expired_token, "password": "expired-password"})
        self.assertEqual(expired.status_code, 400)

    def test_password_reset_email_failure_does_not_expose_or_keep_reset_token(self):
        self.register()
        with patch("backend.app_factory._send_password_reset_email", side_effect=OSError("SMTP unavailable")):
            response = self.client.post("/api/password-reset/request", json={"identifier": "alice"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.get_json())
        with self.app.app_context():
            self.assertEqual(PasswordReset.query.count(), 0)

    def test_task_priority_and_due_date_are_supported(self):
        self.register()
        self.login()

        response = self.client.post("/api/tasks", json={
            "title": "Ship release",
            "priority": "High",
            "due_date": "2026-10-15",
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["priority"], "High")
        self.assertEqual(response.get_json()["due_date"], "2026-10-15")

    def test_overdue_task_notifications_are_created_once(self):
        self.register()
        self.login()
        today = datetime.now(timezone.utc).date()
        overdue_date = (today - timedelta(days=1)).isoformat()

        overdue_task = self.client.post("/api/tasks", json={
            "title": "Review overdue release",
            "due_date": overdue_date,
        })
        completed_task = self.client.post("/api/tasks", json={
            "title": "Completed overdue task",
            "status": "Completed",
            "due_date": overdue_date,
        })
        self.assertEqual(overdue_task.status_code, 201)
        self.assertEqual(completed_task.status_code, 201)

        self.assertEqual(create_overdue_reminders(self.app), 1)
        self.assertEqual(create_overdue_reminders(self.app), 0)
        reminders = [item for item in self.client.get("/api/notifications").get_json() if item["kind"] == "warning"]
        self.assertEqual(len(reminders), 1)
        self.assertIn("Review overdue release", reminders[0]["message"])
        self.assertIn(overdue_date, reminders[0]["message"])

    def test_task_description_and_assignee_are_supported(self):
        self.register()
        self.login()

        response = self.client.post("/api/tasks", json={
            "title": "Review dashboard",
            "description": "Check the responsive layout before release.",
            "assignee": "Priya S",
        })

        self.assertEqual(response.status_code, 201)
        task_id = response.get_json()["id"]
        self.assertEqual(response.get_json()["description"], "Check the responsive layout before release.")
        self.assertEqual(response.get_json()["assignee"], "Priya S")

        updated = self.client.patch(f"/api/tasks/{task_id}", json={
            "description": "Layout review completed.",
            "assignee": "Rahul K",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["description"], "Layout review completed.")
        self.assertEqual(updated.get_json()["assignee"], "Rahul K")

    def test_legacy_tasks_are_migrated_to_first_registered_user(self):
        temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(temporary_directory.name) / "legacy.db"
        connection = sqlite3.connect(database_path)
        connection.executescript(
            "CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, password VARCHAR(255) NOT NULL);"
            "CREATE TABLE task (id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, status VARCHAR(50));"
            "INSERT INTO task (title, status) VALUES ('Existing task', 'Pending');"
        )
        connection.close()

        legacy_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "legacy-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        })
        legacy_client = legacy_app.test_client()
        legacy_client.post("/api/register", json={
            "username": "first-user",
            "password": "password-123",
            "email": "first-user@example.com",
        })
        legacy_client.post("/api/login", json={
            "username": "first-user",
            "password": "password-123",
        })

        tasks = legacy_client.get("/api/tasks").get_json()
        self.assertEqual([task["title"] for task in tasks], ["Existing task"])

        with legacy_app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        temporary_directory.cleanup()


if __name__ == "__main__":
    unittest.main()