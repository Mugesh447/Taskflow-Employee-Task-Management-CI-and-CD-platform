import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app import app as default_app, create_app, db


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

    def register(self, username="alice", password="password-123"):
        return self.client.post("/api/register", json={
            "username": username,
            "password": password,
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

    def test_home_selects_public_or_authenticated_page(self):
        with self.client.get("/") as response:
            public_page = response.get_data()
        self.assertIn(b"Create account", public_page)
        self.register()
        self.login()
        with self.client.get("/") as response:
            dashboard_page = response.get_data()
        self.assertIn(b"Your task list", dashboard_page)

    def test_registration_validation_and_session_lifecycle(self):
        self.assertEqual(self.register(password="short").status_code, 400)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.login(password="wrong-password").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/session").get_json()["username"], "alice")
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)

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
        reset_request = self.client.post("/api/password-reset/request", json={"username": "alice"})
        self.assertEqual(reset_request.status_code, 200)
        reset = self.client.post("/api/password-reset/confirm", json={"token": reset_request.get_json()["token"], "password": "new-password-123"})
        self.assertEqual(reset.status_code, 200)
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