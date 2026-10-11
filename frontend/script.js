const API_URL = "/api/tasks";
let cachedTasks = [];
const selectedTaskIds = new Set();

function openTaskModal() {
    document.getElementById("taskModal").classList.remove("hidden");
    document.getElementById("taskModal").setAttribute("aria-hidden", "false");
}

function closeTaskModal() {
    document.getElementById("taskModal").classList.add("hidden");
    document.getElementById("taskModal").setAttribute("aria-hidden", "true");
    document.getElementById("taskCreateForm").reset();
}

async function submitTaskForm(event) {
    event.preventDefault();
    const title = document.getElementById("taskFormTitle").value.trim();
    const priority = document.getElementById("taskFormPriority").value;
    const dueDate = document.getElementById("taskFormDueDate").value || null;
    const status = document.getElementById("taskFormStatus").value;
    const description = document.getElementById("taskFormDescription").value.trim() || null;
    const assigneeId = Number(document.getElementById("taskFormAssignee").value) || null;

    if (!title) {
        document.getElementById("taskMessage").textContent = "Enter a task title.";
        return;
    }

    try {
        await sendTaskRequest(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, description, assignee_id: assigneeId, priority, due_date: dueDate, status })
        });
        closeTaskModal();
        document.getElementById("taskMessage").textContent = "Task added.";
        await loadTasks();
        if (canManageEmployees) await loadWorkload();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

