// Avatar Fallback Module
// Handles avatar image loading failures and replaces them with styled initials

(function() {
    'use strict';

    // Function to create SVG data URI with initials
    function createInitialsSvgDataUri(img) {
        const initials = img.getAttribute('data-initials') || '?';
        let size = img.offsetWidth || img.offsetHeight || 56;
        
        if (size === 0) {
            size = 56;
        }
        
        const fontSize = Math.max(Math.floor(size / 2.5), 16);
        const uniqueId = Date.now();
        
        const escapedInitials = initials
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        
        const svg = `<svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="grad${uniqueId}" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:#3B82F6;stop-opacity:1" />
                    <stop offset="100%" style="stop-color:#6366F1;stop-opacity:1" />
                </linearGradient>
            </defs>
            <rect width="${size}" height="${size}" fill="url(#grad${uniqueId})" />
            <text 
                x="50%" 
                y="50%" 
                dominant-baseline="middle" 
                text-anchor="middle" 
                fill="white" 
                font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" 
                font-weight="bold" 
                font-size="${fontSize}px"
                style="text-transform: uppercase;">
                ${escapedInitials}
            </text>
        </svg>`;
        
        const encodedSvg = encodeURIComponent(svg.trim());
        return `data:image/svg+xml,${encodedSvg}`;
    }

    // Function to handle image error
    function handleImageError(event) {
        const img = event.target;
        
        // Only process if it has data-initials or avatar class
        if (!img.hasAttribute('data-initials') && !img.classList.contains('avatar')) {
            return;
        }

        // Prevent infinite loop - only skip if already showing fallback SVG
        if (img.src.startsWith('data:image/svg+xml')) {
            return;
        }
        
        // Set img src to SVG data URI instead of replacing element
        const svgDataUri = createInitialsSvgDataUri(img);
        img.src = svgDataUri;
        
        console.log('Avatar fallback applied for:', img.alt || 'Unknown');
    }

    // Initialize avatar error handling
    function initAvatarFallback() {
        // Handle existing images
        const images = document.querySelectorAll('img.avatar, img[data-initials]');
        images.forEach(img => {
            // Add error listener
            img.addEventListener('error', handleImageError);
            
            // Check if image is already broken
            if (!img.complete || img.naturalHeight === 0) {
                handleImageError({ target: img });
            }
        });

        // Watch for dynamically added images
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === 1) { // Element node
                        // Check if the node itself is an avatar image
                        if (node.tagName === 'IMG' && 
                            (node.classList.contains('avatar') || node.hasAttribute('data-initials'))) {
                            node.addEventListener('error', handleImageError);
                            
                            // Check if already broken
                            if (!node.complete || node.naturalHeight === 0) {
                                handleImageError({ target: node });
                            }
                        }
                        
                        // Check for avatar images within the node
                        const avatarImages = node.querySelectorAll('img.avatar, img[data-initials]');
                        avatarImages.forEach(img => {
                            img.addEventListener('error', handleImageError);
                            
                            // Check if already broken
                            if (!img.complete || img.naturalHeight === 0) {
                                handleImageError({ target: img });
                            }
                        });
                    }
                });
            });
        });

        // Start observing the document
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        console.log('Avatar fallback module initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAvatarFallback);
    } else {
        initAvatarFallback();
    }
})();
