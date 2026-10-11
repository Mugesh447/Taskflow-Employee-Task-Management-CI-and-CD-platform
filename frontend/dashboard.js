let liveRefreshInProgress = false;
let canManageEmployees = false;
let canManageTasks = false;
let currentAccountRole = "";

async function initializeDashboard() {
    try {
        if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js");
        const response = await fetch("/api/session");
        if (!response.ok) {
            window.location.replace("login.html");
            return;
        }

        const user = await response.json();
        document.getElementById("settingRecoveryEmail").value = user.recovery_email || "";
        canManageEmployees = ["Admin", "Manager"].includes(user.role);
        canManageTasks = canManageEmployees;
        currentAccountRole = user.role;
        document.querySelectorAll(".manager-only").forEach(element => { element.hidden = !canManageEmployees; });
        document.querySelectorAll(".admin-only").forEach(element => { element.hidden = user.role !== "Admin"; });
        document.getElementById("welcomeUser").textContent = `Welcome, ${user.username}`;
        const roleBadge = document.getElementById("accountRoleBadge");
        roleBadge.dataset.userId = user.id;
        roleBadge.textContent = `${user.role} account`;
        roleBadge.classList.add(user.role === "Admin" ? "success" : "running");
        updateLiveClock();
        window.setInterval(updateLiveClock, 1000);
        startRealtimeEvents();
        setupWorkflowBoard();
        checkServiceHealth();
        loadSettings();
        await refreshVisibleDashboard();
        updateLiveSyncStatus("Live updates · synced now", true);
        window.setInterval(refreshLiveDashboard, 5000);
    } catch {
        document.getElementById("taskMessage").textContent =
            "Could not connect to TaskFlow. Refresh to try again.";
    }
}

function setupWorkflowBoard() {
    document.querySelectorAll(".workflow-board .board-lane").forEach(lane => {
        lane.addEventListener("dragover", event => event.preventDefault());
        lane.addEventListener("drop", async event => {
            event.preventDefault();
            const taskId = event.dataTransfer.getData("text/task-id");
            if (!taskId) return;
            await updateTaskStatus(Number(taskId), lane.dataset.status);
        });
    });
}

function startRealtimeEvents() {
    if (!window.EventSource) return;
    const events = new EventSource("/api/events");
    events.onmessage = async event => {
        const payload = JSON.parse(event.data);
        if (payload.type === "notification") {
            await Promise.all([
                loadTasks(),
                loadNotifications(),
                loadActivity(),
                ...(canManageEmployees ? [loadWorkload()] : []),
            ]);
            updateLiveSyncStatus("Live push · updated now", true);
        }
    };
    events.onerror = () => updateLiveSyncStatus("Live push · reconnecting...", false);
}

function updateLiveClock() {
    document.getElementById("currentDate").textContent = new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    }).format(new Date());
}

async function refreshLiveDashboard() {
    if (liveRefreshInProgress || !document.getElementById("settingAutoRefresh")?.checked) return;
    liveRefreshInProgress = true;
    updateLiveSyncStatus("Syncing live updates...", false);
    try {
        await refreshVisibleDashboard();
        updateLiveSyncStatus(`Live updates · synced ${new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date())}`, true);
    } catch {
        updateLiveSyncStatus("Live updates · reconnecting...", false);
    } finally {
        liveRefreshInProgress = false;
    }
}

async function refreshVisibleDashboard() {
    const requests = [
        loadTasks(),
        loadNotifications(),
        loadAnalytics(),
        loadCalendar(),
        loadActivity(),
    ];
    if (canManageEmployees) {
        requests.push(loadEmployees(), loadPipelines(), loadWorkload());
    }
    if (currentAccountRole === "Admin") requests.push(loadAdminUsers());
    await Promise.all(requests);
}

function updateLiveSyncStatus(message, connected) {
    const status = document.getElementById("liveSyncStatus");
    const dot = document.querySelector(".live-dot");
    if (status) status.textContent = message;
    if (dot) dot.classList.toggle("is-offline", !connected);
}

