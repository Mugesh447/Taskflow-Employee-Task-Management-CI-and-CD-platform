const API_URL = "/api";

async function submitAuth(event, endpoint, successPage) {
    event.preventDefault();

    const message = document.getElementById("message");
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const otp = document.getElementById("otp")?.value.trim();

    message.textContent = "";

    try {
        const response = await fetch(`${API_URL}/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password, ...(otp ? { otp } : {}) })
        });
        const data = await response.json();
        message.textContent = data.message || "Something went wrong.";

        if (data.two_factor_required) {
            document.getElementById("otpField").classList.add("is-visible");
            document.getElementById("otp")?.focus();
        } else if (response.ok) {
            window.location.assign(successPage);
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
    button.textContent = isVisible ? "Show" : "Hide";
    button.setAttribute("aria-label", `${isVisible ? "Show" : "Hide"} password`);
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