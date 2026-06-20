/**
 * Alert Settings Manager
 * Manages saved searches and notification settings for user dashboard
 */

class AlertSettingsManager {
    constructor() {
        this.searches = [];
        this.alertHistory = [];
        this.init();
    }

    init() {
        console.log('🔔 Initializing Alert Settings Manager...');
        this._loadingSearches = false;
        this._updatingSearches = new Set();
    }

    /**
     * Load saved searches with alert settings from API
     */
    async loadSavedSearches() {
        if (this._loadingSearches) return;
        this._loadingSearches = true;
        const listElement = document.getElementById('saved-searches-list');
        if (!listElement) return;

        try {
            console.log('Loading saved searches with alerts...');
            
            const response = await fetch('/api/user/alert-settings');
            const data = await response.json();

            if (data.success) {
                this.searches = data.searches || [];
                console.log(`Loaded ${this.searches.length} saved searches`);
                
                // Update counters
                const totalCount = document.getElementById('saved-searches-total-count');
                if (totalCount) {
                    totalCount.textContent = this.searches.length;
                }

                const activeCount = this.searches.filter(s => s.alert_enabled).length;
                const activeAlertsCount = document.getElementById('active-alerts-count');
                if (activeAlertsCount) {
                    activeAlertsCount.textContent = activeCount;
                }

                // Render searches
                this.renderSavedSearches();
            } else {
                console.error('Failed to load searches:', data.error);
                this.showError('Не удалось загрузить поиски');
            }
        } catch (error) {
            console.error('Error loading saved searches:', error);
            this.showError('Ошибка загрузки данных');
        } finally {
            this._loadingSearches = false;
        }
    }

    /**
     * Render saved searches with notification settings UI
     */
    renderSavedSearches() {
        const listElement = document.getElementById('saved-searches-list');
        if (!listElement) return;

        if (this.searches.length === 0) {
            listElement.innerHTML = `
                <div class="text-center text-gray-500 py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-300" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/>
                    </svg>
                    <p class="text-lg font-medium mb-2">Нет сохранённых поисков</p>
                    <p class="text-sm text-gray-400 mb-4">Создавайте поиски с фильтрами и получайте уведомления о новых объектах</p>
                    <button class="bg-[#0088CC] text-white px-6 py-3 rounded-lg hover:bg-[#006699] transition-colors" onclick="window.location.href='/properties'">
                        Создать первый поиск
                    </button>
                </div>
            `;
            return;
        }

        listElement.innerHTML = this.searches.map(search => this.renderSearchCard(search)).join('');
        
        // Bind events for each search card
        this.bindSearchCardEvents();
    }