async function loadAnalytics() {
    const query = new URLSearchParams();
    const from = document.getElementById("reportFrom")?.value;
    const to = document.getElementById("reportTo")?.value;
    if (from) query.set("from", from);
    if (to) query.set("to", to);
    const response = await fetch(`/api/analytics?${query}`);
    if (!response.ok) throw new Error("Could not load analytics.");
    const data = await response.json();
    document.getElementById("analyticsTotal").textContent = data.total;
    document.getElementById("analyticsCompleted").textContent = data.completed;
    document.getElementById("analyticsOverdue").textContent = data.due.overdue;
    const maximum = Math.max(...Object.values(data.priority), 1);
    ["High", "Medium", "Low"].forEach(priority => {
        const bar = document.getElementById(`${priority.toLowerCase()}PriorityBar`);
        bar.style.width = `${Math.round((data.priority[priority] / maximum) * 100)}%`;
        bar.textContent = data.priority[priority];
    });
}

async function loadCalendar() {
    const response = await fetch("/api/calendar");
    if (!response.ok) throw new Error("Could not load calendar.");
    const tasks = await response.json();
    const today = new Date();
    const todayKey = today.toISOString().slice(0, 10);
    const monthKey = todayKey.slice(0, 7);
    const weekEnd = new Date(today);
    weekEnd.setDate(today.getDate() + 7);
    const visibleTasks = tasks.filter(task => {
        if (calendarView === "day") return task.due_date === todayKey;
        if (calendarView === "week") return task.due_date >= todayKey && task.due_date <= weekEnd.toISOString().slice(0, 10);
        return task.due_date.startsWith(monthKey);
    });
    renderCalendarGrid(tasks);
    document.getElementById("calendarList").innerHTML = visibleTasks.slice(0, 12).map(task => `<div class="calendar-item"><time>${escapeHtml(task.due_date)}</time><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.status)} · ${escapeHtml(task.priority)}</small></div></div>`).join("") || `<p class="lane-empty">No tasks in the ${calendarView} view.</p>`;
}

let calendarView = "month";

function setCalendarView(view) {
    calendarView = view;
    loadCalendar();
}

function renderCalendarGrid(tasks) {
    const today = new Date();
    const dates = [];
    if (calendarView === "day") {
        dates.push(new Date(today));
    } else if (calendarView === "week") {
        for (let index = 0; index < 7; index += 1) {
            const date = new Date(today);
            date.setDate(today.getDate() + index);
            dates.push(date);
        }
    } else {
        const first = new Date(today.getFullYear(), today.getMonth(), 1);
        const startOffset = first.getDay();
        const gridStart = new Date(today.getFullYear(), today.getMonth(), 1 - startOffset);
        for (let index = 0; index < 42; index += 1) {
            const date = new Date(gridStart);
            date.setDate(gridStart.getDate() + index);
            dates.push(date);
        }
    }
    document.getElementById("calendarGrid").innerHTML = dates.map(date => {
        const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
        const tasksForDay = tasks.filter(task => task.due_date === key);
        return `<div class="calendar-day${key === new Date().toISOString().slice(0, 10) ? " today" : ""}"><time>${date.getDate()}</time>${tasksForDay.slice(0, 2).map(task => `<span title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</span>`).join("")}</div>`;
    }).join("");
}

async function loadActivity() {
    const response = await fetch("/api/activity");
    if (!response.ok) throw new Error("Could not load activity.");
    const activity = await response.json();
    document.getElementById("activityList").innerHTML = activity.slice(0, 6).map(item => `<div class="activity-item"><i></i><div><strong>${escapeHtml(item.message)}</strong><small>${new Date(item.created_at).toLocaleString()}</small></div></div>`).join("") || "<p class=\"lane-empty\">No activity yet.</p>";
}

let activeCommentTaskId = null;

async function openComments(taskId, title) {
    activeCommentTaskId = taskId;
    document.getElementById("commentsTitle").textContent = `Comments · ${title}`;
    document.getElementById("commentsModal").classList.remove("hidden");
    document.getElementById("commentsModal").setAttribute("aria-hidden", "false");
    await Promise.all([loadComments(), loadAttachments()]);
}

