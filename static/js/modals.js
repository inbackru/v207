// Modal Management Functions

// CSRF Token helper function
function getCSRFToken() {
    const csrfInput = document.querySelector('input[name="csrf_token"]');
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    return (csrfInput && csrfInput.value) || (csrfMeta && csrfMeta.content) || '';
}

// REMOVED: Old Quiz Modal Functions - replaced with unified callback system

function openCallbackModal() {
    const modal = document.getElementById('callback-modal-container');
    const content = document.getElementById('callback-content');
    
    // Check if modal elements exist
    if (!modal || !content) {
        console.error('Modal elements not found');
        return;
    }
    
    // Load quiz from /quiz-registration page
    fetch('/quiz-registration')
        .then(response => response.text())
        .then(html => {
            // Extract only the quiz content
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const quizContainer = doc.querySelector('#quiz-container');
            
            if (quizContainer) {
                console.log('✅ Quiz container found, loading into modal...');
                content.innerHTML = quizContainer.innerHTML;
                
                // Remove full-page styles and adapt for modal
                const quizContainerDiv = content.querySelector('.quiz-container');
                if (quizContainerDiv) {
                    console.log('✅ Quiz container div found, adapting styles...');
                    quizContainerDiv.style.minHeight = 'auto';
                    quizContainerDiv.style.padding = '20px 0';
                    quizContainerDiv.style.background = 'transparent';
                } else {
                    console.warn('⚠️ Quiz container div not found after innerHTML');
                }
                
                // Re-initialize quiz functionality
                console.log('🔄 Initializing quiz in modal...');
                initQuizInModal();
                
                // Show modal
                modal.classList.remove('hidden');
                console.log('✅ Modal shown');
                setTimeout(() => {
                    const relativeEl = modal.querySelector('.relative');
                    if (relativeEl) {
                        relativeEl.classList.add('scale-100');
                        relativeEl.classList.remove('scale-95');
                        console.log('✅ Modal animation started');
                    }
                }, 10);
                
                // Use counter-based scroll lock
                if (typeof window.lockBodyScroll === 'function') {
                    window.lockBodyScroll();
                }
            } else {
                console.error('❌ Quiz content not found in fetched HTML');
            }
        })
        .catch(error => {
            console.error('Error loading quiz:', error);
            if (content) {
                content.innerHTML = '<div class="p-8 text-center"><p class="text-red-600">Ошибка загрузки формы. Попробуйте позже.</p></div>';
            }
            if (modal) {
                modal.classList.remove('hidden');
            }
        });
}

function closeCallbackModal() {
    const modal = document.getElementById('callback-modal-container');
    
    if (modal && modal.querySelector('.relative')) {
        modal.querySelector('.relative').classList.add('scale-95');
        modal.querySelector('.relative').classList.remove('scale-100');
        
        setTimeout(() => {
            modal.classList.add('hidden');
            // Use counter-based scroll unlock
            if (typeof window.unlockBodyScroll === 'function') {
                window.unlockBodyScroll();
            }
        }, 300);
    }
}

// Export immediately to global scope
window.openCallbackModal = openCallbackModal;
window.closeCallbackModal = closeCallbackModal;

