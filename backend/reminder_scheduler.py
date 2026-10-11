import os
import threading
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

try:
    from .app_factory import Employee, Notification, Task, db
except ImportError:
    from app_factory import Employee, Notification, Task, db


_scheduler_lock = threading.Lock()
_scheduler_started = False


def create_overdue_reminders(app):
    created = 0
    today = datetime.now(timezone.utc).date().isoformat()
    with app.app_context():
        overdue_tasks = Task.query.filter(
            Task.workspace_id.isnot(None),
            Task.due_date.isnot(None),
            Task.due_date < today,
            Task.status != "Completed",
        ).all()

        for task in overdue_tasks:
            recipient_ids = {task.user_id} if task.user_id else set()
            employee = db.session.get(Employee, task.assignee_id) if task.assignee_id else None
            if employee and employee.linked_user_id:
                recipient_ids.add(employee.linked_user_id)

            for recipient_id in recipient_ids:
                dedupe_key = f"overdue:{task.workspace_id}:{task.id}:{task.due_date}:{recipient_id}"
                if Notification.query.filter_by(dedupe_key=dedupe_key).first() is not None:
                    continue

                legacy_reminder = Notification.query.filter_by(
                    user_id=recipient_id,
                    kind="warning",
                ).filter(Notification.message.startswith(f"Overdue task #{task.id}:")).first()
                if legacy_reminder is not None:
                    legacy_reminder.dedupe_key = dedupe_key
                    try:
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                    continue

                db.session.add(Notification(
                    message=f"Overdue task #{task.id}: {task.title[:170]} (due {task.due_date})",
                    kind="warning",
                    user_id=recipient_id,
                    dedupe_key=dedupe_key,
                ))
                try:
                    db.session.commit()
                    created += 1
                except IntegrityError:
                    db.session.rollback()

    return created


def _run_scheduler(app, interval_seconds, stop_event):
    while not stop_event.is_set():
        try:
            create_overdue_reminders(app)
        except Exception:
            app.logger.exception("TaskFlow overdue reminder check failed")
        if stop_event.wait(interval_seconds):
            break


def start_reminder_scheduler(app, interval_seconds=None):
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    if interval_seconds is None:
        try:
            interval_seconds = max(30, int(os.environ.get("TASKFLOW_REMINDER_INTERVAL_SECONDS", "300")))
        except ValueError:
            interval_seconds = 300

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_scheduler,
        args=(app, interval_seconds, stop_event),
        name="taskflow-overdue-reminders",
        daemon=True,
    )
    thread.start()