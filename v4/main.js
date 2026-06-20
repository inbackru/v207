// Main JavaScript for Inback Real Estate Platform

// Presentation page guard - IIFE to properly skip main.js on presentation pages
(function() {
    if (window.SKIP_MAIN_JS || document.documentElement?.dataset.page === 'presentation' || document.body?.dataset.page === 'presentation') {
        console.warn('🚫 Skipping main.js on presentation page');
        return;
    }

// Optimized loading animation - faster performance
window.addEventListener('DOMContentLoaded', function() {
    // Hide loading animation immediately for better performance
    const loadingAnimation = document.querySelector('.loading-animation');
    if (loadingAnimation) {
        loadingAnimation.style.display = 'none';
    }
    
    // PostgreSQL comparison system активна через properties-comparison-fix.js
    // Старый localStorage код отключен для ЖК
});

// Global function to toggle header dropdowns - added for stability
window.toggleHeaderDropdown = function(event, button) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    
    const dropdown = button.closest('.dropdown');
    if (!dropdown) return;
    
    const menu = dropdown.querySelector('.dropdown-menu');
    if (!menu) return;
    
    // Force close other dropdowns
    document.querySelectorAll('.dropdown-menu').forEach(otherMenu => {
        if (otherMenu !== menu) {
            otherMenu.classList.add('hidden');
            otherMenu.style.display = '';
        }
    });
    
    // Toggle current dropdown
    const isHidden = menu.classList.contains('hidden') && menu.style.display !== 'block';
    if (isHidden) {
        menu.classList.remove('hidden');
        menu.style.setProperty('display', 'block', 'important');
        menu.style.setProperty('visibility', 'visible', 'important');
        menu.style.setProperty('opacity', '1', 'important');
        menu.style.setProperty('pointer-events', 'auto', 'important');
        
        // Add one-time listener to close when clicking outside
        const closeOnOutsideClick = (e) => {
            if (!dropdown.contains(e.target)) {
                menu.classList.add('hidden');
                menu.style.display = '';
                menu.style.visibility = '';
                menu.style.opacity = '';
                menu.style.pointerEvents = '';
                document.removeEventListener('click', closeOnOutsideClick);
            }
        };
        setTimeout(() => document.addEventListener('click', closeOnOutsideClick), 10);
    } else {
        menu.classList.add('hidden');
        menu.style.display = '';
        menu.style.visibility = '';
        menu.style.opacity = '';
        menu.style.pointerEvents = '';
    }
};

// Global function to close all dropdowns
window.closeAllDropdowns = function() {
    document.querySelectorAll('.dropdown-menu').forEach(menu => {
        menu.classList.add('hidden');
        menu.classList.remove('open');
    });
};

// Dropdown functionality - robust version with global availability
window.toggleDropdown = function(event, menuElement) {
    console.log('toggleDropdown called');
    
    if (event) {
        if (event.stopPropagation) event.stopPropagation();
        if (event.preventDefault) event.preventDefault();
    }
    
    let menu = menuElement;
    
    // Find menu from currentTarget (button)
    if (!menu && event && event.currentTarget) {
        menu = event.currentTarget.nextElementSibling;
    }
    
    // Fallback: search within closest dropdown container
    if (!menu || !menu.classList.contains('dropdown-menu')) {
        const dropdown = event && event.target ? event.target.closest('.dropdown') : null;
        if (dropdown) {
            menu = dropdown.querySelector('.dropdown-menu');
        }
    }
    
    if (!menu) {
        console.error('Dropdown menu not found');
        return;
    }
    
    const isHidden = menu.classList.contains('hidden');
    
    // Close other dropdowns
    document.querySelectorAll('.dropdown-menu').forEach(otherMenu => {
        if (otherMenu !== menu) {
            otherMenu.classList.add('hidden');
            otherMenu.classList.remove('open');
        }
    });
    
    // Toggle current
    if (isHidden) {
        menu.classList.remove('hidden');
        menu.classList.add('open');
    } else {
        menu.classList.add('hidden');
        menu.classList.remove('open');
    }
};

// Close dropdowns when clicking outside - with safety check
document.addEventListener('click', function(e) {
    if (!(e.target && e.target.closest && e.target.closest('.dropdown'))) {
        document.querySelectorAll('.dropdown-menu').forEach(menu => {
            menu.classList.add('hidden');
            menu.classList.remove('open');
        });
    }
});

// Mobile menu functions - optimized for performance
function toggleMobileMenu() {
    console.log('Mobile menu button clicked');
    const menu = document.getElementById('mobileMenu');
    const menuBtn = document.getElementById('mobileMenuBtn');
    const hamburgerIcon = document.getElementById('hamburgerIcon');
    const closeIcon = document.getElementById('closeIcon');
    
    if (menu) {
        const isHidden = menu.classList.contains('hidden');
        
        if (isHidden) {
            // Open menu
            menu.classList.remove('hidden');
            hamburgerIcon?.classList.add('hidden');
            closeIcon?.classList.remove('hidden');
            // Prevent scroll using unified system
            if (typeof window.unifiedDisableScroll === 'function') {
                window.unifiedDisableScroll();
            } else {
                document.body.style.overflow = 'hidden';
            }
            console.log('Mobile menu opened');
        } else {
            // Close menu
            menu.classList.add('hidden');
            hamburgerIcon?.classList.remove('hidden');
            closeIcon?.classList.add('hidden');
            // Restore scroll using unified system
            if (typeof window.unifiedRestoreScroll === 'function') {
                window.unifiedRestoreScroll();
            } else {
                document.body.style.overflow = '';
            }
            // Close all submenus when closing main menu
            document.querySelectorAll('.mobile-dropdown-content').forEach(submenu => {
                submenu.classList.add('hidden');
            });
            console.log('Mobile menu closed');
        }
    } else {
        console.log('Mobile menu element not found');
    }
}

// ✅ Mobile dropdown toggles - убраны дублирующие обработчики
// Используются только inline onclick handlers из HTML

function toggleSubMenu(id) {
    const submenu = document.getElementById(id);
    if (submenu) {
        submenu.classList.toggle('hidden');
    }
}

// Enhanced mobile dropdown functionality
function initializeMobileDropdowns() {
    const dropdownBtns = document.querySelectorAll('.mobile-dropdown-btn');
    
    dropdownBtns.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const content = this.nextElementSibling;
            const arrow = this.querySelector('svg');
            
            if (content && content.classList.contains('mobile-dropdown-content')) {
                // Close other dropdowns
                dropdownBtns.forEach(otherBtn => {
                    if (otherBtn !== this) {
                        const otherContent = otherBtn.nextElementSibling;
                        const otherArrow = otherBtn.querySelector('svg');
                        if (otherContent) {
                            otherContent.classList.add('hidden');
                            otherArrow?.classList.remove('rotate-180');
                        }
                    }
                });
                
                // Toggle current dropdown
                content.classList.toggle('hidden');
                arrow?.classList.toggle('rotate-180');
            }
        });
    });
}