// Initialize Quiz in Modal
function initQuizInModal() {
    let currentStep = 1;
    const totalSteps = 6;
    const quizData = {
        district: '',
        property_type: '',
        room_count: '',
        budget: ''
    };

    function updateProgressBar() {
        const progress = (currentStep / totalSteps) * 100;
        const progressFill = document.getElementById('progress-fill');
        if (progressFill) {
            progressFill.style.width = progress + '%';
        }
    }

    window.selectOption = function(element, category) {
        // Remove selection from siblings
        const siblings = element.parentNode.querySelectorAll('.option-card');
        siblings.forEach(sibling => sibling.classList.remove('selected'));
        
        // Add selection to current
        element.classList.add('selected');
        
        // Store selection
        quizData[category] = element.dataset.value;
        
        // Auto-advance to next step after 400ms
        setTimeout(() => {
            nextStep();
        }, 400);
    };

    function nextStep() {
        if (currentStep < totalSteps) {
            console.log(`📍 Moving from step ${currentStep} to ${currentStep + 1}`);
            
            // Hide current step
            const currentStepEl = document.getElementById(`quiz-step-${currentStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            } else {
                console.warn(`⚠️ quiz-step-${currentStep} not found`);
            }
            
            // Update current step indicator to completed
            const currentIndicator = document.getElementById(`step-${currentStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-completed');
                console.log(`✅ Step ${currentStep} indicator found and marked as completed`);
            } else {
                console.warn(`⚠️ step-${currentStep} indicator not found!`);
            }
            
            // Move to next step
            currentStep++;
            
            // Show next step content
            const nextStepEl = document.getElementById(`quiz-step-${currentStep}`);
            if (nextStepEl) {
                nextStepEl.classList.remove('hidden');
            } else {
                console.warn(`⚠️ quiz-step-${currentStep} not found`);
            }
            
            // Update next step indicator to active
            const nextIndicator = document.getElementById(`step-${currentStep}`);
            if (nextIndicator) {
                nextIndicator.classList.remove('step-inactive');
                nextIndicator.classList.add('step-active');
                console.log(`✨ Step ${currentStep} indicator found and marked as active`);
            } else {
                console.warn(`⚠️ step-${currentStep} indicator not found!`);
            }
            
            // Update navigation and progress
            updateNavigation();
            updateProgressBar();
        }
    }

    window.previousStep = function() {
        if (currentStep > 1) {
            // Hide current step
            const currentStepEl = document.getElementById(`quiz-step-${currentStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            }
            
            // Update step indicator
            const currentIndicator = document.getElementById(`step-${currentStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-inactive');
            }
            
            // Show previous step
            currentStep--;
            const prevStepEl = document.getElementById(`quiz-step-${currentStep}`);
            if (prevStepEl) {
                prevStepEl.classList.remove('hidden');
            }
            
            const prevIndicator = document.getElementById(`step-${currentStep}`);
            if (prevIndicator) {
                prevIndicator.classList.remove('step-completed');
                prevIndicator.classList.add('step-active');
            }
            
            // Update navigation
            updateNavigation();
            updateProgressBar();
        }
    };

    function updateNavigation() {
        const prevBtn = document.getElementById('prevBtn');
        const submitBtn = document.getElementById('submitBtn');
        const navContainer = document.querySelector('.flex.justify-between.items-center');
        
        // Hide navigation on thank you page (step 6)
        if (currentStep === 6 && navContainer) {
            navContainer.style.display = 'none';
            return;
        } else if (navContainer) {
            navContainer.style.display = 'flex';
        }
        
        // Show/hide previous button (not on step 1 and not on step 5)
        if (prevBtn) {
            prevBtn.style.display = (currentStep > 1 && currentStep < 5) ? 'block' : 'none';
        }
        
        // Show submit button on step 5 only
        if (submitBtn) {
            if (currentStep === 5) {
                submitBtn.classList.remove('hidden');
            } else {
                submitBtn.classList.add('hidden');
            }
        }
    }

    window.submitRegistration = function() {
        const form = document.getElementById('registrationForm');
        const formData = new FormData(form);
        
        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        // Show loading
        const submitText = document.getElementById('submitText');
        const submitSpinner = document.getElementById('submitSpinner');
        const submitBtn = document.getElementById('submitBtn');
        
        if (submitText) submitText.classList.add('hidden');
        if (submitSpinner) submitSpinner.classList.remove('hidden');
        if (submitBtn) submitBtn.disabled = true;
        
        // Prepare application data for /api/contact-manager
        const applicationData = {
            name: formData.get('full_name'),
            phone: formData.get('phone'),
            email: formData.get('email') || '',
            district: quizData.district,
            rooms: quizData.room_count,
            property_type: quizData.property_type,
            budget: quizData.budget,
            message: `Квиз: Район: ${quizData.district}, Тип: ${quizData.property_type}, Комнат: ${quizData.room_count}, Бюджет: ${quizData.budget}`,
            preferred_contact: 'phone'
        };
        
        // Submit to /api/contact-manager
        fetch('/api/contact-manager', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(applicationData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Move to thank you step
                nextStep();
            } else {
                alert('❌ Ошибка отправки: ' + (data.error || 'Попробуйте позже'));
                // Reset button
                if (submitText) submitText.classList.remove('hidden');
                if (submitSpinner) submitSpinner.classList.add('hidden');
                if (submitBtn) submitBtn.disabled = false;
            }
        })
        .catch(error => {
            console.error('Registration error:', error);
            alert('❌ Произошла ошибка. Попробуйте еще раз.');
            // Reset button
            if (submitText) submitText.classList.remove('hidden');
            if (submitSpinner) submitSpinner.classList.add('hidden');
            if (submitBtn) submitBtn.disabled = false;
        });
    };

    // Phone number formatting
    function formatPhoneNumber(input) {
        // Get only digits
        let value = input.value.replace(/\D/g, '');
        
        // Start with +7
        if (value.length > 0) {
            if (value[0] === '8') {
                value = '7' + value.slice(1);
            } else if (value[0] !== '7') {
                value = '7' + value;
            }
        }
        
        // Format as +7 (XXX) XXX-XX-XX
        let formatted = '+7';
        if (value.length > 1) {
            formatted += ' (' + value.slice(1, 4);
        }
        if (value.length >= 5) {
            formatted += ') ' + value.slice(4, 7);
        }
        if (value.length >= 8) {
            formatted += '-' + value.slice(7, 9);
        }
        if (value.length >= 10) {
            formatted += '-' + value.slice(9, 11);
        }
        
        input.value = formatted;
    }

    // Setup phone formatting
    const phoneInput = document.getElementById('phone');
    if (phoneInput) {
        phoneInput.addEventListener('input', function(e) {
            formatPhoneNumber(e.target);
        });
        phoneInput.addEventListener('focus', function(e) {
            if (!e.target.value) {
                e.target.value = '+7 ';
            }
        });
    }

    // Initialize
    updateNavigation();
    updateProgressBar();
}

// REMOVED OLD VERSION
function initQuizInModal_REMOVED() {
    // Re-initialize quiz step functionality for modal
    let currentQuizStep = 1;
    const totalQuizSteps = 5;
    let quizData = {
        district: '',
        property_type: '',
        room_count: '',
        budget: ''
    };
    
    // Global functions for modal quiz
    window.selectOption = function(element, category) {
        // Remove selection from siblings
        const siblings = element.parentNode.querySelectorAll('.option-card');
        siblings.forEach(sibling => sibling.classList.remove('selected'));
        
        // Add selection to current
        element.classList.add('selected');
        
        // Store selection
        quizData[category] = element.dataset.value;
        
        // Enable next button
        const nextBtn = document.getElementById('nextBtn');
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.classList.remove('opacity-50');
        }
        
        // Автоматически переходим на следующий шаг через небольшую задержку
        setTimeout(() => {
            if (currentQuizStep < totalQuizSteps) {
                nextStep();
            }
        }, 300);
    };
    
    window.nextStep = function() {
        if (currentQuizStep < totalQuizSteps) {
            // Hide current step
            const currentStepEl = document.getElementById(`quiz-step-${currentQuizStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            }
            
            // Update step indicator
            const currentIndicator = document.getElementById(`step-${currentQuizStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-completed');
            }
            
            // Show next step
            currentQuizStep++;
            const nextStepEl = document.getElementById(`quiz-step-${currentQuizStep}`);
            if (nextStepEl) {
                nextStepEl.classList.remove('hidden');
            }
            
            const nextIndicator = document.getElementById(`step-${currentQuizStep}`);
            if (nextIndicator) {
                nextIndicator.classList.remove('step-inactive');
                nextIndicator.classList.add('step-active');
            }
            
            // Update navigation
            updateQuizNavigation();
            
            // Show property information if on step 5 and property data exists
            if (currentQuizStep === 5 && window.currentPropertyData) {
                showPropertyInterest(window.currentPropertyData);
            }
        }
    };
    
    window.previousStep = function() {
        if (currentQuizStep > 1) {
            // Hide current step
            const currentStepEl = document.getElementById(`quiz-step-${currentQuizStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            }
            
            // Update step indicator
            const currentIndicator = document.getElementById(`step-${currentQuizStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-inactive');
            }
            
            // Show previous step
            currentQuizStep--;
            const prevStepEl = document.getElementById(`quiz-step-${currentQuizStep}`);
            if (prevStepEl) {
                prevStepEl.classList.remove('hidden');
            }
            
            const prevIndicator = document.getElementById(`step-${currentQuizStep}`);
            if (prevIndicator) {
                prevIndicator.classList.remove('step-completed');
                prevIndicator.classList.add('step-active');
            }
            
            // Update navigation
            updateQuizNavigation();
        }
    };
    
    window.submitRegistration = function() {
        const form = document.getElementById('registrationForm');
        if (!form) return;
        
        const formData = new FormData(form);
        
        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        // No password check needed for application
        
        // Show loading
        const submitText = document.getElementById('submitText');
        const submitSpinner = document.getElementById('submitSpinner');
        const submitBtn = document.getElementById('submitBtn');
        
        if (submitText) submitText.classList.add('hidden');
        if (submitSpinner) submitSpinner.classList.remove('hidden');
        if (submitBtn) submitBtn.disabled = true;
        
        // Get property data if available
        const propertyData = window.currentPropertyData;
        
        // Prepare application data
        const applicationData = {
            name: formData.get('full_name'),
            email: formData.get('email'),
            phone: formData.get('phone'),
            preferred_district: quizData.district,
            property_type: quizData.property_type,
            room_count: quizData.room_count,
            budget_range: quizData.budget,
            application_type: 'property_selection',
            // Add property information if available
            property_id: propertyData ? propertyData.id : null,
            property_title: propertyData ? propertyData.title : null,
            property_complex: propertyData ? propertyData.complex : null,
            property_price: propertyData ? propertyData.price : null,
            property_area: propertyData ? propertyData.area : null,
            property_rooms: propertyData ? propertyData.rooms : null,
            property_floor: propertyData ? propertyData.floor : null,
            property_total_floors: propertyData ? propertyData.total_floors : null,
            property_district: propertyData ? propertyData.district : null,
            property_url: propertyData ? propertyData.url : null,
            property_type_context: propertyData ? propertyData.type : null
        };
        
        // Submit application
        fetch('/api/property-selection', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(applicationData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Заявка отправлена! Наш менеджер свяжется с вами с подходящими вариантами квартир.');
                closeCallbackModal();
            } else {
                alert('Ошибка отправки заявки: ' + data.error);
                resetQuizSubmitButton();
            }
        })
        .catch(error => {
            console.error('Application error:', error);
            alert('Произошла ошибка. Попробуйте еще раз.');
            resetQuizSubmitButton();
        });
    };
    
    function resetQuizSubmitButton() {
        const submitText = document.getElementById('submitText');
        const submitSpinner = document.getElementById('submitSpinner');
        const submitBtn = document.getElementById('submitBtn');
        
        if (submitText) submitText.classList.remove('hidden');
        if (submitSpinner) submitSpinner.classList.add('hidden');
        if (submitBtn) submitBtn.disabled = false;
    }
    
    function updateQuizNavigation() {
        const prevBtn = document.getElementById('prevBtn');
        const nextBtn = document.getElementById('nextBtn');
        const submitBtn = document.getElementById('submitBtn');
        
        // Show/hide previous button
        if (prevBtn) {
            prevBtn.style.display = currentQuizStep > 1 ? 'block' : 'none';
        }
        
        // Show/hide next/submit buttons
        if (currentQuizStep === totalQuizSteps) {
            if (nextBtn) nextBtn.classList.add('hidden');
            if (submitBtn) submitBtn.classList.remove('hidden');
        } else {
            if (nextBtn) {
                nextBtn.classList.remove('hidden');
                nextBtn.disabled = true;
                nextBtn.classList.add('opacity-50');
            }
            if (submitBtn) submitBtn.classList.add('hidden');
        }
    }

    // Global functions
    window.openQuizModal = openQuizModal;
    window.closeQuizModal = closeQuizModal;
    window.submitRegistration = submitRegistration;
    window.openCallbackModal = openCallbackModal;
    window.closeCallbackModal = closeCallbackModal;
    
    function showQuizStep(step) {
        // Hide all steps
        for (let i = 1; i <= totalQuizSteps; i++) {
            const stepEl = document.getElementById(`quiz-step-${i}`);
            if (stepEl) {
                stepEl.classList.add('hidden');
            }
        }
        
        // Show current step
        const currentStepEl = document.getElementById(`quiz-step-${step}`);
        if (currentStepEl) {
            currentStepEl.classList.remove('hidden');
        }
        
        // Update navigation
        updateQuizNavigation();
    }
    
    function updateQuizProgress(step) {
        const progress = (step / totalQuizSteps) * 100;
        const progressBar = document.querySelector('#quiz-progress-bar');
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
        }
        
        const stepText = document.querySelector('#quiz-step-text');
        if (stepText) {
            stepText.textContent = `Шаг ${step} из ${totalQuizSteps}`;
        }
    }
    
    // Next step handlers
    window.nextQuizStep = function(nextStep) {
        if (nextStep <= totalQuizSteps) {
            currentQuizStep = nextStep;
            showQuizStep(currentQuizStep);
        }
    }
    
    // Previous step handler
    window.prevQuizStep = function() {
        if (currentQuizStep > 1) {
            currentQuizStep--;
            showQuizStep(currentQuizStep);
        }
    }
    
    // Initialize first step
    showQuizStep(1);
    
    // Handle form submission
    const quizForm = document.getElementById('quiz-form');
    if (quizForm) {
        quizForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            
            fetch('/api/submit-quiz', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Show success message and close modal
                    alert('Спасибо! Мы подобрали для вас подходящие варианты квартир и сохранили ваши предпочтения.');
                    closeCallbackModal();
                    
                    // Optionally redirect to properties or dashboard
                    if (data.redirect_url) {
                        window.location.href = data.redirect_url;
                    }
                } else {
                    alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                }
            })
            .catch(error => {
                console.error('Error submitting quiz:', error);
                alert('Произошла ошибка при отправке формы. Попробуйте позже.');
            });
        });
    }
    
    // Function to show property interest information
    window.showPropertyInterest = function(propertyData) {
        const interestBlock = document.getElementById('property-interest-block');
        const contentDiv = document.getElementById('property-interest-content');
        
        if (!interestBlock || !contentDiv || !propertyData) return;
        
        let content = '';
        
        if (propertyData.type === 'property') {
            // Specific apartment/property
            content = `
                <div class="flex items-start space-x-3">
                    <div class="flex-shrink-0">
                        <i class="fas fa-map-marker-alt text-blue-600"></i>
                    </div>
                    <div>
                        <p class="font-semibold">${propertyData.title || 'Квартира'}</p>
                        <p class="text-xs text-gray-600 mt-1">
                            ${propertyData.complex ? `ЖК: ${propertyData.complex}` : ''}
                            ${propertyData.area ? ` • ${propertyData.area} м²` : ''}
                            ${propertyData.floor && propertyData.total_floors ? ` • ${propertyData.floor}/${propertyData.total_floors} этаж` : ''}
                        </p>
                        ${propertyData.price ? `<p class="text-sm font-medium text-blue-800 mt-1">${Number(propertyData.price).toLocaleString()} ₽</p>` : ''}
                    </div>
                </div>
            `;
        } else if (propertyData.type === 'complex') {
            // Residential complex
            content = `
                <div class="flex items-start space-x-3">
                    <div class="flex-shrink-0">
                        <i class="fas fa-building text-blue-600"></i>
                    </div>
                    <div>
                        <p class="font-semibold">${propertyData.title || propertyData.name}</p>
                        <p class="text-xs text-gray-600 mt-1">
                            ${propertyData.district ? `Район: ${propertyData.district}` : ''}
                            ${propertyData.total_apartments ? ` • ${propertyData.total_apartments} квартир` : ''}
                        </p>
                        ${propertyData.price_from ? `<p class="text-sm font-medium text-blue-800 mt-1">От ${Number(propertyData.price_from).toLocaleString()} ₽</p>` : ''}
                    </div>
                </div>
            `;
        }
        
        if (content) {
            contentDiv.innerHTML = content;
            interestBlock.classList.remove('hidden');
        }
    };
}