async function loadComments() {
    const response = await fetch(`/api/tasks/${activeCommentTaskId}/comments`);
    if (!response.ok) return;
    const comments = await response.json();
    document.getElementById("commentsList").innerHTML = comments.map(comment => `<article class="comment-item"><strong>${escapeHtml(comment.author)}</strong><p>${escapeHtml(comment.body)}</p><small>${new Date(comment.created_at).toLocaleString()}</small></article>`).join("") || "<p class=\"lane-empty\">No comments yet.</p>";
}

async function submitComment(event) {
    event.preventDefault();
    const input = document.getElementById("commentBody");
    const response = await fetch(`/api/tasks/${activeCommentTaskId}/comments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: input.value.trim() }) });
    if (response.ok) {
        input.value = "";
        await Promise.all([loadComments(), loadTasks(), loadNotifications(), loadActivity()]);
    }
}

async function uploadAttachment(event) {
    event.preventDefault();
    const file = document.getElementById("attachmentFile").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/api/tasks/${activeCommentTaskId}/attachments/upload`, { method: "POST", body: form });
    if (response.ok) {
        document.getElementById("attachmentFile").value = "";
        await loadAttachments();
    }
}

async function loadAttachments() {
    const response = await fetch(`/api/tasks/${activeCommentTaskId}/attachments`);
    if (!response.ok) return;
    const attachments = await response.json();
    document.getElementById("attachmentList").innerHTML = attachments.map(item => `<span class="attachment-item"><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a><button type="button" onclick="deleteAttachment(${item.id})">×</button></span>`).join("") || "";
}

async function deleteAttachment(id) {
    const response = await fetch(`/api/attachments/${id}`, { method: "DELETE" });
    if (response.ok) await loadAttachments();
}

function closeComments() {
    document.getElementById("commentsModal").classList.add("hidden");
    document.getElementById("commentsModal").setAttribute("aria-hidden", "true");
    activeCommentTaskId = null;
}

async function loadAdminUsers() {
    const response = await fetch("/api/users");
    if (!response.ok) return;
    const users = await response.json();
    document.getElementById("adminUserList").innerHTML = users.map(user => `<div class="admin-user-row"><span><strong>${escapeHtml(user.username)}</strong><small>${escapeHtml(user.role)} · ${user.two_factor_enabled ? "2FA enabled" : "2FA off"}</small></span><select aria-label="Access role for ${escapeHtml(user.username)}" onchange="updateUserRole(${user.id}, this.value)">${user.role === "Manager" ? `<option selected>Manager</option>` : ""}<option ${user.role === "Admin" ? "selected" : ""}>Admin</option><option ${user.role === "Employee" ? "selected" : ""}>Employee</option></select></div>`).join("");
}

async function updateUserRole(id, role) {
    const response = await fetch(`/api/users/${id}/role`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        document.getElementById("monitoringMessage").textContent = data.message || "Could not update account access.";
        await loadAdminUsers();
        return;
    }
    document.getElementById("monitoringMessage").textContent = `${data.username} now has ${data.role} access.`;
    if (data.id === Number(document.getElementById("accountRoleBadge").dataset.userId)) {
        window.location.reload();
        return;
    }
    await loadAdminUsers();
}

async function loadMonitoringMetrics() {
    const response = await fetch("/api/metrics");
    const data = await response.json();
    document.getElementById("monitoringMessage").textContent = response.ok ? `Requests: ${data.requests.count} · Errors: ${data.requests.errors} · Tasks: ${data.tasks}` : data.message;
}

async function createDatabaseBackup() {
    const response = await fetch("/api/admin/backup", { method: "POST" });
    const data = await response.json();
    document.getElementById("monitoringMessage").textContent = response.ok ? "Workspace export downloaded." : data.message;
    if (response.ok) window.location.assign(data.download_url);
}