// ✅ Mobile menu initialization - removed addEventListener (using onclick in HTML)
document.addEventListener('DOMContentLoaded', function() {
    // Removed: mobileMenuBtn.addEventListener - using onclick="toggleMobileMenu()" in HTML
    // This prevents double-triggering which caused menu to open and immediately close
    
    initializeMobileDropdowns();
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', function(e) {
        const mobileMenu = document.getElementById('mobileMenu');
        const mobileMenuBtn = document.getElementById('mobileMenuBtn');
        const subPanelContainer = document.getElementById('mobSubPanelContainer');
        const subOverlay = document.getElementById('mobSubOverlay');
        const subPanel = document.getElementById('mobSubPanel');
        
        if (subOverlay && (subOverlay.contains(e.target) || (subPanel && subPanel.contains(e.target)))) {
            return;
        }
        if (subPanelContainer && subPanelContainer.contains(e.target)) {
            return;
        }
        
        if (mobileMenu && !mobileMenu.classList.contains('hidden') && 
            !mobileMenu.contains(e.target) && 
            !mobileMenuBtn.contains(e.target)) {
            toggleMobileMenu();
        }
    });
    
    // Close mobile menu on window resize to desktop
    window.addEventListener('resize', function() {
        if (window.innerWidth >= 1024) { // lg breakpoint
            const mobileMenu = document.getElementById('mobileMenu');
            if (mobileMenu && !mobileMenu.classList.contains('hidden')) {
                toggleMobileMenu();
            }
        }
    });
});

// Modal functions
// Note: openApplicationModal is defined in base.html for the quiz

function openLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function openRegisterModal() {
    closeModal('loginModal');
    const modal = document.getElementById('registerModal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Close modals when clicking outside
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('fixed') && e.target.classList.contains('inset-0')) {
        e.target.classList.add('hidden');
    }
});