function initCallbackInModal() {
    // Re-initialize callback step functionality for modal
    let currentCallbackStep = 1;
    const totalCallbackSteps = 4;
    let callbackData = {
        interest: '',
        budget: '',
        timing: ''
    };
    
    // Global functions for modal callback
    window.selectCallbackOption = function(element, category) {
        // Remove selection from siblings
        const siblings = element.parentNode.querySelectorAll('.option-card');
        siblings.forEach(sibling => sibling.classList.remove('selected'));
        
        // Add selection to current
        element.classList.add('selected');
        
        // Store selection
        callbackData[category] = element.dataset.value;
        
        // Enable next button
        const nextBtn = document.getElementById('callbackNextBtn');
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.classList.remove('opacity-50');
        }
        
        // Автоматически переходим на следующий шаг через небольшую задержку
        setTimeout(() => {
            if (currentCallbackStep < totalCallbackSteps) {
                nextCallbackStep();
            }
        }, 300);
    };
    
    window.nextCallbackStep = function() {
        if (currentCallbackStep < totalCallbackSteps) {
            // Hide current step
            const currentStepEl = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            }
            
            // Update step indicator
            const currentIndicator = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-completed');
            }
            
            // Show next step
            currentCallbackStep++;
            const nextStepEl = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (nextStepEl) {
                nextStepEl.classList.remove('hidden');
            }
            
            const nextIndicator = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (nextIndicator) {
                nextIndicator.classList.remove('step-inactive');
                nextIndicator.classList.add('step-active');
            }
            
            // Update navigation
            updateCallbackNavigation();
        }
    };
    
    window.previousCallbackStep = function() {
        if (currentCallbackStep > 1) {
            // Hide current step
            const currentStepEl = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (currentStepEl) {
                currentStepEl.classList.add('hidden');
            }
            
            // Update step indicator
            const currentIndicator = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (currentIndicator) {
                currentIndicator.classList.remove('step-active');
                currentIndicator.classList.add('step-inactive');
            }
            
            // Show previous step
            currentCallbackStep--;
            const prevStepEl = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (prevStepEl) {
                prevStepEl.classList.remove('hidden');
            }
            
            const prevIndicator = document.getElementById(`callback-step-${currentCallbackStep}`);
            if (prevIndicator) {
                prevIndicator.classList.remove('step-completed');
                prevIndicator.classList.add('step-active');
            }
            
            // Update navigation
            updateCallbackNavigation();
        }
    };
    
    window.submitCallbackRequest = function() {
        const form = document.getElementById('callbackForm');
        if (!form) return;
        
        const formData = new FormData(form);
        
        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        // Show loading
        const submitText = document.getElementById('callbackSubmitText');
        const submitSpinner = document.getElementById('callbackSubmitSpinner');
        const submitBtn = document.getElementById('callbackSubmitBtn');
        
        if (submitText) submitText.classList.add('hidden');
        if (submitSpinner) submitSpinner.classList.remove('hidden');
        if (submitBtn) submitBtn.disabled = true;
        
        // Prepare callback data
        const requestData = {
            name: formData.get('name'),
            phone: formData.get('phone'),
            email: formData.get('email') || '',
            preferred_time: formData.get('preferred_time'),
            notes: formData.get('notes') || '',
            interest: callbackData.interest,
            budget: callbackData.budget,
            timing: callbackData.timing
        };
        
        // Submit callback request
        fetch('/api/callback-request', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(requestData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Заявка отправлена! Наш менеджер свяжется с вами в ближайшее время.');
                closeCallbackModal();
            } else {
                alert('Ошибка отправки заявки: ' + data.error);
                resetCallbackSubmitButton();
            }
        })
        .catch(error => {
            console.error('Callback request error:', error);
            alert('Произошла ошибка. Попробуйте еще раз.');
            resetCallbackSubmitButton();
        });
    };
    
    function resetCallbackSubmitButton() {
        const submitText = document.getElementById('callbackSubmitText');
        const submitSpinner = document.getElementById('callbackSubmitSpinner');
        const submitBtn = document.getElementById('callbackSubmitBtn');
        
        if (submitText) submitText.classList.remove('hidden');
        if (submitSpinner) submitSpinner.classList.add('hidden');
        if (submitBtn) submitBtn.disabled = false;
    }
    
    function updateCallbackNavigation() {
        const prevBtn = document.getElementById('callbackPrevBtn');
        const nextBtn = document.getElementById('callbackNextBtn');
        const submitBtn = document.getElementById('callbackSubmitBtn');
        
        // Show/hide previous button
        if (prevBtn) {
            prevBtn.style.display = currentCallbackStep > 1 ? 'block' : 'none';
        }
        
        // Show/hide next/submit buttons
        if (currentCallbackStep === totalCallbackSteps) {
            if (nextBtn) nextBtn.classList.add('hidden');
            if (submitBtn) submitBtn.classList.remove('hidden');
        } else {
            if (nextBtn) {
                nextBtn.classList.remove('hidden');
                nextBtn.disabled = true;
                nextBtn.classList.add('opacity-50');
            }
            if (submitBtn) submitBtn.classList.add('hidden');
        }
    }
    
    function showCallbackStep(step) {
        // Hide all steps
        for (let i = 1; i <= totalCallbackSteps; i++) {
            const stepEl = document.getElementById(`callback-step-${i}`);
            if (stepEl) {
                stepEl.classList.add('hidden');
            }
        }
        
        // Show current step
        const currentStepEl = document.getElementById(`callback-step-${step}`);
        if (currentStepEl) {
            currentStepEl.classList.remove('hidden');
        }
        
        // Update navigation
        updateCallbackNavigation();
    }
    
    function updateCallbackProgress(step) {
        const progress = (step / totalCallbackSteps) * 100;
        const progressBar = document.querySelector('#callback-progress-bar');
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
        }
        
        const stepText = document.querySelector('#callback-step-text');
        if (stepText) {
            stepText.textContent = `Шаг ${step} из ${totalCallbackSteps}`;
        }
    }
    
    // Next step handlers
    window.nextCallbackStep = function(nextStep) {
        if (nextStep <= totalCallbackSteps) {
            currentCallbackStep = nextStep;
            showCallbackStep(currentCallbackStep);
        }
    }
    
    // Previous step handler
    window.prevCallbackStep = function() {
        if (currentCallbackStep > 1) {
            currentCallbackStep--;
            showCallbackStep(currentCallbackStep);
        }
    }
    
    // Initialize first step
    showCallbackStep(1);
    
    // Handle form submission
    const callbackForm = document.getElementById('callback-form');
    if (callbackForm) {
        callbackForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            
            fetch('/api/callback-request', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCSRFToken()
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Show success message and close modal
                    alert('Спасибо за заявку! Наш менеджер свяжется с вами в ближайшее время.');
                    closeCallbackModal();
                } else {
                    alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                }
            })
            .catch(error => {
                console.error('Error submitting callback request:', error);
                alert('Произошла ошибка при отправке заявки. Попробуйте позже.');
            });
        });
    }
}

