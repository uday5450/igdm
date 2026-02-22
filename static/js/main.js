// ═══════════════════════════════════════════════════════
// IGDM Pro — Main JavaScript
// Account switcher, form validation, toasts, char counter
// ═══════════════════════════════════════════════════════

// ─── Sidebar Toggle (Mobile) ─────────────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('open');
    }
}

// Close sidebar when clicking outside (mobile)
document.addEventListener('click', function(e) {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.querySelector('.menu-toggle');
    if (sidebar && sidebar.classList.contains('open') &&
        !sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove('open');
    }
});

// ─── Account Switcher ────────────────────────────────
function toggleAccountMenu() {
    const switcher = document.getElementById('accountSwitcher');
    if (switcher) {
        switcher.classList.toggle('open');
    }
}

// Close account menu when clicking outside
document.addEventListener('click', function(e) {
    const switcher = document.getElementById('accountSwitcher');
    if (switcher && switcher.classList.contains('open') &&
        !switcher.contains(e.target)) {
        switcher.classList.remove('open');
    }
});

// ─── Toast Auto-dismiss ──────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach(function(toast, index) {
        setTimeout(function() {
            toast.style.animation = 'toastOut 0.3s ease forwards';
            setTimeout(function() { toast.remove(); }, 300);
        }, 4000 + (index * 500));
    });

    // Initialize character counters
    initCharCounters();

    // Initialize keyword chips
    initKeywordInput();
});

// Add toastOut animation
const style = document.createElement('style');
style.textContent = `
    @keyframes toastOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(40px); }
    }
`;
document.head.appendChild(style);

// ─── Character Counter ───────────────────────────────
function initCharCounters() {
    const inputs = document.querySelectorAll('[data-maxlength]');
    inputs.forEach(function(input) {
        const max = parseInt(input.getAttribute('data-maxlength'));
        const counter = document.createElement('div');
        counter.className = 'char-counter';
        counter.textContent = `0 / ${max}`;
        input.parentNode.appendChild(counter);

        input.addEventListener('input', function() {
            const len = this.value.length;
            counter.textContent = `${len} / ${max}`;
            counter.className = 'char-counter';
            if (len > max * 0.9) counter.classList.add('danger');
            else if (len > max * 0.7) counter.classList.add('warning');
        });

        // Trigger initial count
        const event = new Event('input');
        input.dispatchEvent(event);
    });
}

// ─── DM Message Character Counter ────────────────────
document.addEventListener('DOMContentLoaded', function() {
    const dmInput = document.getElementById('id_dm_message');
    if (dmInput) {
        dmInput.setAttribute('data-maxlength', '80');
        const counter = document.createElement('div');
        counter.className = 'char-counter';
        counter.id = 'dmCharCounter';
        dmInput.parentNode.appendChild(counter);

        function updateCounter() {
            const len = dmInput.value.length;
            counter.textContent = `${len} / 80`;
            counter.className = 'char-counter';
            if (len > 72) counter.classList.add('danger');
            else if (len > 56) counter.classList.add('warning');
        }

        dmInput.addEventListener('input', updateCounter);
        updateCounter();
    }
});

// ─── Keyword Input Enhancement ───────────────────────
function initKeywordInput() {
    const keywordInput = document.getElementById('id_keywords');
    if (!keywordInput) return;

    // Show remaining keywords count
    const helpText = keywordInput.parentNode.querySelector('.form-help');
    if (helpText) {
        keywordInput.addEventListener('input', function() {
            const keywords = this.value.split(',').filter(k => k.trim()).length;
            const remaining = 3 - keywords;
            if (remaining < 0) {
                helpText.style.color = 'var(--color-danger)';
                helpText.textContent = 'Too many keywords! Free plan allows max 3.';
            } else {
                helpText.style.color = '';
                helpText.textContent = `${remaining} keyword${remaining !== 1 ? 's' : ''} remaining`;
            }
        });
    }
}

// ─── Confirm Delete ──────────────────────────────────
function confirmDelete(name) {
    return confirm(`Are you sure you want to delete "${name}"? This action cannot be undone.`);
}

// ─── Select Post Helper ──────────────────────────────
function selectPost(mediaId, permalink) {
    const postInput = document.getElementById('id_target_post_id');
    if (postInput) {
        postInput.value = mediaId;
    }
    // Highlight selected
    document.querySelectorAll('.media-item').forEach(item => {
        item.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');
}