// Footer menu toggle for mobile
function toggleFooterMenu(header) {
    if (window.innerWidth >= 768) return;
    
    const group = header && header.closest ? header.closest('.footer-menu-group') : null;
    if (!group) return;
    
    const submenu = group.querySelector('.footer-submenu');
    const icon = header.querySelector('svg');
    
    if (submenu) {
        submenu.classList.toggle('hidden');
    }
    if (icon) {
        icon.classList.toggle('rotate-180');
    }
}

// Стабильный typewriter с защитой от множественных запусков
function setupTypewriter() {
    const typewriter = document.getElementById('typewriter');
    if (!typewriter) return;
    
    // Защита от повторного запуска
    if (typewriter.dataset.initialized) return;
    typewriter.dataset.initialized = 'true';
    
    const texts = [
        "с кэшбеком до 5%",
        "с платежами в подарок"
    ];
    
    let textIndex = 0;
    let charIndex = 0;
    let isDeleting = false;
    let timeoutId = null;
    
    function type() {
        // Проверка что элемент все еще существует
        if (!typewriter || !typewriter.isConnected) {
            if (timeoutId) clearTimeout(timeoutId);
            return;
        }
        
        const currentText = texts[textIndex];
        
        if (!isDeleting) {
            // Typing
            if (charIndex < currentText.length) {
                typewriter.textContent = currentText.substring(0, charIndex + 1);
                charIndex++;
                timeoutId = setTimeout(type, 100);
            } else {
                // Pause then start deleting
                timeoutId = setTimeout(() => {
                    isDeleting = true;
                    type();
                }, 2000);
            }
        } else {
            // Deleting
            if (charIndex > 0) {
                typewriter.textContent = currentText.substring(0, charIndex - 1);
                charIndex--;
                timeoutId = setTimeout(type, 50);
            } else {
                // Move to next text
                isDeleting = false;
                textIndex = (textIndex + 1) % texts.length;
                timeoutId = setTimeout(type, 500);
            }
        }
    }
    
    // Очистка при уходе со страницы
    window.addEventListener('beforeunload', () => {
        if (timeoutId) clearTimeout(timeoutId);
    });
    
    timeoutId = setTimeout(type, 1000);
}

// Price formatter
function formatPrice(price) {
    return new Intl.NumberFormat('ru-RU').format(price) + ' ₽';
}

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Setup typewriter if element exists
    if (document.getElementById('typewriter')) {
        setupTypewriter();
    }
    
    // Add event listeners to forms (except auth forms and profile forms)
    const forms = document.querySelectorAll('form:not(#login-form-element):not(#register-form-element)');
    forms.forEach(form => {
        // Skip auth-related forms and profile forms
        if ((form.closest && (form.closest('[id*="login"]') || form.closest('[id*="register"]'))) || 
            form.action?.includes('/login') || 
            form.action?.includes('/register') ||
            form.action?.includes('/profile') ||
            form.action?.includes('/manager/profile')) {
            return;
        }
        
        form.addEventListener('submit', function(e) {
            // Skip quiz form - it has its own handler in header.html
            if (this.id === 'quiz-form') {
                return;
            }
            
            e.preventDefault();
            // Here you would handle form submission
            console.log('Form submitted:', this);
            
            // Show success message
            console.log('Form submitted successfully');
            
            // Close modal if form is in modal
            const modal = this.closest ? this.closest('.fixed') : null;
            if (modal) {
                modal.classList.add('hidden');
            }
        });
    });
    
    // Add smooth scrolling to anchor links (only internal anchors, not external pages)
    document.querySelectorAll('a[href^="#"]:not([href="#"])').forEach(anchor => {
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
    
    // Initialize property cards hover effects
    const propertyCards = document.querySelectorAll('.property-card');
    propertyCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-5px)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
        });
    });
    
    // Search functionality
    const searchInputs = document.querySelectorAll('input[type="text"][placeholder*="Поиск"]');
    searchInputs.forEach(input => {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const form = this.closest ? this.closest('form') : null;
                if (form) {
                    form.submit();
                }
            }
        });
    });
});