// Global scroll position management
let scrollPosition = 0;

// Function to disable scroll with position preservation
window.disableBodyScroll = function() {
    // Save current scroll position
    scrollPosition = window.pageYOffset || document.documentElement.scrollTop;
    
    // Clear any existing conflicting styles first
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    
    // Remove ALL possible conflicting classes
    document.body.classList.remove('scroll-restored', 'scroll-unified-disabled', 'modal-open', 'no-scroll', 'overflow-hidden');
    
    // Apply UNIFIED scroll lock with padding compensation
    document.body.style.cssText = `
        position: fixed !important;
        top: -${scrollPosition}px !important;
        left: 0 !important;
        width: 100% !important;
        overflow: hidden !important;
        padding-right: ${window.innerWidth - document.documentElement.clientWidth}px !important;
    `;
    
    // Mark as scroll disabled
    document.body.classList.add('scroll-disabled');
};

// Function to restore scroll with position preservation
window.restoreBodyScroll = function() {
    // Reset all possible scroll-blocking styles immediately
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    
    // Remove all classes that might block scroll
    document.body.className = document.body.className
        .replace(/modal-open|no-scroll|overflow-hidden|scroll-disabled/g, '')
        .trim();
    document.documentElement.className = document.documentElement.className
        .replace(/modal-open|no-scroll|overflow-hidden|scroll-disabled/g, '')
        .trim();
    
    // Force immediate reflow
    document.body.offsetHeight;
    
    // Restore scroll position with small delay to ensure styles are applied
    setTimeout(() => {
        window.scrollTo(0, scrollPosition);
        document.body.classList.add('scroll-restored');
    }, 10);
};

