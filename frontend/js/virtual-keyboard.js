/**
 * Virtual Keyboard Component for OTP Entry
 * 
 * Security feature: Randomized button layout on each display to prevent
 * keystroke logging, shoulder surfing, and input pattern analysis.
 * 
 * Usage:
 *   VirtualKeyboard.show({
 *     title: 'Enter OTP',
 *     subtitle: 'Use the virtual keyboard below',
 *     digits: 6,
 *     onSubmit: async (code) => { ... return true/false; },
 *     onCancel: () => { ... }
 *   });
 */
const VirtualKeyboard = (() => {
    let overlay = null;
    let currentConfig = null;
    let enteredDigits = [];

    function createOverlay() {
        if (overlay) overlay.remove();

        overlay = document.createElement('div');
        overlay.id = 'vk-overlay';
        overlay.innerHTML = `
            <style>
                #vk-overlay {
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.85); z-index: 10000;
                    display: flex; align-items: center; justify-content: center;
                    backdrop-filter: blur(8px);
                    animation: vk-fadein 0.2s ease;
                }
                @keyframes vk-fadein { from { opacity: 0; } to { opacity: 1; } }
                #vk-container {
                    background: linear-gradient(145deg, rgba(30,30,50,0.98), rgba(20,20,35,0.98));
                    border: 1px solid rgba(99,102,241,0.3);
                    border-radius: 16px; padding: 2rem; width: 380px; max-width: 95vw;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 30px rgba(99,102,241,0.15);
                }
                #vk-title {
                    text-align: center; font-size: 1.1rem; font-weight: 700; color: #fff;
                    margin-bottom: 0.3rem;
                }
                #vk-subtitle {
                    text-align: center; font-size: 0.8rem; color: #888; margin-bottom: 1.2rem;
                }
                #vk-display {
                    display: flex; justify-content: center; gap: 0.5rem; margin-bottom: 1.5rem;
                }
                .vk-digit-box {
                    width: 42px; height: 50px; border: 2px solid rgba(99,102,241,0.3);
                    border-radius: 8px; display: flex; align-items: center; justify-content: center;
                    font-size: 1.4rem; font-weight: 700; color: #fff;
                    background: rgba(255,255,255,0.03); transition: all 0.15s;
                }
                .vk-digit-box.filled {
                    border-color: rgba(99,102,241,0.8);
                    background: rgba(99,102,241,0.1);
                    box-shadow: 0 0 10px rgba(99,102,241,0.2);
                }
                .vk-digit-box.active {
                    border-color: rgba(99,102,241,0.6);
                    animation: vk-pulse 1s infinite;
                }
                @keyframes vk-pulse {
                    0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.3); }
                    50% { box-shadow: 0 0 0 4px rgba(99,102,241,0.1); }
                }
                #vk-keys {
                    display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.6rem;
                    margin-bottom: 1rem;
                }
                .vk-key {
                    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
                    border-radius: 10px; color: #fff; font-size: 1.3rem; font-weight: 600;
                    padding: 0.9rem; cursor: pointer; transition: all 0.12s;
                    display: flex; align-items: center; justify-content: center;
                    user-select: none; -webkit-user-select: none;
                }
                .vk-key:hover { background: rgba(99,102,241,0.2); border-color: rgba(99,102,241,0.4); }
                .vk-key:active { transform: scale(0.93); background: rgba(99,102,241,0.35); }
                .vk-key.vk-action {
                    font-size: 0.85rem; font-weight: 600; letter-spacing: 0.5px;
                }
                .vk-key.vk-delete { color: #ef4444; border-color: rgba(239,68,68,0.2); }
                .vk-key.vk-delete:hover { background: rgba(239,68,68,0.15); }
                .vk-key.vk-submit { color: #10b981; border-color: rgba(16,185,129,0.2); }
                .vk-key.vk-submit:hover { background: rgba(16,185,129,0.15); }
                #vk-status {
                    text-align: center; font-size: 0.8rem; min-height: 1.2rem;
                    margin-bottom: 0.5rem;
                }
                #vk-cancel {
                    display: block; width: 100%; text-align: center; color: #888;
                    font-size: 0.85rem; cursor: pointer; padding: 0.5rem; border: none;
                    background: none; margin-top: 0.5rem;
                }
                #vk-cancel:hover { color: #fff; }
                .vk-security-badge {
                    display: flex; align-items: center; justify-content: center; gap: 0.4rem;
                    font-size: 0.7rem; color: rgba(16,185,129,0.7); margin-top: 0.5rem;
                }
            </style>
            <div id="vk-container">
                <div id="vk-title"></div>
                <div id="vk-subtitle"></div>
                <div id="vk-display"></div>
                <div id="vk-status"></div>
                <div id="vk-keys"></div>
                <button id="vk-cancel">Cancel</button>
                <div class="vk-security-badge">
                    <i class="fas fa-shield-alt"></i> 
                    Randomized layout • Anti-keylogger protection
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        // Block physical keyboard
        overlay.addEventListener('keydown', (e) => {
            e.preventDefault();
            e.stopPropagation();
        }, true);

        document.getElementById('vk-cancel').addEventListener('click', hide);
    }

    function shuffleArray(arr) {
        const a = [...arr];
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    }

    function render() {
        const cfg = currentConfig;
        document.getElementById('vk-title').textContent = cfg.title || 'Enter OTP Code';
        document.getElementById('vk-subtitle').textContent = cfg.subtitle || 'Use the virtual keyboard below';

        // Display boxes
        const display = document.getElementById('vk-display');
        display.innerHTML = '';
        for (let i = 0; i < cfg.digits; i++) {
            const box = document.createElement('div');
            box.className = 'vk-digit-box' + (i < enteredDigits.length ? ' filled' : '') + (i === enteredDigits.length ? ' active' : '');
            box.textContent = i < enteredDigits.length ? '●' : '';
            display.appendChild(box);
        }

        // Randomized keys
        const keysDiv = document.getElementById('vk-keys');
        keysDiv.innerHTML = '';
        const digits = shuffleArray([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);

        // Layout: 9 digit keys + delete on row 1-3, then clear/0/submit on row 4
        const layout = [...digits.slice(0, 9)];
        // First 9 digits
        layout.forEach(d => {
            const btn = document.createElement('button');
            btn.className = 'vk-key';
            btn.textContent = d;
            btn.addEventListener('click', () => pressDigit(d));
            keysDiv.appendChild(btn);
        });

        // Bottom row: Delete, last digit, Submit
        const delBtn = document.createElement('button');
        delBtn.className = 'vk-key vk-action vk-delete';
        delBtn.innerHTML = '<i class="fas fa-backspace" style="margin-right:0.3rem;"></i> DEL';
        delBtn.addEventListener('click', pressDelete);
        keysDiv.appendChild(delBtn);

        const lastDigitBtn = document.createElement('button');
        lastDigitBtn.className = 'vk-key';
        lastDigitBtn.textContent = digits[9];
        lastDigitBtn.addEventListener('click', () => pressDigit(digits[9]));
        keysDiv.appendChild(lastDigitBtn);

        const submitBtn = document.createElement('button');
        submitBtn.className = 'vk-key vk-action vk-submit';
        submitBtn.innerHTML = '<i class="fas fa-check" style="margin-right:0.3rem;"></i> OK';
        submitBtn.addEventListener('click', pressSubmit);
        keysDiv.appendChild(submitBtn);
    }

    function pressDigit(d) {
        if (enteredDigits.length >= currentConfig.digits) return;
        enteredDigits.push(d);
        setStatus('', '');
        render();
    }

    function pressDelete() {
        enteredDigits.pop();
        setStatus('', '');
        render();
    }

    async function pressSubmit() {
        const code = enteredDigits.join('');
        if (code.length < currentConfig.digits) {
            setStatus(`Please enter all ${currentConfig.digits} digits`, '#ef4444');
            return;
        }

        setStatus('Verifying...', 'rgba(99,102,241,0.8)');

        try {
            const success = await currentConfig.onSubmit(code);
            if (success) {
                setStatus('✓ Verified', '#10b981');
                setTimeout(() => hide(), 500);
            } else {
                setStatus('Invalid code. Try again.', '#ef4444');
                enteredDigits = [];
                render();
            }
        } catch (e) {
            setStatus('Verification error', '#ef4444');
            enteredDigits = [];
            render();
        }
    }

    function setStatus(text, color) {
        const el = document.getElementById('vk-status');
        if (el) {
            el.textContent = text;
            el.style.color = color || '#888';
        }
    }

    function show(config) {
        currentConfig = {
            title: config.title || 'Enter OTP Code',
            subtitle: config.subtitle || 'Use the virtual keyboard for secure input',
            digits: config.digits || 6,
            onSubmit: config.onSubmit || (() => false),
            onCancel: config.onCancel || (() => {})
        };
        enteredDigits = [];
        createOverlay();
        render();
    }

    function hide() {
        if (currentConfig && currentConfig.onCancel) {
            currentConfig.onCancel();
        }
        if (overlay) {
            overlay.remove();
            overlay = null;
        }
        currentConfig = null;
        enteredDigits = [];
    }

    return { show, hide };
})();