// Carousel functionality
function initCarousels() {
    document.querySelectorAll('.carousel').forEach(carousel => {
        const inner = carousel.querySelector('.carousel-inner');
        const items = inner ? inner.querySelectorAll('.carousel-item') : [];
        const dots = carousel.querySelectorAll('.carousel-dot');
        const prevBtn = carousel.querySelector('.carousel-prev');
        const nextBtn = carousel.querySelector('.carousel-next');
        
        if (items.length === 0) return;
        
        let currentIndex = 0;
        
        function updateCarousel() {
            if (inner) {
                inner.style.transform = `translateX(-${currentIndex * 100}%)`;
            }
            
            dots.forEach((dot, index) => {
                dot.classList.toggle('active', index === currentIndex);
            });
        }
        
        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                currentIndex = (currentIndex > 0) ? currentIndex - 1 : items.length - 1;
                updateCarousel();
            });
        }
        
        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                currentIndex = (currentIndex < items.length - 1) ? currentIndex + 1 : 0;
                updateCarousel();
            });
        }
        
        dots.forEach((dot, index) => {
            dot.addEventListener('click', () => {
                currentIndex = index;
                updateCarousel();
            });
        });
        
        // Auto-rotate every 5 seconds
        let interval = setInterval(() => {
            currentIndex = (currentIndex < items.length - 1) ? currentIndex + 1 : 0;
            updateCarousel();
        }, 5000);
        
        carousel.addEventListener('mouseenter', () => clearInterval(interval));
        carousel.addEventListener('mouseleave', () => {
            interval = setInterval(() => {
                currentIndex = (currentIndex < items.length - 1) ? currentIndex + 1 : 0;
                updateCarousel();
            }, 5000);
        });
        
        // Initialize
        updateCarousel();
    });
}

// Initialize carousels when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initCarousels();
    
    // Property comparison is now handled by properties-comparison-fix.js
    // No need to initialize here as the PostgreSQL system is active
});

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    }
}

// ОТКЛЮЧЕНО: PostgreSQL система сравнения активна через properties-comparison-fix.js
function initializePropertyComparison_DISABLED() {
    let comparisonList = JSON.parse(localStorage.getItem('comparison_properties') || '[]');
    
    // Make functions globally available
    window.addToCompare = function(propertyId) {
        // Check if user is authenticated
        const userAuthElement = document.querySelector('a[href*="dashboard"]') || document.querySelector('.user-authenticated');
        const isAuthenticated = userAuthElement !== null || document.querySelector('a[href*="logout"]') !== null;
        
        if (!isAuthenticated) {
            showNotification('Для добавления в сравнение необходимо войти в личный кабинет', 'warning');
            // Redirect to login page
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
            return;
        }
        
        propertyId = parseInt(propertyId);
        
        if (comparisonList.includes(propertyId)) {
            // Remove from comparison
            comparisonList = comparisonList.filter(id => id !== propertyId);
            console.log('Property removed from comparison:', propertyId);
            showNotification('Объект удален из сравнения', 'info');
        } else if (comparisonList.length < 3) {
            // Add to comparison (max 3 properties)
            comparisonList.push(propertyId);
            console.log('Property added to comparison:', propertyId);
            showNotification('Объект добавлен к сравнению', 'success');
        } else {
            showNotification('Максимум 3 объекта для сравнения', 'warning');
            return;
        }
        
        localStorage.setItem('comparison_properties', JSON.stringify(comparisonList));
        updateCompareButtons();
        updateComparisonCounter();
    };
    
    function updateCompareButtons() {
        document.querySelectorAll('.compare-btn').forEach(btn => {
            const propertyId = parseInt(btn.getAttribute('data-property-id'));
            const textSpan = btn.querySelector('.compare-text') || btn;
            const icon = btn.querySelector('i');
            
            if (comparisonList.includes(propertyId)) {
                // Active state - property is in comparison
                btn.classList.remove('border-gray-300', 'hover:bg-gray-50', 'text-gray-700');
                btn.classList.add('bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                if (textSpan !== btn) textSpan.textContent = 'В сравнении';
                else btn.textContent = 'В сравнении';
                if (icon) {
                    icon.className = 'fas fa-check mr-1';
                }
            } else {
                // Default state
                btn.classList.remove('bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                btn.classList.add('border-gray-300', 'hover:bg-gray-50', 'text-gray-700');
                if (textSpan !== btn) textSpan.textContent = 'Сравнить';
                else btn.textContent = 'Сравнить';
                if (icon) {
                    icon.className = 'fas fa-balance-scale mr-1';
                }
            }
        });
    }
    
    function updateComparisonCounter() {
        const propertiesCount = comparisonList.length;
        const complexesCount = JSON.parse(localStorage.getItem('comparison_complexes') || '[]').length;
        const totalCount = propertiesCount + complexesCount;
        
        const counter = document.getElementById('comparisonCounter');
        if (counter) {
            if (totalCount > 0) {
                counter.textContent = totalCount;
                counter.classList.remove('hidden');
            } else {
                counter.classList.add('hidden');
            }
        }
        
        // Update comparison button in navigation if exists
        const comparisonBtn = document.getElementById('comparisonBtn');
        if (comparisonBtn) {
            if (totalCount > 0) {
                comparisonBtn.classList.remove('hidden');
            } else {
                comparisonBtn.classList.add('hidden');
            }
        }
    }
    
    function showNotification(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type === 'warning' ? 'warning' : type === 'success' ? 'success' : type === 'error' ? 'error' : 'info');
        }
    }
    
    // Initialize buttons on load
    updateCompareButtons();
    updateComparisonCounter();
}