// Close modals on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeCallbackModal();
        closeCallbackModal();
    }
});

// Emergency scroll restoration - runs every 100ms to check for stuck scroll
let emergencyScrollCheck = setInterval(function() {
    // Only check if no modal is currently open
    const quizModal = document.getElementById('quiz-modal-container');
    const callbackModal = document.getElementById('callback-modal-container');
    
    const isQuizOpen = quizModal && !quizModal.classList.contains('hidden');
    const isCallbackOpen = callbackModal && !callbackModal.classList.contains('hidden');
    
    // If no modals are open but body has scroll-blocking styles, fix it
    if (!isQuizOpen && !isCallbackOpen) {
        const bodyStyle = getComputedStyle(document.body);
        const hasFixedPosition = bodyStyle.position === 'fixed';
        const hasHiddenOverflow = bodyStyle.overflow === 'hidden';
        
        if (hasFixedPosition || hasHiddenOverflow) {
            document.body.style.cssText = '';
            document.documentElement.style.cssText = '';
            document.body.className = document.body.className
                .replace(/modal-open|no-scroll|overflow-hidden|scroll-disabled/g, '')
                .trim();
        }
    }
}, 100);

// Stop emergency check after 10 seconds to avoid performance issues
setTimeout(() => {
    clearInterval(emergencyScrollCheck);
}, 10000);