    /**
     * Render individual search card with notification controls
     */
    renderSearchCard(search) {
        const filters = this.parseFilters(search);
        const alertsCount = search.alerts_sent_count || 0;
        const isAlertEnabled = search.alert_enabled || false;
        const frequency = search.alert_frequency || 'instant';
        const channels = search.alert_channels || ['email'];

        const frequencyLabels = {
            'instant': '⚡ Мгновенно',
            'daily': '📅 Раз в день',
            'weekly': '📆 Раз в неделю'
        };

        return `
            <div class="bg-white border border-gray-200 rounded-2xl p-4 hover:border-[#0088CC] hover:shadow-md transition-all cursor-pointer relative group apply-search-card" data-search-id="${search.id}">
                <div class="flex items-start gap-3 mb-4">
                    <div class="w-10 h-10 bg-gradient-to-br from-[#0088CC] to-[#006699] rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm mt-0.5">
                        <svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/>
                        </svg>
                    </div>
                    <div class="min-w-0 flex-1">
                        <h4 class="text-base font-bold text-gray-900 mb-0.5 break-words pr-2">${search.name || 'Сохранённый поиск'}</h4>
                        <p class="text-sm text-gray-500 line-clamp-2">${filters}</p>
                    </div>
                </div>

                <div class="flex items-center justify-between gap-3 mt-2 pt-2 border-t border-gray-50">
                    <div class="flex items-center flex-wrap gap-2">
                        ${isAlertEnabled ? `
                            <span class="inline-flex items-center gap-1.5 bg-green-50 text-green-700 text-[11px] font-semibold px-2.5 py-1.5 rounded-xl border border-green-100">
                                <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                                ${frequencyLabels[frequency] || 'Активно'}
                            </span>
                        ` : `
                            <span class="inline-flex items-center gap-1.5 bg-gray-100 text-gray-500 text-[11px] font-medium px-2.5 py-1.5 rounded-xl">
                                <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M13.477 14.89A6 6 0 015.11 6.524l8.367 8.368zm1.414-1.414L6.524 5.11a6 6 0 018.367 8.367zM18 10a8 8 0 11-16 0 8 8 0 0116 0z" clip-rule="evenodd"/>
                                </svg>
                                Выкл.
                            </span>
                        `}
                        ${alertsCount > 0 ? `
                            <span class="inline-flex items-center gap-1 bg-blue-50 text-[#0088CC] text-[11px] font-semibold px-2 py-1 rounded-lg border border-blue-100">
                                ${alertsCount}
                            </span>
                        ` : ''}
                    </div>

                    <div class="flex items-center gap-1 bg-gray-50 p-1 rounded-xl">
                        <!-- Notification Toggle -->
                        <label class="relative inline-flex items-center cursor-pointer card-alert-toggle-wrapper px-2" data-search-id="${search.id}">
                            <input type="checkbox" class="sr-only peer card-alert-toggle" data-search-id="${search.id}" ${isAlertEnabled ? 'checked' : ''}>
                            <div class="w-10 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-4 peer-checked:after:left-[2px] after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#0088CC] shadow-sm"></div>
                        </label>

                        <div class="flex items-center gap-0.5 border-l border-gray-200 pl-1">
                            <button class="p-2 text-gray-400 hover:text-[#0088CC] rounded-lg transition-colors settings-btn" data-search-id="${search.id}">
                                <svg class="w-4.5 h-4.5" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/>
                                </svg>
                            </button>
                            <button class="p-2 text-gray-400 hover:text-red-500 rounded-lg transition-colors delete-search-btn" data-search-id="${search.id}">
                                <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Parse search filters into human-readable string
     */
    parseFilters(search) {
        const filters = [];
        const data = search.additional_filters || {};

        if (data.rooms) filters.push(`${data.rooms}-комн.`);
        if (data.priceFrom || data.priceTo) {
            const from = data.priceFrom ? `от ${(data.priceFrom / 1000000).toFixed(1)} млн` : '';
            const to = data.priceTo ? `до ${(data.priceTo / 1000000).toFixed(1)} млн` : '';
            filters.push([from, to].filter(Boolean).join(' '));
        }
        if (data.district) filters.push(data.district);
        if (data.complex_name) filters.push(`ЖК "${data.complex_name}"`);

        return filters.length > 0 ? filters.join(' • ') : 'Все параметры';
    }

    /**
     * Bind events for search card controls
     */
    bindSearchCardEvents() {

        // Make entire card clickable to apply search
        document.querySelectorAll('.apply-search-card').forEach(card => {
            card.addEventListener('click', (e) => {
                // Don't trigger if clicking on controls
                if (e.target.closest('.delete-search-btn') || 
                    e.target.closest('.settings-btn') ||
                    e.target.closest('.card-alert-toggle-wrapper')) {
                    return;
                }
                const searchId = card.dataset.searchId;
                this.applySearch(searchId);
            });
        });

        // Settings buttons
        document.querySelectorAll('.settings-btn').forEach(button => {
            button.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent card click
                const searchId = e.currentTarget.dataset.searchId;
                this.openSettingsModal(searchId);
            });
        });

        // Delete search buttons
        document.querySelectorAll('.delete-search-btn').forEach(button => {
            button.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent card click
                const searchId = e.currentTarget.dataset.searchId;
                this.deleteSavedSearch(searchId);
            });
        });

        // Alert toggle switches in cards
        document.querySelectorAll('.card-alert-toggle').forEach(toggle => {
            if (toggle.dataset.eventsBound) return;
            toggle.dataset.eventsBound = 'true';

            const wrapper = toggle.closest('.card-alert-toggle-wrapper');
            
            // Stop propagation on wrapper to prevent card click
            wrapper.addEventListener('click', (e) => {
                e.stopPropagation();
            });

            // Handle toggle change
            toggle.addEventListener('change', (e) => {
                e.stopPropagation();
                const searchId = e.currentTarget.dataset.searchId;
                const enabled = e.target.checked;
                this.updateAlertSettings(searchId, { alert_enabled: enabled });
            });
        });
    }

    /**
     * Open settings modal for a specific search
     */
    openSettingsModal(searchId) {
        const search = this.searches.find(s => s.id === parseInt(searchId));
        if (!search) return;

        const isAlertEnabled = search.alert_enabled || false;
        const frequency = search.alert_frequency || 'instant';
        const channels = search.alert_channels || ['email'];
        const filters = this.parseFilters(search);

        const modal = document.createElement('div');
        modal.id = 'settings-modal';
        modal.className = 'fixed inset-0 bg-black/60 z-[9999] flex items-end sm:items-center justify-center p-0 sm:p-4';
        modal.innerHTML = `
            <div class="bg-white rounded-t-3xl sm:rounded-2xl w-full max-w-md shadow-2xl transform transition-all max-h-[92vh] flex flex-col" onclick="event.stopPropagation()">
                <!-- Header -->
                <div class="px-6 py-5 border-b border-gray-100 sticky top-0 bg-white rounded-t-3xl sm:rounded-t-2xl z-10">
                    <div class="flex items-start justify-between">
                        <div class="flex-1 min-w-0">
                            <h3 class="text-xl font-bold text-gray-900 truncate">Настройки уведомлений</h3>
                            <p class="text-sm text-gray-500 mt-1 truncate">${search.name || 'Сохранённый поиск'}</p>
                        </div>
                        <button class="ml-4 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-colors close-modal">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-6 py-6 overflow-y-auto flex-1 space-y-8 pb-10">
                    <!-- Enable/Disable Toggle -->
                    <div class="flex items-center justify-between p-4 bg-gray-50 rounded-2xl">
                        <div class="flex items-center space-x-3">
                            <div class="w-10 h-10 bg-[#0088CC]/10 rounded-xl flex items-center justify-center">
                                <svg class="w-6 h-6 text-[#0088CC]" fill="currentColor" viewBox="0 0 20 20">
                                    <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z"/>
                                </svg>
                            </div>
                            <div>
                                <p class="text-base font-bold text-gray-900">Уведомления</p>
                                <p class="text-xs text-gray-500">О новых объектах</p>
                            </div>
                        </div>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" class="sr-only peer modal-alert-toggle" data-search-id="${searchId}" ${isAlertEnabled ? 'checked' : ''}>
                            <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-5 peer-checked:after:left-[2px] after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#0088CC]"></div>
                        </label>
                    </div>

                    <!-- Settings (shown when enabled) -->
                    <div class="modal-notification-settings space-y-8 ${isAlertEnabled ? '' : 'hidden'}">
                        <!-- Frequency Selector -->
                        <div>
                            <label class="text-sm font-bold text-gray-900 block mb-4 uppercase tracking-wider">Частота уведомлений</label>
                            <div class="grid grid-cols-3 gap-3">
                                <label class="relative cursor-pointer group">
                                    <input type="radio" name="frequency-${searchId}" value="instant" class="sr-only peer modal-frequency" data-search-id="${searchId}" ${frequency === 'instant' ? 'checked' : ''}>
                                    <div class="border-2 border-gray-100 rounded-2xl p-4 text-center peer-checked:border-[#0088CC] peer-checked:bg-[#0088CC]/5 transition-all group-hover:border-[#0088CC]/30">
                                        <div class="text-3xl mb-2">⚡</div>
                                        <div class="text-[11px] font-bold text-gray-900 uppercase">Сразу</div>
                                    </div>
                                </label>
                                <label class="relative cursor-pointer group">
                                    <input type="radio" name="frequency-${searchId}" value="daily" class="sr-only peer modal-frequency" data-search-id="${searchId}" ${frequency === 'daily' ? 'checked' : ''}>
                                    <div class="border-2 border-gray-100 rounded-2xl p-4 text-center peer-checked:border-[#0088CC] peer-checked:bg-[#0088CC]/5 transition-all group-hover:border-[#0088CC]/30">
                                        <div class="text-3xl mb-2">📅</div>
                                        <div class="text-[11px] font-bold text-gray-900 uppercase">День</div>
                                    </div>
                                </label>
                                <label class="relative cursor-pointer group">
                                    <input type="radio" name="frequency-${searchId}" value="weekly" class="sr-only peer modal-frequency" data-search-id="${searchId}" ${frequency === 'weekly' ? 'checked' : ''}>
                                    <div class="border-2 border-gray-100 rounded-2xl p-4 text-center peer-checked:border-[#0088CC] peer-checked:bg-[#0088CC]/5 transition-all group-hover:border-[#0088CC]/30">
                                        <div class="text-3xl mb-2">📆</div>
                                        <div class="text-[11px] font-bold text-gray-900 uppercase">Неделя</div>
                                    </div>
                                </label>
                            </div>
                        </div>

                        <!-- Channel Checkboxes -->
                        <div>
                            <label class="text-sm font-bold text-gray-900 block mb-4 uppercase tracking-wider">Где получать</label>
                            <div class="space-y-3">
                                <label class="flex items-center space-x-4 cursor-pointer p-4 rounded-2xl border-2 border-gray-50 hover:bg-gray-50 transition-colors">
                                    <input type="checkbox" class="w-5 h-5 text-[#0088CC] border-gray-300 rounded-lg focus:ring-[#0088CC] modal-channel-checkbox" data-search-id="${searchId}" data-channel="email" ${channels.includes('email') ? 'checked' : ''}>
                                    <div class="flex items-center space-x-4 flex-1">
                                        <div class="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center text-2xl">✉️</div>
                                        <div>
                                            <div class="text-base font-bold text-gray-900">Email</div>
                                            <div class="text-xs text-gray-500">${search.user?.email || 'На почту'}</div>
                                        </div>
                                    </div>
                                </label>
                                <label class="flex items-center space-x-4 cursor-pointer p-4 rounded-2xl border-2 border-gray-50 hover:bg-gray-50 transition-colors">
                                    <input type="checkbox" class="w-5 h-5 text-[#0088CC] border-gray-300 rounded-lg focus:ring-[#0088CC] modal-channel-checkbox" data-search-id="${searchId}" data-channel="telegram" ${channels.includes('telegram') ? 'checked' : ''}>
                                    <div class="flex items-center space-x-4 flex-1">
                                        <div class="w-12 h-12 bg-[#0088CC]/10 rounded-xl flex items-center justify-center text-2xl">📱</div>
                                        <div>
                                            <div class="text-base font-bold text-gray-900">Telegram</div>
                                            <div class="text-xs text-gray-500">В наш бот</div>
                                        </div>
                                    </div>
                                </label>
                            </div>
                        </div>

                        <!-- Help Info -->
                        <div class="bg-blue-50 border border-blue-100 rounded-2xl p-5">
                            <div class="flex items-start space-x-3">
                                <svg class="w-6 h-6 text-[#0088CC] flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                                </svg>
                                <div class="text-xs text-blue-900 leading-relaxed">
                                    <p class="font-bold mb-1.5">Как подключить Telegram?</p>
                                    <p>Чтобы получать уведомления в мессенджер, подключите @InBackBot в настройках профиля.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="px-6 py-5 bg-white border-t border-gray-100 sticky bottom-0 sm:rounded-b-2xl">
                    <button class="w-full bg-[#0088CC] text-white py-4 px-6 rounded-2xl hover:bg-[#006699] active:scale-[0.98] transition-all font-bold text-lg close-modal">
                        Сохранить
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        // ... rest of the modal logic (events, etc) already exists in bindSearchCardEvents and below ...


        document.body.appendChild(modal);

        // Close modal on background click
        modal.addEventListener('click', () => this.closeSettingsModal());
        
        // Close on close button
        modal.querySelectorAll('.close-modal').forEach(btn => {
            btn.addEventListener('click', () => this.closeSettingsModal());
        });

        // Prevent modal content click from closing
        modal.querySelector('.bg-white').addEventListener('click', (e) => e.stopPropagation());

        // Bind modal control events
        this.bindModalEvents(searchId);
    }