// Property Image Carousel Functions
function nextImageSlide(button, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const container = button && button.closest ? button.closest('.carousel-container') : null;
    if (!container) return;
    const slides = container.querySelectorAll('.carousel-slide');
    
    let currentIndex = 0;
    slides.forEach((slide, index) => {
        if (!slide.classList.contains('opacity-0')) {
            currentIndex = index;
        }
    });
    
    const nextIndex = (currentIndex + 1) % slides.length;
    showImageSlide(container, nextIndex);
}

function prevImageSlide(button, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const container = button && button.closest ? button.closest('.carousel-container') : null;
    if (!container) return;
    const slides = container.querySelectorAll('.carousel-slide');
    
    let currentIndex = 0;
    slides.forEach((slide, index) => {
        if (!slide.classList.contains('opacity-0')) {
            currentIndex = index;
        }
    });
    
    const prevIndex = (currentIndex - 1 + slides.length) % slides.length;
    showImageSlide(container, prevIndex);
}

function goToImageSlide(button, index, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const container = button && button.closest ? button.closest('.carousel-container') : null;
    if (!container) return;
    showImageSlide(container, index);
}

function showImageSlide(container, index) {
    const slides = container.querySelectorAll('.carousel-slide');
    const dots = container.querySelectorAll('.absolute.bottom-14 button');
    
    // Hide all slides
    slides.forEach(slide => {
        slide.classList.add('opacity-0');
    });
    
    // Show current slide
    if (slides[index]) {
        slides[index].classList.remove('opacity-0');
    }
    
    // Update dots
    dots.forEach((dot, i) => {
        if (i === index) {
            dot.classList.remove('bg-white/50');
            dot.classList.add('bg-white/80');
        } else {
            dot.classList.remove('bg-white/80');
            dot.classList.add('bg-white/50');
        }
    });
}

// Complex comparison functionality
function initializeComplexComparison() {
    let complexComparisonList = JSON.parse(localStorage.getItem('comparison_complexes') || '[]');
    
    // Make functions globally available
    function addToComplexCompare(complexId) {
        // Check if user is authenticated
        const userAuthElement = document.querySelector('a[href*="dashboard"]') || document.querySelector('.user-authenticated');
        const isAuthenticated = userAuthElement !== null || document.querySelector('a[href*="logout"]') !== null;
        
        if (!isAuthenticated) {
            showNotification('Для добавления в сравнение необходимо войти в личный кабинет', 'warning');
            // Redirect to login page
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
            return;
        }
        
        complexId = parseInt(complexId);
        
        if (complexComparisonList.includes(complexId)) {
            // Remove from comparison
            complexComparisonList = complexComparisonList.filter(id => id !== complexId);
            console.log('Complex removed from comparison:', complexId);
            showNotification('ЖК удален из сравнения', 'info');
        } else if (complexComparisonList.length < 3) {
            // Add to comparison (max 3 complexes)
            complexComparisonList.push(complexId);
            console.log('Complex added to comparison:', complexId);
            showNotification('ЖК добавлен к сравнению', 'success');
        } else {
            showNotification('Максимум 3 ЖК для сравнения', 'warning');
            return;
        }
        
        localStorage.setItem('comparison_complexes', JSON.stringify(complexComparisonList));
        updateComplexCompareButtons();
        updateComplexComparisonCounter();
    };
    
    function updateComplexCompareButtons() {
        document.querySelectorAll('.complex-compare-btn').forEach(btn => {
            const complexId = parseInt(btn.getAttribute('data-complex-id'));
            const textSpan = btn.querySelector('span') || btn;
            const icon = btn.querySelector('i');
            
            if (complexComparisonList.includes(complexId)) {
                // Active state - complex is in comparison
                btn.classList.remove('border-gray-300', 'hover:bg-blue-50', 'text-gray-700', 'hover:border-blue-400');
                btn.classList.add('bg-green-50', 'text-green-700', 'border-green-400');
                if (textSpan !== btn) textSpan.textContent = 'В сравнении';
                else btn.textContent = 'В сравнении';
                if (icon) {
                    icon.className = 'fas fa-check mr-2 text-green-500';
                }
            } else {
                // Default state
                btn.classList.remove('bg-green-50', 'text-green-700', 'border-green-400');
                btn.classList.add('border-gray-300', 'hover:bg-blue-50', 'text-gray-700', 'hover:border-blue-400');
                if (textSpan !== btn) textSpan.textContent = 'Сравнить';
                else btn.textContent = 'Сравнить';
                if (icon) {
                    icon.className = 'fas fa-balance-scale mr-2 text-blue-500';
                }
            }
        });
    }
    
    function updateComplexComparisonCounter() {
        const propertiesCount = JSON.parse(localStorage.getItem('comparison_properties') || '[]').length;
        const complexesCount = complexComparisonList.length;
        const totalCount = propertiesCount + complexesCount;
        
        const counter = document.getElementById('comparisonCounter');
        if (counter) {
            if (totalCount > 0) {
                counter.textContent = totalCount;
                counter.classList.remove('hidden');
            } else {
                counter.classList.add('hidden');
            }
        }
        
        // Update comparison button in navigation if exists
        const comparisonBtn = document.getElementById('comparisonBtn');
        if (comparisonBtn) {
            if (totalCount > 0) {
                comparisonBtn.classList.remove('hidden');
            } else {
                comparisonBtn.classList.add('hidden');
            }
        }
    }
    
    // Make comparison counter function globally available  
    window.updateComplexComparisonCounter = updateComplexComparisonCounter;
    
    // Initialize buttons on load
    updateComplexCompareButtons();
    updateComplexComparisonCounter();
    
    // Make functions globally available
    window.addToComplexCompare = addToComplexCompare;
    window.updateComplexCompareButtons = updateComplexCompareButtons;
}