// UNIFIED SCROLL MANAGEMENT SYSTEM - Replaces all other scroll functions
let scrollY = 0;
let isScrollDisabled = false;

// Unified function to disable scroll - works for ALL modal systems
window.unifiedDisableScroll = function() {
    if (isScrollDisabled) return; // Prevent double-disable
    
    // Store current scroll position
    scrollY = window.scrollY;
    isScrollDisabled = true;
    
    // Apply unified scroll lock
    document.body.style.cssText = `
        position: fixed !important;
        top: -${scrollY}px !important;
        left: 0 !important;
        width: 100% !important;
        overflow: hidden !important;
        padding-right: ${window.innerWidth - document.documentElement.clientWidth}px !important;
    `;
    
    // Add class marker
    document.body.classList.add('scroll-unified-disabled');
    
    console.log('Unified scroll disabled at position:', scrollY);
};

// Unified function to restore scroll - works for ALL modal systems  
window.unifiedRestoreScroll = function() {
    if (!isScrollDisabled) return; // Prevent double-restore
    
    // Clear all styles immediately
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    
    // Remove all possible scroll-blocking classes
    document.body.classList.remove('scroll-unified-disabled', 'scroll-disabled', 'modal-open', 'no-scroll', 'overflow-hidden');
    
    // Force reflow
    document.body.offsetHeight;
    
    // Restore scroll position
    window.scrollTo(0, scrollY);
    isScrollDisabled = false;
    
    console.log('Unified scroll restored to position:', scrollY);
};

// Enhanced emergency cleanup that works with unified system
let unifiedEmergencyCheck = setInterval(function() {
    // Check if any modals are actually open
    const quizModal = document.getElementById('quiz-modal-container');
    const callbackModal = document.getElementById('callback-modal-container');
    
    const isQuizOpen = quizModal && !quizModal.classList.contains('hidden');
    const isCallbackOpen = callbackModal && !callbackModal.classList.contains('hidden');
    
    // If no modals are open but scroll is disabled, restore it
    if (!isQuizOpen && !isCallbackOpen && isScrollDisabled) {
        console.warn('Emergency: Restoring scroll - no modals open but scroll was disabled');
        window.unifiedRestoreScroll();
    }
}, 200);

// Stop emergency check after 15 seconds
setTimeout(() => {
    clearInterval(unifiedEmergencyCheck);
}, 15000);