(function() {
    'use strict';

    const TOAST_TYPES = {
        success: { icon: '✓', bg: '#059669', label: 'Успех' },
        error: { icon: '✕', bg: '#DC2626', label: 'Ошибка' },
        info: { icon: 'ℹ', bg: '#0088CC', label: 'Информация' },
        warning: { icon: '⚠', bg: '#D97706', label: 'Внимание' }
    };

    let containerEl = null;
    let toastQueue = [];
    let activeToasts = 0;
    const MAX_VISIBLE = 3;

    function getContainer() {
        if (containerEl && document.body.contains(containerEl)) return containerEl;
        
        containerEl = document.createElement('div');
        containerEl.id = 'toast-container';
        containerEl.style.cssText = `
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 99999;
            display: flex;
            flex-direction: column-reverse;
            align-items: center;
            gap: 8px;
            pointer-events: none;
            width: 100%;
            max-width: 400px;
            padding: 0 16px;
        `;
        document.body.appendChild(containerEl);
        return containerEl;
    }

    function showToast(message, type, duration) {
        type = type || 'success';
        duration = duration || 3000;
        
        if (activeToasts >= MAX_VISIBLE) {
            toastQueue.push({ message, type, duration });
            return;
        }
        
        activeToasts++;
        const config = TOAST_TYPES[type] || TOAST_TYPES.info;
        const container = getContainer();

        const toast = document.createElement('div');
        toast.style.cssText = `
            display: flex;
            align-items: center;
            gap: 10px;
            background: ${config.bg};
            color: white;
            padding: 12px 20px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 8px 25px rgba(0,0,0,0.2);
            pointer-events: auto;
            cursor: pointer;
            opacity: 0;
            transform: translateY(20px) scale(0.95);
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            max-width: 100%;
            line-height: 1.4;
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        `;

        const iconSpan = document.createElement('span');
        iconSpan.style.cssText = `
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: rgba(255,255,255,0.25);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            flex-shrink: 0;
        `;
        iconSpan.textContent = config.icon;

        const textSpan = document.createElement('span');
        textSpan.textContent = message;
        textSpan.style.cssText = 'flex: 1; word-break: break-word;';

        toast.appendChild(iconSpan);
        toast.appendChild(textSpan);
        container.appendChild(toast);

        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                toast.style.opacity = '1';
                toast.style.transform = 'translateY(0) scale(1)';
            });
        });

        function dismiss() {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px) scale(0.95)';
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
                activeToasts--;
                if (toastQueue.length > 0) {
                    var next = toastQueue.shift();
                    showToast(next.message, next.type, next.duration);
                }
            }, 350);
        }

        toast.addEventListener('click', dismiss);

        var progressBar = document.createElement('div');
        progressBar.style.cssText = `
            position: absolute;
            bottom: 0;
            left: 12px;
            right: 12px;
            height: 3px;
            background: rgba(255,255,255,0.3);
            border-radius: 2px;
            overflow: hidden;
        `;
        var progressFill = document.createElement('div');
        progressFill.style.cssText = `
            height: 100%;
            background: rgba(255,255,255,0.7);
            border-radius: 2px;
            width: 100%;
            transition: width ${duration}ms linear;
        `;
        progressBar.appendChild(progressFill);
        toast.style.position = 'relative';
        toast.appendChild(progressBar);

        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                progressFill.style.width = '0%';
            });
        });

        setTimeout(dismiss, duration);
    }

    window.showToast = showToast;

    window.toastSuccess = function(msg, dur) { showToast(msg, 'success', dur); };
    window.toastError = function(msg, dur) { showToast(msg, 'error', dur); };
    window.toastInfo = function(msg, dur) { showToast(msg, 'info', dur); };
    window.toastWarning = function(msg, dur) { showToast(msg, 'warning', dur); };
})();