    /**
     * Bind events for modal controls
     */
    bindModalEvents(searchId) {
        // Alert toggle
        const toggle = document.querySelector('.modal-alert-toggle');
        if (toggle) {
            toggle.addEventListener('change', (e) => {
                const enabled = e.target.checked;
                const settingsDiv = document.querySelector('.modal-notification-settings');
                if (settingsDiv) {
                    if (enabled) {
                        settingsDiv.classList.remove('hidden');
                    } else {
                        settingsDiv.classList.add('hidden');
                    }
                }
                this.updateAlertSettings(searchId, { alert_enabled: enabled });
            });
        }

        // Frequency radios
        document.querySelectorAll('.modal-frequency').forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.updateAlertSettings(searchId, { alert_frequency: e.target.value });
                }
            });
        });

        // Channel checkboxes
        document.querySelectorAll('.modal-channel-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                const checkboxes = document.querySelectorAll('.modal-channel-checkbox');
                const channels = Array.from(checkboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.dataset.channel);
                this.updateAlertSettings(searchId, { alert_channels: channels });
            });
        });
    }

    /**
     * Close settings modal
     */
    closeSettingsModal() {
        const modal = document.getElementById('settings-modal');
        if (modal) {
            modal.remove();
            // Reload searches to reflect updates
            this.loadSavedSearches();
        }
    }

    /**
     * Update alert settings for a specific search
     */
    async updateAlertSettings(searchId, settings) {
        if (this._updatingSearches.has(String(searchId))) return;
        this._updatingSearches.add(String(searchId));
        try {
            console.log(`Updating alert settings for search ${searchId}:`, settings);

            const response = await fetch('/api/user/alert-settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ search_id: parseInt(searchId), ...settings })
            });

            if (!response.ok && response.status === 401) {
                console.warn('Session expired, redirecting to login');
                window.location.href = '/login';
                return;
            }

            let data;
            try {
                data = await response.json();
            } catch (parseError) {
                console.error('Non-JSON response from server:', response.status);
                this.showError('Ошибка соединения с сервером');
                return;
            }

            if (data.success) {
                console.log('✅ Alert settings updated successfully');
                this.showSuccess('Настройки обновлены');
                
                // Update local data
                const search = this.searches.find(s => s.id === parseInt(searchId));
                if (search) {
                    Object.assign(search, settings);
                    
                    // Update active alerts counter
                    const activeCount = this.searches.filter(s => s.alert_enabled).length;
                    const activeAlertsCount = document.getElementById('active-alerts-count');
                    if (activeAlertsCount) {
                        activeAlertsCount.textContent = activeCount;
                    }
                }
            } else {
                console.error('Failed to update settings:', data.error);
                this.showError(data.error || 'Не удалось обновить настройки');
            }
        } catch (error) {
            console.error('Error updating alert settings:', error);
            this.showError('Ошибка соединения');
        } finally {
            this._updatingSearches.delete(String(searchId));
        }
    }

    /**
     * Delete a saved search
     */
    async deleteSavedSearch(searchId) {
        try {
            console.log(`Deleting search ${searchId}...`);

            const response = await fetch(`/api/user/saved-searches/${searchId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                console.log('✅ Search deleted successfully');
                this.showToast('Поиск удалён', 'success');
                
                // Remove from local array
                this.searches = this.searches.filter(s => s.id !== parseInt(searchId));
                
                // Re-render
                this.renderSavedSearches();
            } else {
                console.error('Failed to delete search:', data.error);
                this.showToast('Не удалось удалить поиск', 'error');
            }
        } catch (error) {
            console.error('Error deleting search:', error);
            this.showToast('Ошибка удаления поиска', 'error');
        }
    }

    /**
     * Apply a saved search (redirect to properties with filters)
     */
    applySearch(searchId) {
        const search = this.searches.find(s => s.id === parseInt(searchId));
        if (!search) {
            console.error('Search not found:', searchId);
            return;
        }

        console.log('Applying saved search:', searchId, search);
        // Use 'filters' (parsed dict) not 'additional_filters' (JSON string)
        let filters = search.filters || {};
        // Fallback: if filters is empty but additional_filters exists, try to parse it
        if (Object.keys(filters).length === 0 && search.additional_filters) {
            try {
                filters = typeof search.additional_filters === 'string' 
                    ? JSON.parse(search.additional_filters) 
                    : search.additional_filters;
            } catch (e) {
                console.warn('Failed to parse additional_filters:', e);
            }
        }
        console.log('Saved search filters:', filters);

        if (filters.search_url) {
            console.log('Redirecting to saved search_url:', filters.search_url);
            window.location.href = filters.search_url;
            return;
        }

        const params = new URLSearchParams();

        if (filters.complex_name) params.append('complex', filters.complex_name);
        
        if (filters.property_type) params.append('property_type', filters.property_type);
        
        if (filters.rooms) {
            if (Array.isArray(filters.rooms)) {
                filters.rooms.forEach(r => params.append('rooms[]', r));
            } else {
                params.append('rooms[]', filters.rooms);
            }
        }
        
        const priceMin = filters.price_min || filters.priceFrom;
        const priceMax = filters.price_max || filters.priceTo;
        if (priceMin) params.append('price_min', priceMin);
        if (priceMax) params.append('price_max', priceMax);
        
        const areaMin = filters.area_min || filters.areaFrom;
        const areaMax = filters.area_max || filters.areaTo;
        if (areaMin) params.append('area_min', areaMin);
        if (areaMax) params.append('area_max', areaMax);
        
        const floorMin = filters.floor_min || filters.floorFrom;
        const floorMax = filters.floor_max || filters.floorTo;
        if (floorMin) params.append('floor_min', floorMin);
        if (floorMax) params.append('floor_max', floorMax);
        
        if (filters.district) params.append('district', filters.district);
        
        if (filters.object_classes && filters.object_classes.length > 0) {
            const classes = Array.isArray(filters.object_classes) ? filters.object_classes : [filters.object_classes];
            classes.forEach(c => params.append('object_classes[]', c));
        }
        
        if (filters.developers && filters.developers.length > 0) {
            const devs = Array.isArray(filters.developers) ? filters.developers : [filters.developers];
            devs.forEach(d => params.append('developers[]', d));
        }
        if (filters.districts && filters.districts.length > 0) {
            const dists = Array.isArray(filters.districts) ? filters.districts : [filters.districts];
            dists.forEach(d => params.append('districts[]', d));
        }
        
        if (filters.building_types && filters.building_types.length > 0) {
            const types = Array.isArray(filters.building_types) ? filters.building_types : [filters.building_types];
            types.forEach(t => params.append('building_types[]', t));
        }
        if (filters.renovation && filters.renovation.length > 0) {
            const reno = Array.isArray(filters.renovation) ? filters.renovation : [filters.renovation];
            reno.forEach(r => params.append('renovation[]', r));
        }
        if (filters.floor_options && filters.floor_options.length > 0) {
            const opts = Array.isArray(filters.floor_options) ? filters.floor_options : [filters.floor_options];
            opts.forEach(o => params.append('floor_options[]', o));
        }

        if (filters.city_id) params.append('city_id', filters.city_id);

        let citySlug = 'sochi';
        if (search.city_slug) {
            citySlug = search.city_slug;
        } else if (search.city) {
            if (typeof search.city === 'object' && search.city.slug) {
                citySlug = search.city.slug;
            } else if (typeof search.city === 'string') {
                citySlug = search.city;
            }
        } else if (filters.city) {
            if (typeof filters.city === 'object' && filters.city.slug) {
                citySlug = filters.city.slug;
            } else if (typeof filters.city === 'string') {
                citySlug = filters.city;
            }
        }

        const queryString = params.toString();
        const url = queryString ? `/${citySlug}/properties?${queryString}` : `/${citySlug}/properties`;
        
        console.log('Applying search, redirecting to:', url);
        window.location.href = url;
    }

    /**
     * Load alert history from API
     */
    async loadAlertHistory() {
        try {
            console.log('Loading alert history...');
            
            const response = await fetch('/api/user/alert-history?limit=20');
            const data = await response.json();

            if (data.success) {
                this.alertHistory = data.alerts || [];
                console.log(`Loaded ${this.alertHistory.length} alerts`);
                this.renderAlertHistory();
            } else {
                console.error('Failed to load alert history:', data.error);
                this.showError('Не удалось загрузить историю уведомлений');
            }
        } catch (error) {
            console.error('Error loading alert history:', error);
            this.showError('Ошибка загрузки истории');
        }
    }

    /**
     * Render alert history list
     */
    renderAlertHistory() {
        const listElement = document.getElementById('alert-history-list');
        const noHistoryMsg = document.getElementById('no-history-message');
        
        if (!listElement) return;

        if (this.alertHistory.length === 0) {
            listElement.innerHTML = '';
            if (noHistoryMsg) {
                noHistoryMsg.classList.remove('hidden');
            }
            return;
        }

        if (noHistoryMsg) {
            noHistoryMsg.classList.add('hidden');
        }

        listElement.innerHTML = this.alertHistory.map(alert => `
            <div class="bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition-colors cursor-pointer" onclick="window.location.href='/object/${alert.property_id}'">
                <div class="flex items-start justify-between">
                    <div class="flex-1">
                        <h5 class="font-medium text-gray-900 text-sm mb-1">${alert.property_name || 'Новый объект'}</h5>
                        <p class="text-xs text-gray-600 mb-2">${this.formatPrice(alert.property_price)}</p>
                        <div class="flex items-center space-x-3 text-xs text-gray-500">
                            <span>📅 ${this.formatDate(alert.sent_at)}</span>
                            ${alert.delivery_status === 'sent' ? 
                                '<span class="text-green-600">✓ Отправлено</span>' : 
                                '<span class="text-yellow-600">⏳ В очереди</span>'
                            }
                        </div>
                    </div>
                    <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"/>
                    </svg>
                </div>
            </div>
        `).join('');
    }

    /**
     * Helper: Format price
     */
    formatPrice(price) {
        if (!price) return 'Цена не указана';
        return `${(price / 1000000).toFixed(2)} млн ₽`;
    }

    /**
     * Helper: Format date
     */
    formatDate(dateString) {
        if (!dateString) return 'Недавно';
        const date = new Date(dateString);
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    }

    /**
     * Helper: Get word declension
     */
    getDeclension(number, forms) {
        const n = Math.abs(number) % 100;
        const n1 = n % 10;
        
        if (n > 10 && n < 20) return forms[2];
        if (n1 > 1 && n1 < 5) return forms[1];
        if (n1 === 1) return forms[0];
        
        return forms[2];
    }

    /**
     * Helper: Get CSRF token
     */
    getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    /**
     * Helper: Show toast notification (modern style)
     */
    showToast(message, type = 'success') {
        const bgColor = type === 'success' ? 'bg-green-500' : type === 'error' ? 'bg-red-500' : 'bg-blue-500';
        const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
        
        const toast = document.createElement('div');
        toast.className = `fixed top-20 right-4 ${bgColor} text-white px-6 py-4 rounded-lg shadow-2xl z-50 flex items-center gap-3 transform translate-x-full transition-all duration-300`;
        toast.innerHTML = `
            <div class="w-6 h-6 bg-white bg-opacity-20 rounded-full flex items-center justify-center font-bold">
                ${icon}
            </div>
            <span class="font-medium">${message}</span>
        `;
        
        document.body.appendChild(toast);
        
        setTimeout(() => toast.classList.remove('translate-x-full'), 100);
        
        setTimeout(() => {
            toast.classList.add('translate-x-full');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /**
     * Helper: Show success message
     */
    showSuccess(message) {
        this.showNotification(message, 'success');
    }

    /**
     * Helper: Show error message
     */
    showError(message) {
        this.showNotification(message, 'error');
    }

    /**
     * Helper: Show notification
     */
    showNotification(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    }
}

/**
 * Toggle alert history accordion
 */
window.toggleAlertHistory = function() {
    const content = document.getElementById('alert-history-content');
    const chevron = document.getElementById('history-chevron');
    
    if (content && chevron) {
        const isHidden = content.classList.contains('hidden');
        
        if (isHidden) {
            content.classList.remove('hidden');
            chevron.style.transform = 'rotate(180deg)';
            
            // Load history when opening for the first time
            if (window.alertSettingsManager && window.alertSettingsManager.alertHistory.length === 0) {
                window.alertSettingsManager.loadAlertHistory();
            }
        } else {
            content.classList.add('hidden');
            chevron.style.transform = 'rotate(0deg)';
        }
    }
};

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.alertSettingsManager = new AlertSettingsManager();
    });
} else {
    window.alertSettingsManager = new AlertSettingsManager();
}