// Initialize property comparison when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Property comparison is now handled by properties-comparison-fix.js
    // Complex comparison may still use the old system if function exists
    if (typeof initializeComplexComparison === 'function') {
        initializeComplexComparison();
    }
});

// Share functions using Web Share API
window.shareProperty = function() {
    const propertyTitle = document.querySelector('h1')?.textContent || 'Квартира';
    const propertyUrl = window.location.href;
    
    if (navigator.share) {
        navigator.share({
            title: propertyTitle,
            text: `Посмотрите эту квартиру: ${propertyTitle}`,
            url: propertyUrl
        }).then(() => {
            console.log('Property shared successfully');
        }).catch((error) => {
            console.log('Error sharing property:', error);
            fallbackShare(propertyUrl);
        });
    } else {
        fallbackShare(propertyUrl);
    }
};

window.shareComplex = function() {
    const complexTitle = document.querySelector('h1')?.textContent || 'ЖК';
    const complexUrl = window.location.href;
    
    if (navigator.share) {
        navigator.share({
            title: complexTitle,
            text: `Посмотрите этот ЖК: ${complexTitle}`,
            url: complexUrl
        }).then(() => {
            console.log('Complex shared successfully');
        }).catch((error) => {
            console.log('Error sharing complex:', error);
            fallbackShare(complexUrl);
        });
    } else {
        fallbackShare(complexUrl);
    }
};

// Fallback share function (copy to clipboard)
function fallbackShare(url) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(() => {
            showNotification('Ссылка скопирована в буфер обмена!', 'success');
        }).catch(() => {
            showNotification('Не удалось скопировать ссылку', 'error');
        });
    } else {
        showNotification('Поделиться: ' + url, 'info');
    }
}

// Wrapper function for complex favorites
window.toggleComplexFavorite = function(complexId, element) {
    if (window.ComplexFavorites && typeof window.ComplexFavorites.toggle === 'function') {
        window.ComplexFavorites.toggle(complexId);
    } else {
        console.error('ComplexFavorites not available');
    }
};

// Export slider functions globally for inline onclick handlers
window.nextImageSlide = nextImageSlide;
window.prevImageSlide = prevImageSlide;
window.goToImageSlide = goToImageSlide;

// ✅ Export mobile menu functions globally for onclick handlers
window.toggleMobileMenu = toggleMobileMenu;
window.toggleSubMenu = toggleSubMenu;

})(); // Close IIFE

// ✅ Event delegation УБРАН - inline onclick обработчики в HTML работают напрямую