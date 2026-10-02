from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app_factory import ActivityLog, Employee, Notification, Task, TaskComment, User, create_app, db


app = create_app()


with app.app_context():
    username = "demoadmin"
    password = "demo12345"

    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(
            username=username,
            password=generate_password_hash(password),
            role="Admin",
        )
        db.session.add(user)
        db.session.flush()

    existing_tasks = {task.title for task in Task.query.filter_by(user_id=user.id).all()}

    sample_tasks = [
        {
            "title": "Launch sprint planning",
            "status": "In Progress",
            "priority": "High",
            "assignee": "Arun",
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "description": "Finalize sprint goals, assign owners, and review dependencies for the next release.",
        },
        {
            "title": "Prepare deployment checklist",
            "status": "Pending",
            "priority": "Medium",
            "assignee": "Meena",
            "due_date": (date.today() + timedelta(days=4)).isoformat(),
            "description": "Validate environment variables, Docker config, backup plan, and release readiness.",
        },
        {
            "title": "Review QA bug backlog",
            "status": "Review",
            "priority": "High",
            "assignee": "Karthik",
            "due_date": (date.today() + timedelta(days=1)).isoformat(),
            "description": "Prioritize defect fixes and ensure release blockers are resolved before the next build.",
        },
        {
            "title": "Update onboarding docs",
            "status": "Completed",
            "priority": "Low",
            "assignee": "Sathya",
            "due_date": (date.today() - timedelta(days=1)).isoformat(),
            "description": "Document the step-by-step onboarding checklist for newly added team members.",
        },
        {
            "title": "Prepare customer feedback summary",
            "status": "Pending",
            "priority": "Medium",
            "assignee": "Raja",
            "due_date": (date.today() + timedelta(days=6)).isoformat(),
            "description": "Summarize the latest customer feedback and convert it into product improvement tasks.",
        },
    ]

    for index, item in enumerate(sample_tasks):
        if item["title"] in existing_tasks:
            continue

        task = Task(
            title=item["title"],
            status=item["status"],
            priority=item["priority"],
            assignee=item["assignee"],
            due_date=item["due_date"],
            description=item["description"],
            position=index * 10,
            user_id=user.id,
        )
        db.session.add(task)
        db.session.flush()

        db.session.add(
            TaskComment(
                body=f"Follow-up note for {item['title']}.",
                task_id=task.id,
                user_id=user.id,
            )
        )

        db.session.add(
            ActivityLog(
                message=f"Demo task created: {item['title']}",
                task_id=task.id,
                user_id=user.id,
            )
        )

        db.session.add(
            Notification(
                message=f"Demo reminder: {item['title']}",
                kind="info",
                user_id=user.id,
            )
        )

    if not Employee.query.filter_by(user_id=user.id).count():
        employees = [
            ("Arun", "arun@taskflow.local", "Project Lead", "Active"),
            ("Meena", "meena@taskflow.local", "DevOps Engineer", "Active"),
            ("Karthik", "karthik@taskflow.local", "QA Analyst", "Active"),
            ("Sathya", "sathya@taskflow.local", "Documentation Lead", "Active"),
            ("Raja", "raja@taskflow.local", "Product Analyst", "Active"),
        ]
        for name, email, role, status in employees:
            db.session.add(
                Employee(
                    name=name,
                    email=email,
                    role=role,
                    status=status,
                    user_id=user.id,
                )
            )

    db.session.commit()
    print("Demo user created: demoadmin / demo12345")
    print(f"Demo tasks added for user_id={user.id}")