async function loadEmployees() {
    const response = await fetch("/api/employees");
    if (!response.ok) throw new Error("Could not load employees.");
    const employees = await response.json();
    const counts = { Active: 0, "On leave": 0, Inactive: 0 };
    employees.forEach(employee => { counts[employee.status] = (counts[employee.status] || 0) + 1; });
    window.taskflowEmployees = employees;
    const assigneeSelect = document.getElementById("taskFormAssignee");
    assigneeSelect.innerHTML = `<option value="">Unassigned</option>${employees.map(employee => `<option value="${employee.id}">${escapeHtml(employee.name)}</option>`).join("")}`;
    document.getElementById("employeeGrid").innerHTML = `
        <article class="employee-stat-card blue"><span class="employee-icon">👥</span><div><h3>${employees.length}</h3><p>Total employees</p></div></article>
        <article class="employee-stat-card green"><span class="employee-icon">✅</span><div><h3>${counts.Active}</h3><p>Active</p></div></article>
        <article class="employee-stat-card amber"><span class="employee-icon">🧳</span><div><h3>${counts["On leave"]}</h3><p>On leave</p></div></article>
        <article class="employee-stat-card red"><span class="employee-icon">⏳</span><div><h3>${counts.Inactive}</h3><p>Inactive</p></div></article>
        <div class="employee-records">${employees.map(employee => {
            const initials = employee.name.split(" ").map(part => part[0]).join("").slice(0, 2).toUpperCase();
            return `
            <div class="employee-record">
                <div class="employee-main">
                    <span class="employee-avatar-mini">${escapeHtml(initials)}</span>
                    <div>
                        <strong>${escapeHtml(employee.name)}</strong>
                        <small>${escapeHtml(employee.role)} · ${escapeHtml(employee.account_role || "Employee")} access · ${escapeHtml(employee.email)}</small>
                    </div>
                </div>
                <span class="status-tag ${employee.status === "Active" ? "success" : "running"}">${escapeHtml(employee.status)}</span>
                ${canManageEmployees ? `<div class="employee-actions">
                    <button class="task-action" onclick="openEmployeeDetails(${employee.id})">View</button>
                    ${employee.account_linked ? `<span class="status-tag success">Joined</span>` : `<button class="task-action" onclick="inviteEmployee(${employee.id})">Invite</button>`}
                    <button class="task-action" onclick="openEmployeeModal(${employee.id})">Edit</button>
                    <button class="task-action task-action-delete" onclick="deleteEmployee(${employee.id})">Delete</button>
                </div>` : `<div class="employee-actions"><button class="task-action" onclick="openEmployeeDetails(${employee.id})">View</button></div>`}
            </div>`;
        }).join("") || `<p class="lane-empty">No employees yet. Add your first employee.</p>`}</div>`;
}

async function loadWorkload() {
    const response = await fetch("/api/workload");
    if (!response.ok) throw new Error("Could not load team workload.");
    const employees = await response.json();
    document.getElementById("workloadList").innerHTML = employees.map(employee => `
        <tr>
            <th scope="row"><strong>${escapeHtml(employee.name)}</strong><small>${escapeHtml(employee.role)}</small></th>
            <td>${employee.active_tasks}</td>
            <td><span class="workload-number${employee.overdue_tasks ? " is-overdue" : ""}">${employee.overdue_tasks}</span></td>
            <td>${employee.due_soon_tasks}</td>
        </tr>`).join("") || `<tr><td colspan="4" class="workload-empty">No employees in this workspace yet.</td></tr>`;
}