async function loadTasks() {
    try {
        const response = await fetch(API_URL);
        if (response.status === 401) {
            window.location.replace("login.html");
            return;
        }
        if (!response.ok) {
            throw new Error("Could not load tasks.");
        }
        cachedTasks = await response.json();
        renderTasks();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

function renderTasks() {
    const selectedStatus = document.getElementById("statusFilter").value;
    const searchTerm = document.getElementById("taskSearch").value.trim().toLowerCase();
    const visibleTasks = cachedTasks.filter(task => {
        const matchesStatus = selectedStatus === "All" || task.status === selectedStatus;
        const matchesSearch = task.title.toLowerCase().includes(searchTerm);
        return matchesStatus && matchesSearch;
    });

    const lanes = {
        "To Do": document.getElementById("todoTasks"),
        "Pending": document.getElementById("todoTasks"),
        "In Progress": document.getElementById("progressTasks"),
        "Review": document.getElementById("reviewTasks"),
        "Completed": document.getElementById("completedTasks"),
    };
    Object.values(lanes).forEach(lane => lane.replaceChildren());
    const counts = { "To Do": 0, "In Progress": 0, "Review": 0, "Completed": 0 };
    visibleTasks.forEach(task => { counts[task.status === "Pending" ? "To Do" : task.status] = (counts[task.status === "Pending" ? "To Do" : task.status] || 0) + 1; });
    document.getElementById("todoCount").textContent = counts["To Do"];
    document.getElementById("progressCount").textContent = counts["In Progress"];
    document.getElementById("reviewCount").textContent = counts.Review;
    document.getElementById("completedCount").textContent = counts.Completed;
    document.querySelectorAll(".workflow-board .board-lane").forEach(lane => { lane.hidden = selectedStatus !== "All" && lane.dataset.status !== selectedStatus; });
    document.getElementById("taskSummary").textContent =
        `${cachedTasks.length} total · ${cachedTasks.filter(task => task.status !== "Completed").length} active · ${cachedTasks.filter(task => task.status === "Completed").length} completed`;
    updateTaskMetrics();

    if (visibleTasks.length === 0) {
        const emptyLane = lanes[selectedStatus] || lanes["To Do"];
        const emptyState = createEmptyState(searchTerm || selectedStatus !== "All"
            ? "No tasks match your filters."
            : "No tasks yet. Add your first task above.");
        emptyLane.appendChild(emptyState);
        return;
    }

    visibleTasks.forEach(task => {
        const taskCard = document.createElement("article");
        const selectBox = document.createElement("input");
        const title = document.createElement("h4");
        const description = document.createElement("p");
        const meta = document.createElement("div");
        const priority = document.createElement("span");
        const dueDate = document.createElement("small");
        const assigneeWrap = document.createElement("div");
        const assigneeAvatar = document.createElement("span");
        const assigneeName = document.createElement("small");
        const actions = document.createElement("div");
        const statusButton = document.createElement("button");
        const editButton = document.createElement("button");
        const deleteButton = document.createElement("button");
        const commentButton = document.createElement("button");
        const taskList = lanes[task.status] || lanes["To Do"];

        taskCard.className = `board-task${task.status === "Completed" ? " is-completed" : ""}`;
        taskCard.draggable = true;
        taskCard.addEventListener("dragstart", event => event.dataTransfer.setData("text/task-id", String(task.id)));
        selectBox.type = "checkbox";
        selectBox.className = "task-select";
        selectBox.checked = selectedTaskIds.has(task.id);
        selectBox.setAttribute("aria-label", `Select ${task.title}`);
        selectBox.addEventListener("change", () => {
            if (selectBox.checked) selectedTaskIds.add(task.id); else selectedTaskIds.delete(task.id);
            updateBulkToolbar();
        });
        title.textContent = task.title;
        description.className = "task-description";
        description.textContent = task.description || "No description";
        meta.className = "task-meta";
        priority.className = `priority-pill priority-${(task.priority || "Medium").toLowerCase()}`;
        priority.textContent = task.priority || "Medium";
        dueDate.textContent = task.due_date ? `Due ${task.due_date}` : "No due date";
        assigneeWrap.className = "assignee-wrap";
        if (task.assignee) {
            const initials = task.assignee.split(" ").map(part => part[0]).join("").slice(0, 2).toUpperCase();
            assigneeAvatar.className = "assignee-avatar";
            assigneeAvatar.textContent = initials;
            assigneeName.textContent = task.assignee;
            assigneeWrap.append(assigneeAvatar, assigneeName);
        }
        actions.className = "task-card-actions";
        statusButton.className = "task-action task-action-primary";
        const employeeStatusSteps = {
            "Pending": ["In Progress", "Start task"],
            "To Do": ["In Progress", "Start task"],
            "In Progress": ["Review", "Send to review"],
            "Review": ["Completed", "Complete task"],
            "Completed": ["Pending", "Reopen"],
        };
        const [nextStatus, statusLabel] = employeeStatusSteps[task.status] || employeeStatusSteps.Pending;
        statusButton.textContent = canManageTasks
            ? (task.status === "Completed" ? "Reopen" : "Complete")
            : statusLabel;
        statusButton.addEventListener("click", () => updateTaskStatus(
            task.id,
            canManageTasks ? (task.status === "Completed" ? "Pending" : "Completed") : nextStatus
        ));
        editButton.className = "task-action";
        editButton.textContent = "Edit";
        editButton.addEventListener("click", () => editTask(task.id, task.title, task.priority || "Medium", task.due_date || ""));
        deleteButton.className = "task-action task-action-delete";
        deleteButton.textContent = "Delete";
        deleteButton.addEventListener("click", () => deleteTask(task.id));
        commentButton.className = "task-action";
        commentButton.textContent = `Comments (${task.comment_count || 0})`;
        commentButton.addEventListener("click", () => openComments(task.id, task.title));

        meta.append(priority, dueDate);
        if (canManageTasks) actions.append(editButton);
        actions.append(statusButton, commentButton);
        if (canManageTasks) actions.append(deleteButton);
        taskCard.append(...(canManageTasks ? [selectBox] : []), title, description, meta, assigneeWrap, actions);
        taskList.appendChild(taskCard);
    });
}

function updateBulkToolbar() {
    document.getElementById("selectedTaskCount").textContent = `${selectedTaskIds.size} selected`;
    document.getElementById("bulkToolbar").classList.toggle("has-selection", selectedTaskIds.size > 0);
}

async function applyBulkUpdate() {
    if (!selectedTaskIds.size) return;
    const status = document.getElementById("bulkStatus").value || undefined;
    const priority = document.getElementById("bulkPriority").value || undefined;
    if (!status && !priority) return;
    await sendTaskRequest(`${API_URL}/bulk`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [...selectedTaskIds], status, priority }) });
    selectedTaskIds.clear();
    await loadTasks();
    if (canManageEmployees) await loadWorkload();
}

