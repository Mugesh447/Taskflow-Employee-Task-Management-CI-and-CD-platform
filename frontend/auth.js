const API_URL = "/api";

async function submitAuth(event, endpoint, successPage) {
    event.preventDefault();

    const message = document.getElementById("message");
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const otp = document.getElementById("otp")?.value.trim();
    const inviteToken = endpoint === "register" ? new URLSearchParams(window.location.search).get("invite") : null;
    const recoveryEmail = endpoint === "register" ? document.getElementById("recoveryEmail")?.value.trim() : null;
    const loginRole = endpoint === "login" ? document.getElementById("loginRole")?.value : null;
    const rememberMe = endpoint === "login" ? document.getElementById("rememberMe")?.checked : null;

    message.textContent = "";

    try {
        const response = await fetch(`${API_URL}/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username,
                password,
                ...(recoveryEmail ? { email: recoveryEmail } : {}),
                ...(otp ? { otp } : {}),
                ...(inviteToken ? { invite_token: inviteToken } : {}),
                ...(loginRole ? { login_role: loginRole } : {}),
                ...(rememberMe ? { remember_me: true } : {})
            })
        });
        const data = await response.json();
        message.textContent = data.message || "Something went wrong.";

        if (data.two_factor_required) {
            document.getElementById("otpField").classList.add("is-visible");
            document.getElementById("otp")?.focus();
        } else if (response.ok) {
            window.location.assign(data.invited ? "dashboard.html" : successPage);
        }
    } catch {
        message.textContent = "Could not reach TaskFlow. Check your connection and try again.";
    }
}

function register(event) {
    const password = document.getElementById("password").value;
    const confirmation = document.getElementById("confirmPassword").value;
    const message = document.getElementById("message");

    if (password !== confirmation) {
        event.preventDefault();
        message.textContent = "Passwords do not match.";
        return;
    }

    return submitAuth(event, "register", "login.html");
}

function login(event) {
    return submitAuth(event, "login", "dashboard.html");
}

function togglePassword(inputId, button) {
    const input = document.getElementById(inputId);
    const isVisible = input.type === "text";

    input.type = isVisible ? "password" : "text";
    button.setAttribute("aria-label", `${isVisible ? "Show" : "Hide"} password`);
    button.textContent = button.classList.contains("login-password-toggle")
        ? (isVisible ? "◉" : "◉̸")
        : (isVisible ? "Show" : "Hide");
}

function showLoginNotice(text) {
    const message = document.getElementById("message");
    if (message) message.textContent = text;
}

function setAuthView(view) {
    document.getElementById("loginForm").hidden = view !== "login";
    document.getElementById("passwordRecoveryForm").hidden = view !== "recovery";
    document.getElementById("passwordResetForm").hidden = view !== "reset";
    document.getElementById("loginRoleTabs").hidden = view !== "login";
    document.getElementById("loginRegisterLink").hidden = view !== "login";
    showLoginNotice("");
}

function showPasswordRecovery() {
    const currentUsername = document.getElementById("username").value.trim();
    document.getElementById("recoveryIdentifier").value = currentUsername;
    setAuthView("recovery");
    document.getElementById("recoveryIdentifier").focus();
}

function showLoginForm() {
    const url = new URL(window.location.href);
    const fragment = new URLSearchParams(url.hash.slice(1));
    fragment.delete("reset_token");
    url.hash = fragment.toString();
    window.history.replaceState({}, "", url);
    setAuthView("login");
}

async function requestPasswordReset(event) {
    event.preventDefault();
    const message = document.getElementById("message");
    const identifier = document.getElementById("recoveryIdentifier").value.trim();
    const submitButton = event.currentTarget.querySelector("button[type='submit']");
    submitButton.disabled = true;
    message.textContent = "";

    try {
        const response = await fetch(`${API_URL}/password-reset/request`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier })
        });
        const data = await response.json();
        message.textContent = response.ok
            ? "If the account exists and email delivery is configured, reset instructions will be sent to its recovery email. Check your inbox and spam folder."
            : data.message || "Could not request a password reset.";
    } catch {
        message.textContent = "Could not reach TaskFlow. Check your connection and try again.";
    } finally {
        submitButton.disabled = false;
    }
}

async function confirmPasswordReset(event) {
    event.preventDefault();
    const message = document.getElementById("message");
    const password = document.getElementById("resetPassword").value;
    const confirmation = document.getElementById("resetPasswordConfirmation").value;
    if (password !== confirmation) {
        message.textContent = "Passwords do not match.";
        return;
    }

    const submitButton = event.currentTarget.querySelector("button[type='submit']");
    submitButton.disabled = true;
    try {
        const response = await fetch(`${API_URL}/password-reset/confirm`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                token: new URLSearchParams(window.location.hash.slice(1)).get("reset_token"),
                password
            })
        });
        const data = await response.json();
        message.textContent = data.message || "Could not reset password.";
        if (response.ok) {
            const url = new URL(window.location.href);
            const fragment = new URLSearchParams(url.hash.slice(1));
            fragment.delete("reset_token");
            url.hash = fragment.toString();
            window.history.replaceState({}, "", url);
            setAuthView("login");
            message.textContent = "Password reset successfully. Sign in with your new password.";
        }
    } catch {
        message.textContent = "Could not reach TaskFlow. Check your connection and try again.";
    } finally {
        submitButton.disabled = false;
    }
}

function setLoginRole(role) {
    const roleInput = document.getElementById("loginRole");
    if (!roleInput) return;

    roleInput.value = role;
    document.querySelectorAll("[data-login-role]").forEach((button) => {
        const isActive = button.dataset.loginRole === role;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
    showLoginNotice("");
}

function updatePasswordStrength() {
    const password = document.getElementById("password").value;
    const fill = document.getElementById("passwordStrengthFill");
    const label = document.getElementById("passwordStrengthLabel");
    const checks = [
        password.length >= 8,
        /[a-z]/.test(password),
        /[A-Z]/.test(password),
        /[0-9]/.test(password),
        /[^A-Za-z0-9]/.test(password)
    ];
    const strength = checks.filter(Boolean).length;
    const levels = ["Use at least 8 characters.", "Weak", "Weak", "Fair", "Strong", "Strong"];

    fill.style.width = `${strength * 20}%`;
    fill.dataset.strength = strength < 3 ? "weak" : strength < 4 ? "fair" : "strong";
    label.textContent = levels[strength];
}

function setSignupView(view) {
    document.getElementById("signupChoice").hidden = view !== "choices";
    document.getElementById("signupInviteForm").hidden = view !== "invite";
    document.getElementById("registrationForm").hidden = view !== "registration";
}

function showSignupChoices() {
    const url = new URL(window.location.href);
    url.searchParams.delete("invite");
    window.history.replaceState({}, "", url);
    document.getElementById("registerHeading").textContent = "Create your account";
    document.getElementById("registerLede").textContent = "Choose how you want to join TaskFlow.";
    document.getElementById("message").textContent = "";
    document.getElementById("signupInviteLink").value = "";
    document.getElementById("registrationForm").reset();
    document.getElementById("recoveryEmail").readOnly = false;
    document.getElementById("accountRole").value = "Admin (workspace owner)";
    document.getElementById("accountRoleHint").textContent = "You manage this workspace. Account roles cannot be chosen during sign-up.";
    document.querySelector("#registrationForm button[type='submit']").textContent = "Create workspace";
    setSignupView("choices");
}

async function showAdminSignup() {
    const roleInput = document.getElementById("accountRole");
    const roleHint = document.getElementById("accountRoleHint");
    const message = document.getElementById("message");
    document.getElementById("registerHeading").textContent = "Create your workspace";
    document.getElementById("registerLede").textContent = "Set up your Admin account to manage work and invite your team.";
    roleInput.value = "Admin (workspace owner)";
    roleHint.textContent = "Admin access is assigned by TaskFlow when you create a new workspace.";
    document.querySelector("#registrationForm button[type='submit']").textContent = "Create workspace";
    setSignupView("registration");
    try {
        const response = await fetch(`${API_URL}/registration-info`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Could not verify account type.");
        roleInput.value = `${data.role} (workspace owner)`;
    } catch {
        message.textContent = "Could not verify account type. TaskFlow still assigns Admin access securely on the server.";
    }
}

function showEmployeeInvite() {
    document.getElementById("registerHeading").textContent = "Join your workspace";
    document.getElementById("registerLede").textContent = "Employee accounts are created through an invitation from your workspace Admin.";
    document.getElementById("message").textContent = "";
    setSignupView("invite");
    document.getElementById("signupInviteLink").focus();
}

async function continueWithInvitation(event) {
    event.preventDefault();
    const enteredValue = document.getElementById("signupInviteLink").value.trim();
    let token = enteredValue;
    try {
        const inviteUrl = new URL(enteredValue);
        token = inviteUrl.searchParams.get("invite") || enteredValue;
    } catch {
        const query = new URLSearchParams(enteredValue.includes("?") ? enteredValue.slice(enteredValue.indexOf("?") + 1) : "");
        token = query.get("invite") || enteredValue;
    }
    await loadInvitationContext(token);
}

async function loadInvitationContext(inviteToken = null) {
    let token = inviteToken || new URLSearchParams(window.location.search).get("invite");
    const roleInput = document.getElementById("accountRole");
    const roleHint = document.getElementById("accountRoleHint");
    if (!document.getElementById("registerHeading")) return;

    if (!token) {
        showSignupChoices();
        return;
    }

    setSignupView("invite");
    const submitButton = document.querySelector("#registrationForm button[type='submit']");
    const message = document.getElementById("message");
    try {
        const response = await fetch(`${API_URL}/invitations/${encodeURIComponent(token)}`);
        const data = await response.json();
        if (!response.ok) {
            message.textContent = data.message || "This invitation is invalid or expired.";
            document.getElementById("signupInviteLink").value = inviteToken ? token : window.location.href;
            return;
        }
        const url = new URL(window.location.href);
        url.searchParams.set("invite", token);
        window.history.replaceState({}, "", url);
        document.getElementById("registerHeading").textContent = `Join ${data.workspace_name}`;
        document.getElementById("registerLede").textContent = `Set up an account for ${data.employee_name} (${data.email}).`;
        const recoveryEmail = document.getElementById("recoveryEmail");
        recoveryEmail.value = data.email;
        recoveryEmail.readOnly = true;
        roleInput.value = data.account_role || "Employee";
        const article = /^[aeiou]/i.test(roleInput.value) ? "an" : "a";
        roleHint.textContent = `You are joining this workspace as ${article} ${roleInput.value}. Your account access is assigned by the invitation.`;
        submitButton.textContent = "Accept invitation";
        setSignupView("registration");
    } catch {
        message.textContent = "Could not verify this invitation. Check your connection and try again.";
        document.getElementById("signupInviteLink").value = inviteToken ? token : window.location.href;
    }
}

function loadPasswordResetContext() {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("reset_token");
    if (!token || !document.getElementById("passwordResetForm")) return;
    setAuthView("reset");
    document.getElementById("resetPassword").focus();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
        loadInvitationContext();
        loadPasswordResetContext();
    });
} else {
    loadInvitationContext();
    loadPasswordResetContext();
}

document.querySelectorAll("[data-login-role]").forEach((button) => {
    button.addEventListener("click", () => setLoginRole(button.dataset.loginRole));
});