async function inviteEmployee(id) {
    if (!canManageEmployees) {
        document.getElementById("employeeMessage").textContent = "Only workspace Admins and Managers can create invitations.";
        return;
    }
    try {
        const response = await fetch(`/api/employees/${id}/invite`, { method: "POST" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            document.getElementById("employeeMessage").textContent = data.message || "Could not create invitation.";
            return;
        }
        document.getElementById("employeeInviteUrl").value = data.invite_url;
        document.getElementById("employeeInviteDescription").textContent =
            `Created for ${data.email} with ${data.account_role} account access. Share this link only with the invited employee.`;
        document.getElementById("employeeInviteExpiry").textContent =
            `Expires ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(data.expires_at))}.`;
        document.getElementById("employeeInviteMessage").textContent = "";
        document.getElementById("copyEmployeeInviteButton").textContent = "Copy invitation link";
        document.getElementById("employeeInviteModal").classList.remove("hidden");
        document.getElementById("employeeInviteModal").setAttribute("aria-hidden", "false");
        document.getElementById("employeeInviteUrl").focus();
    } catch {
        document.getElementById("employeeMessage").textContent = "Could not connect to TaskFlow. Check your connection and try again.";
    }
}

async function copyEmployeeInvitation() {
    const inviteInput = document.getElementById("employeeInviteUrl");
    const message = document.getElementById("employeeInviteMessage");
    const invitationUrl = inviteInput.value;
    if (!invitationUrl) {
        message.textContent = "Generate a new invitation link before copying.";
        return;
    }
    try {
        await navigator.clipboard.writeText(invitationUrl);
        message.textContent = "Invitation link copied. Send it securely to the invited employee.";
    } catch {
        inviteInput.focus();
        inviteInput.select();
        message.textContent = "Automatic copy is unavailable. The link is selected; copy it with Ctrl+C.";
    }
}

async function submitEmployeeForm(event) {
    event.preventDefault();
    if (!canManageEmployees) {
        document.getElementById("employeeFormMessage").textContent = "Employee management requires an Admin account.";
        return;
    }
    const employeeId = document.getElementById("employeeId").value;
    const submitButton = document.getElementById("employeeSubmitButton");
    const formMessage = document.getElementById("employeeFormMessage");
    submitButton.disabled = true;
    submitButton.textContent = "Saving...";
    formMessage.textContent = "";

    try {
        const response = await fetch(employeeId ? `/api/employees/${employeeId}` : "/api/employees", {
            method: employeeId ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: document.getElementById("employeeName").value.trim(),
                email: document.getElementById("employeeEmail").value.trim(),
                role: document.getElementById("employeeRole").value.trim(),
                status: document.getElementById("employeeStatus").value,
                ...(!employeeId ? { account_role: document.getElementById("employeeAccountRole").value } : {}),
            }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            formMessage.textContent = result.message || "Could not save employee.";
            return;
        }

        closeEmployeeModal();
        document.getElementById("employeeMessage").textContent = employeeId ? "Employee updated." : "Employee added.";
        try {
            await Promise.all([loadEmployees(), loadNotifications()]);
        } catch {
            document.getElementById("employeeMessage").textContent = "Employee saved, but the list could not refresh. Reload the dashboard.";
        }
        if (!employeeId) await inviteEmployee(result.id);
    } catch {
        formMessage.textContent = "Could not connect to TaskFlow. Check your connection and try again.";
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = document.getElementById("employeeId").value ? "Save Changes" : "Add Employee";
    }
}

function openEmployeeModal(employeeId) {
    const employee = window.taskflowEmployees?.find(item => item.id === employeeId);
    document.getElementById("employeeFormMessage").textContent = "";
    document.getElementById("employeeMessage").textContent = "";
    document.getElementById("employeeId").value = employee?.id || "";
    document.getElementById("employeeModalTitle").textContent = employee ? "Edit Employee" : "Add Employee";
    document.getElementById("employeeSubmitButton").textContent = employee ? "Save Changes" : "Add Employee";
    document.getElementById("employeeName").value = employee?.name || "";
    document.getElementById("employeeEmail").value = employee?.email || "";
    document.getElementById("employeeRole").value = employee?.role || "Employee";
    document.getElementById("employeeStatus").value = employee?.status || "Active";
    const accountRole = document.getElementById("employeeAccountRole");
    accountRole.value = employee?.account_role || "Employee";
    accountRole.disabled = Boolean(employee?.account_linked);
    document.getElementById("employeeModal").classList.remove("hidden");
    document.getElementById("employeeModal").setAttribute("aria-hidden", "false");
}

function closeEmployeeModal() {
    document.getElementById("employeeModal").classList.add("hidden");
    document.getElementById("employeeModal").setAttribute("aria-hidden", "true");
    document.getElementById("employeeForm").reset();
    document.getElementById("employeeFormMessage").textContent = "";
    document.getElementById("employeeId").value = "";
    document.getElementById("employeeModalTitle").textContent = "Add Employee";
    document.getElementById("employeeSubmitButton").textContent = "Add Employee";
}

function openEmployeeDetails(id) {
    const employee = window.taskflowEmployees?.find(item => item.id === id);
    if (!employee) return;
    document.getElementById("employeeDetailsContent").innerHTML = `<div class="employee-profile"><div class="profile-avatar">${escapeHtml(employee.name.slice(0, 2).toUpperCase())}</div><h4>${escapeHtml(employee.name)}</h4><p>${escapeHtml(employee.role)} · ${escapeHtml(employee.account_role || "Employee")} account</p><dl><dt>Email</dt><dd>${escapeHtml(employee.email)}</dd><dt>Status</dt><dd>${escapeHtml(employee.status)}</dd><dt>Employee ID</dt><dd>#${employee.id}</dd></dl></div>`;
    document.getElementById("employeeDetailsModal").classList.remove("hidden");
    document.getElementById("employeeDetailsModal").setAttribute("aria-hidden", "false");
}

function closeEmployeeDetails() {
    document.getElementById("employeeDetailsModal").classList.add("hidden");
    document.getElementById("employeeDetailsModal").setAttribute("aria-hidden", "true");
}

function closeEmployeeInvite() {
    document.getElementById("employeeInviteModal").classList.add("hidden");
    document.getElementById("employeeInviteModal").setAttribute("aria-hidden", "true");
    document.getElementById("employeeInviteMessage").textContent = "";
}

async function deleteEmployee(id) {
    if (!window.confirm("Remove this employee?")) return;
    await fetch(`/api/employees/${id}`, { method: "DELETE" });
    await Promise.all([loadEmployees(), loadNotifications()]);
}

async function loadNotifications() {
    const response = await fetch("/api/notifications");
    if (!response.ok) throw new Error("Could not load notifications.");
    const notifications = await response.json();
    document.getElementById("notificationBadge").textContent = notifications.filter(item => !item.read).length;
    document.getElementById("notificationList").innerHTML = notifications.map(item => `
        <li class="${item.read ? "is-read" : ""}"><span class="notice-icon ${escapeHtml(item.kind)}">${item.kind === "success" ? "✓" : item.kind === "warning" ? "!" : "✦"}</span><div><strong>${escapeHtml(item.message)}</strong><small>${new Date(item.created_at).toLocaleString()}</small></div>${item.read ? "" : `<button class="task-action" onclick="markNotificationRead(${item.id})">Mark read</button>`}</li>`).join("") || "<li><div><strong>No notifications yet</strong></div></li>";
}

async function markNotificationRead(id) {
    await fetch(`/api/notifications/${id}/read`, { method: "POST" });
    await loadNotifications();
}

function loadSettings() {
    const settings = JSON.parse(localStorage.getItem("taskflow-settings") || "{}");
    if (settings.autoRefresh === false) document.getElementById("settingAutoRefresh").checked = false;
    document.getElementById("settingCompactTasks").checked = settings.compactTasks === true;
    document.getElementById("settingShowCompleted").checked = settings.showCompleted !== false;
    document.getElementById("settingDarkMode").checked = settings.darkMode === true;
    document.body.classList.toggle("compact-tasks", settings.compactTasks === true);
    document.body.classList.toggle("dark-mode", settings.darkMode === true);
}

function saveSettings() {
    const settings = {
        autoRefresh: document.getElementById("settingAutoRefresh").checked,
        compactTasks: document.getElementById("settingCompactTasks").checked,
        showCompleted: document.getElementById("settingShowCompleted").checked,
        darkMode: document.getElementById("settingDarkMode").checked,
    };
    localStorage.setItem("taskflow-settings", JSON.stringify(settings));
    document.body.classList.toggle("compact-tasks", settings.compactTasks);
    document.body.classList.toggle("dark-mode", settings.darkMode);
    document.getElementById("settingsMessage").textContent = "Settings saved.";
}

async function loadPipelines() {
    const response = await fetch("/api/pipelines");
    if (!response.ok) throw new Error("Could not load pipelines.");
    const pipelines = await response.json();
    document.getElementById("pipelineList").innerHTML = pipelines.map(item => `
        <div class="pipeline-item ${item.status.toLowerCase()}"><span class="pipeline-dot"></span><div><strong>${escapeHtml(item.job_name)}</strong><small>${escapeHtml(item.branch)} · ${new Date(item.started_at).toLocaleString()}</small></div><span class="status-tag ${item.status.toLowerCase()}">${escapeHtml(item.status)}</span></div>`).join("") || "<p class=\"lane-empty\">No pipeline runs yet.</p>";
}

async function triggerPipeline() {
    const response = await fetch("/api/pipelines/trigger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_name: "taskflow", branch: "main" }) });
    if (!response.ok) {
        document.getElementById("serviceDetail").textContent = "Pipeline trigger failed.";
        return;
    }
    document.getElementById("serviceDetail").textContent = "Pipeline queued successfully.";
    await Promise.all([loadPipelines(), loadNotifications()]);
}

function downloadTaskReport() {
    window.open(`/api/reports/tasks.csv?${reportQuery()}`, "_blank");
}

function downloadPdfReport() {
    window.open(`/api/reports/tasks.pdf?${reportQuery()}`, "_blank");
}

function reportQuery() {
    const query = new URLSearchParams();
    const from = document.getElementById("reportFrom")?.value;
    const to = document.getElementById("reportTo")?.value;
    if (from) query.set("from", from);
    if (to) query.set("to", to);
    return query.toString();
}

async function applyReportFilter() {
    await loadAnalytics();
    document.getElementById("settingsMessage").textContent = "Report date filter applied.";
}

async function setupTwoFactor() {
    const response = await fetch("/api/security/2fa/setup", { method: "POST" });
    const data = await response.json();
    document.getElementById("settingsMessage").textContent = response.ok ? `Scan this OTP URI in your authenticator: ${data.otpauth_uri}` : data.message;
}

async function saveRecoveryEmail(event) {
    event.preventDefault();
    const email = document.getElementById("settingRecoveryEmail").value.trim();
    const message = document.getElementById("settingsMessage");
    try {
        const response = await fetch("/api/account/recovery-email", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email })
        });
        const data = await response.json();
        message.textContent = data.message || "Could not update the recovery email.";
    } catch {
        message.textContent = "Could not reach TaskFlow. Check your connection and try again.";
    }
}

