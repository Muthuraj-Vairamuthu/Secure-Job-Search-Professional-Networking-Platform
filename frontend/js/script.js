// ── CSRF Protection: Auto-inject token into all state-changing requests ──
(function() {
    const originalFetch = window.fetch;
    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : '';
    }
    window.fetch = function(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            const csrfToken = getCookie('csrf_token');
            if (csrfToken) {
                options.headers = options.headers || {};
                // Handle both Headers object and plain object
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-CSRF-Token')) {
                        options.headers.set('X-CSRF-Token', csrfToken);
                    }
                } else {
                    if (!options.headers['X-CSRF-Token']) {
                        options.headers['X-CSRF-Token'] = csrfToken;
                    }
                }
            }
        }
        return originalFetch.call(this, url, options);
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    console.log('FCS GROUP 19 App Loaded');

    setupSharedNavigation();


    // Fade In Animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    const scrollElements = document.querySelectorAll('.fade-in-scroll');
    scrollElements.forEach(el => observer.observe(el));

    // Smooth scrolling
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

});

// Mock Application Apply
function applyForJob(element) {
    if (confirm("Apply for this job? You will be asked to select a resume.")) {
        // Mock successful application
        const btn = element;
        btn.textContent = "Applied";
        btn.style.background = "rgba(16, 185, 129, 0.2)";
        btn.style.color = "#10b981";
        btn.style.border = "1px solid #10b981";
        btn.disabled = true;
    }
}

async function setupSharedNavigation() {
    const navContainer = document.querySelector('.nav-links');
    if (!navContainer) return;
    if (navContainer.tagName !== 'UL') return;

    const currentPath = window.location.pathname.split('/').pop() || 'index.html';
    const user = await fetchCurrentUser();
    const links = buildNavigationLinks(currentPath, user);

    navContainer.innerHTML = links.map(link => {
        const activeClass = link.href === currentPath ? ' class="active"' : '';
        const styleAttr = link.style ? ` style="${link.style}"` : '';
        return `<li><a href="${link.href}"${activeClass}${styleAttr}><i class="${link.icon}"></i> ${link.label}</a></li>`;
    }).join('');
}

async function fetchCurrentUser() {
    try {
        const res = await fetch('/api/v1/users/me');
        if (!res.ok) return null;
        const data = await res.json();
        return data.status === 'success' ? data : null;
    } catch {
        return null;
    }
}

function buildNavigationLinks(currentPath, user) {
    const links = [
        { href: 'dashboard.html', label: 'Home', icon: 'fas fa-home' },
        { href: 'network.html', label: 'Network', icon: 'fas fa-users' },
        { href: 'jobs.html', label: 'Jobs', icon: 'fas fa-briefcase' },
        { href: 'messages.html', label: 'Messaging', icon: 'fas fa-comment-dots' }
    ];

    if (user && (user.role === 'recruiter' || user.role === 'admin' || currentPath === 'company.html')) {
        links.push({ href: 'company.html', label: 'Company', icon: 'fas fa-building' });
    }

    if (user || currentPath === 'profile.html' || currentPath === 'edit_profile.html') {
        links.push({ href: 'profile.html', label: 'Profile', icon: 'fas fa-user-circle' });
    }

    if (user && user.role === 'admin') {
        links.push({ href: 'admin.html', label: 'Admin', icon: 'fas fa-shield-alt', style: 'color: var(--warning-color);' });
    }

    return links;
}
