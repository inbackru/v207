/**
 * Scroll Animations - InBack
 * Smooth reveal animations as user scrolls
 */

(function() {
    'use strict';

    // Configuration
    const config = {
        threshold: 0.15,
        rootMargin: '0px 0px -50px 0px'
    };

    // Initialize Intersection Observer for scroll reveals
    function initScrollReveal() {
        const revealElements = document.querySelectorAll(
            '.scroll-reveal, .scroll-reveal-left, .scroll-reveal-right, ' +
            '.scroll-reveal-scale, .scroll-reveal-stagger, .highlight-reveal, ' +
            '.decorative-arrow, .badge-reveal, .title-underline, .blur-reveal, .draw-line'
        );

        if (!revealElements.length) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    
                    // Counter animation trigger
                    if (entry.target.classList.contains('counter-animate')) {
                        animateCounter(entry.target);
                    }
                }
            });
        }, config);

        revealElements.forEach(el => observer.observe(el));
    }

    // Counter animation
    function animateCounter(element) {
        const target = parseInt(element.getAttribute('data-target') || element.textContent.replace(/\D/g, ''));
        const duration = 2000;
        const start = 0;
        const startTime = performance.now();
        const suffix = element.getAttribute('data-suffix') || '';
        const prefix = element.getAttribute('data-prefix') || '';

        function updateCounter(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // Easing function
            const easeOutQuart = 1 - Math.pow(1 - progress, 4);
            const current = Math.floor(start + (target - start) * easeOutQuart);
            
            element.textContent = prefix + current.toLocaleString('ru-RU') + suffix;
            
            if (progress < 1) {
                requestAnimationFrame(updateCounter);
            }
        }

        requestAnimationFrame(updateCounter);
    }

    // Parallax effect for hero section
    function initParallax() {
        const parallaxElements = document.querySelectorAll('.parallax-bg');
        if (!parallaxElements.length) return;

        let ticking = false;

        window.addEventListener('scroll', () => {
            if (!ticking) {
                requestAnimationFrame(() => {
                    const scrollY = window.pageYOffset;
                    parallaxElements.forEach(el => {
                        const speed = parseFloat(el.getAttribute('data-speed') || 0.5);
                        el.style.transform = `translateY(${scrollY * speed}px)`;
                    });
                    ticking = false;
                });
                ticking = true;
            }
        });
    }

    // Mouse follow effect for decorative elements
    function initMouseFollow() {
        const followElements = document.querySelectorAll('.mouse-follow');
        if (!followElements.length) return;

        document.addEventListener('mousemove', (e) => {
            const mouseX = e.clientX / window.innerWidth - 0.5;
            const mouseY = e.clientY / window.innerHeight - 0.5;

            followElements.forEach(el => {
                const intensity = parseFloat(el.getAttribute('data-intensity') || 20);
                const x = mouseX * intensity;
                const y = mouseY * intensity;
                el.style.transform = `translate(${x}px, ${y}px)`;
            });
        });
    }

    // Smooth scroll progress indicator
    function initScrollProgress() {
        const progressBar = document.querySelector('.scroll-progress');
        if (!progressBar) return;

        window.addEventListener('scroll', () => {
            const scrollTop = window.pageYOffset;
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            const progress = (scrollTop / docHeight) * 100;
            progressBar.style.width = `${progress}%`;
        });
    }

    // Add floating decorative elements to hero
    function addDecorativeElements() {
        const hero = document.querySelector('.hero-section, [class*="hero"]');
        if (!hero || hero.querySelector('.decorative-shapes')) return;

        const shapes = document.createElement('div');
        shapes.className = 'decorative-shapes pointer-events-none absolute inset-0 overflow-hidden';
        shapes.innerHTML = `
            <div class="absolute top-20 left-10 w-16 h-16 float-animation opacity-20">
                <svg viewBox="0 0 100 100" class="text-[#0088CC]">
                    <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" stroke-width="2"/>
                </svg>
            </div>
            <div class="absolute top-40 right-20 w-12 h-12 float-animation float-animation-delay-1 opacity-20">
                <svg viewBox="0 0 100 100" class="text-[#0088CC]">
                    <rect x="20" y="20" width="60" height="60" fill="none" stroke="currentColor" stroke-width="2" transform="rotate(45 50 50)"/>
                </svg>
            </div>
            <div class="absolute bottom-32 left-1/4 w-8 h-8 float-animation float-animation-delay-2 opacity-15">
                <svg viewBox="0 0 100 100" class="text-[#FFB800]">
                    <polygon points="50,10 90,90 10,90" fill="currentColor"/>
                </svg>
            </div>
        `;
        
        hero.style.position = 'relative';
        hero.appendChild(shapes);
    }

    // Initialize all animations
    function init() {
        // Wait for DOM
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initAll);
        } else {
            initAll();
        }
    }

    function initAll() {
        initScrollReveal();
        initParallax();
        initMouseFollow();
        initScrollProgress();
        
        // Add scroll-reveal classes to existing elements
        autoAddAnimationClasses();
        
        console.log('✅ Scroll animations initialized');
    }

    // Auto-add animation classes to common elements
    function autoAddAnimationClasses() {
        // Section headers
        document.querySelectorAll('section h2:not(.scroll-reveal)').forEach((el, index) => {
            if (!el.closest('.no-animate')) {
                el.classList.add('scroll-reveal');
            }
        });

        // Section subtitles/descriptions
        document.querySelectorAll('section > .container > .max-w-6xl > p:not(.scroll-reveal)').forEach(el => {
            if (!el.closest('.no-animate')) {
                el.classList.add('scroll-reveal');
            }
        });

        // Cards in grids
        document.querySelectorAll('.grid:not(.scroll-reveal-stagger)').forEach(grid => {
            if (!grid.closest('.no-animate') && grid.children.length > 1 && grid.children.length <= 8) {
                grid.classList.add('scroll-reveal-stagger');
            }
        });

        // Re-observe new elements
        initScrollReveal();
    }

    // Expose for manual use
    window.ScrollAnimations = {
        init: initAll,
        reveal: initScrollReveal,
        counter: animateCounter
    };

    // Auto-init
    init();

})();
