// =====================================================
// PRESENTATION SYSTEM - Manager Presentation Functions
// Version: 2025-10-23-21:00
// =====================================================

console.log('🚀 PRESENTATION.JS LOADED - VERSION 21:00');

// Presentation modal functions
window.openPresentationModal = function(propertyId) {
    console.log('🎯 openPresentationModal called with property ID:', propertyId);
    fetch('/api/manager/presentations', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
        .then(response => response.text())
        .then(text => {
            const jsonStart = text.indexOf('{');
            if (jsonStart !== -1) {
                const jsonText = text.substring(jsonStart);
                const data = JSON.parse(jsonText);
                if (data.success) {
                    window.showPresentationSelectionModal(propertyId, data.presentations);
                } else {
                    window.showNotification('Ошибка загрузки презентаций', 'error');
                }
            } else {
                window.showNotification('Ошибка загрузки презентаций', 'error');
            }
        })
        .catch(error => {
            console.error('Error loading presentations:', error);
            window.showNotification('Ошибка загрузки презентаций', 'error');
        });
};

window.openComplexPresentationModal = function(complexId) {
    fetch('/api/manager/presentations', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
        .then(response => response.text())
        .then(text => {
            const jsonStart = text.indexOf('{');
            if (jsonStart !== -1) {
                const jsonText = text.substring(jsonStart);
                const data = JSON.parse(jsonText);
                if (data.success) {
                    window.showComplexPresentationSelectionModal(complexId, data.presentations);
                } else {
                    window.showNotification('Ошибка загрузки презентаций', 'error');
                }
            } else {
                window.showNotification('Ошибка загрузки презентаций', 'error');
            }
        })
        .catch(error => {
            console.error('Error loading presentations:', error);
            window.showNotification('Ошибка загрузки презентаций', 'error');
        });
};

window.showPresentationSelectionModal = function(propertyId, presentations) {
    window.closePresentationModal(); // Remove any existing modals first
    const modal = document.createElement('div');
    modal.id = 'presentationSelectionModal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';
    
    const presentationsList = presentations.length > 0 
        ? presentations.map(p => `
            <button onclick="window.addPropertyToPresentation(${propertyId}, ${p.id})" 
                    class="w-full px-4 py-3 text-left bg-white hover:bg-blue-50 border border-gray-200 rounded-lg transition-colors">
                <div class="font-semibold text-gray-900">${p.title}</div>
                <div class="text-sm text-gray-600">Клиент: ${p.client_name || 'Не указан'}</div>
            </button>
        `).join('')
        : '<p class="text-gray-500 text-center py-4">У вас пока нет презентаций</p>';
    
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-semibold text-gray-900">Добавить в презентацию</h3>
            </div>
            <div class="p-6 space-y-3">
                ${presentationsList}
            </div>
            <div class="p-6 border-t border-gray-200 space-y-3">
                <button onclick="window.createNewPresentationWithProperty(${propertyId})" 
                        class="w-full px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors">
                    + Создать новую презентацию
                </button>
                <button onclick="window.closePresentationModal()" class="w-full px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">Закрыть</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
};

window.showComplexPresentationSelectionModal = function(complexId, presentations) {
    window.closePresentationModal(); // Remove any existing modals first
    const modal = document.createElement('div');
    modal.id = 'presentationSelectionModal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';
    
    const presentationsList = presentations.length > 0 
        ? presentations.map(p => `
            <button onclick="window.addComplexToPresentation(${complexId}, ${p.id})" 
                    class="w-full px-4 py-3 text-left bg-white hover:bg-blue-50 border border-gray-200 rounded-lg transition-colors">
                <div class="font-semibold text-gray-900">${p.title}</div>
                <div class="text-sm text-gray-600">Клиент: ${p.client_name || 'Не указан'}</div>
            </button>
        `).join('')
        : '<p class="text-gray-500 text-center py-4">У вас пока нет презентаций</p>';
    
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-semibold text-gray-900">Добавить ЖК в презентацию</h3>
            </div>
            <div class="p-6 space-y-3">
                ${presentationsList}
            </div>
            <div class="p-6 border-t border-gray-200 space-y-3">
                <button onclick="window.createNewPresentationWithComplex(${complexId})" 
                        class="w-full px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors">
                    + Создать новую презентацию
                </button>
                <button onclick="window.closePresentationModal()" class="w-full px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">Отмена</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
};

window.addPropertyToPresentation = function(propertyId, presentationId) {
    fetch(`/api/manager/presentation/${presentationId}/add-property`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
        },
        body: JSON.stringify({
            property_id: propertyId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.closePresentationModal();
            window.showNotification('Объект добавлен в презентацию!', 'success');
        } else {
            window.showNotification('Ошибка: ' + data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error adding property to presentation:', error);
        window.showNotification('Ошибка при добавлении объекта', 'error');
    });
};

window.addComplexToPresentation = function(complexId, presentationId) {
    fetch(`/api/manager/presentation/${presentationId}/add-complex`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
        },
        body: JSON.stringify({
            complex_id: complexId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.closePresentationModal();
            window.showNotification('ЖК добавлен в презентацию!', 'success');
        } else {
            window.showNotification('Ошибка: ' + data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error adding complex to presentation:', error);
        window.showNotification('Ошибка при добавлении ЖК', 'error');
    });
};

window.createNewPresentationWithProperty = function(propertyId) {
    window.closePresentationModal(); // Remove any existing modals first
    const modal = document.createElement('div');
    modal.id = 'newPresentationModal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';
    
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-semibold text-gray-900">Новая презентация</h3>
            </div>
            <div class="p-6 space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Название презентации</label>
                    <input type="text" id="newPresentationTitle" class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="Например: Презентация для Иванова И.И.">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Имя клиента (необязательно)</label>
                    <input type="text" id="newPresentationClient" class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="ФИО клиента">
                </div>
            </div>
            <div class="p-6 border-t border-gray-200 flex gap-3">
                <button type="button" id="createPresentationBtn" class="flex-1 px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors">Создать</button>
                <button type="button" onclick="window.closePresentationModal()" class="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">Отмена</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    document.getElementById('createPresentationBtn').onclick = function() {
        const title = document.getElementById('newPresentationTitle').value;
        const clientName = document.getElementById('newPresentationClient').value;
        
        if (!title) {
            window.showNotification('Введите название презентации', 'error');
            return;
        }
        
        fetch('/api/manager/presentation/create-with-property', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
            },
            body: JSON.stringify({
                title: title,
                client_name: clientName,
                property_id: propertyId
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                window.closePresentationModal();
                window.showNotification('Презентация создана и объект добавлен!', 'success');
            } else {
                window.showNotification('Ошибка: ' + data.error, 'error');
            }
        })
        .catch(error => {
            console.error('Error creating presentation with property:', error);
            window.showNotification('Ошибка при создании презентации', 'error');
        });
    };
};

window.createNewPresentationWithComplex = function(complexId) {
    window.closePresentationModal(); // Remove any existing modals first
    const modal = document.createElement('div');
    modal.id = 'newPresentationModal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm';
    
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-semibold text-gray-900">Новая презентация</h3>
            </div>
            <div class="p-6 space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Название презентации</label>
                    <input type="text" id="newPresentationTitle" class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="Например: Презентация для Иванова И.И.">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Имя клиента (необязательно)</label>
                    <input type="text" id="newPresentationClient" class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="ФИО клиента">
                </div>
            </div>
            <div class="p-6 border-t border-gray-200 flex gap-3">
                <button type="button" id="createPresentationBtn" class="flex-1 px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors">Создать</button>
                <button type="button" onclick="window.closePresentationModal()" class="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">Отмена</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    document.getElementById('createPresentationBtn').onclick = function() {
        const title = document.getElementById('newPresentationTitle').value;
        const clientName = document.getElementById('newPresentationClient').value;
        
        if (!title) {
            window.showNotification('Введите название презентации', 'error');
            return;
        }
        
        fetch('/api/manager/presentation/create-with-complex', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
            },
            body: JSON.stringify({
                title: title,
                client_name: clientName,
                complex_id: complexId
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                window.closePresentationModal();
                window.showNotification('Презентация создана и ЖК добавлен!', 'success');
            } else {
                window.showNotification('Ошибка: ' + data.error, 'error');
            }
        })
        .catch(error => {
            console.error('Error creating presentation with complex:', error);
            window.showNotification('Ошибка при создании презентации', 'error');
        });
    };
};

window.closePresentationModal = function() {
    const modals = document.querySelectorAll('#presentationSelectionModal, #newPresentationModal');
    modals.forEach(modal => modal.remove());
};

window.showNotification = function(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = 'fixed top-20 right-4 z-[10060] px-6 py-4 rounded-lg shadow-lg text-white transition-all duration-300';
    notification.style.cssText = `
        background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'}
    `;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
};

console.log('✅ Presentation functions loaded:', {
    openPresentationModal: typeof window.openPresentationModal,
    closePresentationModal: typeof window.closePresentationModal,
    addPropertyToPresentation: typeof window.addPropertyToPresentation
});