async function deleteSelectedTasks() {
    if (!selectedTaskIds.size || !window.confirm("Delete selected tasks?")) return;
    await sendTaskRequest(`${API_URL}/bulk`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [...selectedTaskIds] }) });
    selectedTaskIds.clear();
    await loadTasks();
    if (canManageEmployees) await loadWorkload();
}

function createEmptyState(message) {
    const emptyState = document.createElement("p");
    emptyState.className = "lane-empty";
    emptyState.textContent = message;
    return emptyState;
}

function updateTaskMetrics() {
    const pending = cachedTasks.filter(task => task.status !== "Completed").length;
    const completed = cachedTasks.filter(task => task.status === "Completed").length;
    const total = cachedTasks.length;
    const completion = total ? Math.round((completed / total) * 100) : 0;

    document.getElementById("metricTotal").textContent = total;
    document.getElementById("metricPending").textContent = pending;
    document.getElementById("metricCompleted").textContent = completed;
    document.getElementById("metricRate").textContent = `${completion}%`;
    document.getElementById("progressRingValue").textContent = `${completion}%`;
    document.getElementById("progressRing").style.setProperty("--progress", `${completion}%`);
    document.getElementById("progressCompletedLabel").textContent = completed;
    document.getElementById("progressPendingLabel").textContent = pending;
}

async function addTask(event) {
    event.preventDefault();
    const titleInput = document.getElementById("taskTitle");
    const title = titleInput.value.trim();
    if (!title) {
        document.getElementById("taskMessage").textContent = "Enter a task title.";
        return;
    }

    try {
        await sendTaskRequest(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title })
        });
        titleInput.value = "";
        document.getElementById("taskMessage").textContent = "Task added.";
        await loadTasks();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

async function deleteTask(id) {
    if (!window.confirm("Delete this task? This cannot be undone.")) {
        return;
    }
    try {
        await sendTaskRequest(`${API_URL}/${id}`, { method: "DELETE" });
        document.getElementById("taskMessage").textContent = "Task deleted.";
        await loadTasks();
        if (canManageEmployees) await loadWorkload();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

async function updateTaskStatus(id, status) {
    try {
        await sendTaskRequest(`${API_URL}/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status })
        });
        document.getElementById("taskMessage").textContent = "Task status updated.";
        await loadTasks();
        if (canManageEmployees) await loadWorkload();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

async function editTask(id, currentTitle, currentPriority, currentDueDate) {
    const title = window.prompt("Edit task title", currentTitle);
    if (title === null || !title.trim()) {
        return;
    }
    const priority = window.prompt("Set priority (High, Medium, Low)", currentPriority) || currentPriority;
    const dueDate = window.prompt("Set due date (YYYY-MM-DD) or leave blank", currentDueDate || "") || "";
    try {
        await sendTaskRequest(`${API_URL}/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title.trim(),
                priority: ["High", "Medium", "Low"].includes(priority) ? priority : currentPriority,
                due_date: dueDate || null,
            })
        });
        document.getElementById("taskMessage").textContent = "Task updated.";
        await loadTasks();
        if (canManageEmployees) await loadWorkload();
    } catch (error) {
        document.getElementById("taskMessage").textContent = error.message;
    }
}

async function sendTaskRequest(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
        window.location.replace("login.html");
        throw new Error("Your session has expired. Please sign in again.");
    }
    if (!response.ok) {
        throw new Error(data.message || "The task request failed.");
    }
    return data;
}