async function enableBrowserNotifications() {
    if (!("Notification" in window)) {
        document.getElementById("settingsMessage").textContent = "Browser notifications are not supported.";
        return;
    }
    const permission = await Notification.requestPermission();
    document.getElementById("settingsMessage").textContent = permission === "granted" ? "Browser notifications enabled." : "Browser notifications were not enabled.";
}

async function toggleTwoFactor() {
    const response = await fetch("/api/security/2fa", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true }) });
    document.getElementById("settingsMessage").textContent = response.ok ? "Two-factor security enabled." : "Could not update two-factor security.";
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

async function checkServiceHealth() {
    const dot = document.getElementById("serviceDot");
    const state = document.getElementById("serviceState");
    const detail = document.getElementById("serviceDetail");

    try {
        const response = await fetch("/api/health");
        if (!response.ok) {
            throw new Error("Health check failed");
        }

        state.textContent = "All systems operational";
        detail.textContent = "TaskFlow API is responding normally.";
        dot.className = "service-dot is-online";
    } catch {
        state.textContent = "Service unavailable";
        detail.textContent = "The TaskFlow API could not be reached.";
        dot.className = "service-dot is-offline";
    }
}

async function logout() {
    try {
        await fetch("/api/logout", { method: "POST" });
    } finally {
        window.location.replace("login.html");
    }
}

initializeDashboard();