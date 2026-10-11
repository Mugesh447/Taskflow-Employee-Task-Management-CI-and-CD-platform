import os

try:
    from .app_factory import Task, User, create_app, db
    from .reminder_scheduler import start_reminder_scheduler
except ImportError:
    from app_factory import Task, User, create_app, db
    from reminder_scheduler import start_reminder_scheduler


app = create_app()


if __name__ == "__main__":
    start_reminder_scheduler(app)
    app.run(host="127.0.0.1", port=5001, debug=False)
elif os.environ.get("TASKFLOW_START_REMINDER_SCHEDULER", "false").lower() == "true":
    start_reminder_scheduler(app)