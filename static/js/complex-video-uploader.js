/**
 * Complex Video Uploader
 * Управление видео для жилых комплексов (для менеджеров и администраторов)
 */

class ComplexVideoUploader {
    constructor(complexId, complexSlug) {
        this.complexId = complexId;
        this.complexSlug = complexSlug;
        this.initializeUI();
    }

    initializeUI() {
        // Проверяем, является ли пользователь администратором
        if (!window.admin_authenticated) {
            return; // Модальное окно только для администраторов
        }

        this.createModal();
    }

    createModal() {
        const modalHTML = `
            <div id="videoUploadModal" class="hidden fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
                <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                    <div class="p-6">
                        <div class="flex justify-between items-center mb-4">
                            <h3 class="text-xl font-bold text-gray-900">Добавить видео о комплексе</h3>
                            <button onclick="videoUploader.closeModal()" class="text-gray-400 hover:text-gray-600">
                                <i class="fas fa-times text-2xl"></i>
                            </button>
                        </div>

                        <!-- Tabs -->
                        <div class="flex border-b mb-4">
                            <button class="tab-btn active px-4 py-2 border-b-2 border-blue-600 font-medium text-blue-600" data-tab="link">
                                <i class="fas fa-link mr-2"></i>Ссылка на видео
                            </button>
                            <button class="tab-btn px-4 py-2 font-medium text-gray-600 hover:text-blue-600" data-tab="upload">
                                <i class="fas fa-upload mr-2"></i>Загрузить файл
                            </button>
                        </div>

                        <!-- Tab Content: Link -->
                        <div id="link-tab" class="tab-content">
                            <div class="space-y-4">
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">
                                        Платформа
                                    </label>
                                    <select id="videoType" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                        <option value="youtube">YouTube</option>
                                        <option value="rutube">Rutube</option>
                                        <option value="vk">VK Video</option>
                                        <option value="ok">OK.ru</option>
                                        <option value="dzen">Яндекс.Дзен</option>
                                        <option value="vimeo">Vimeo</option>
                                    </select>
                                </div>

                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">
                                        Ссылка на видео *
                                    </label>
                                    <input type="url" id="videoUrl" placeholder="https://www.youtube.com/watch?v=..." 
                                           class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                    <p class="text-xs text-gray-500 mt-1">
                                        Вставьте полную ссылку на видео
                                    </p>
                                </div>

                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">
                                        Название видео *
                                    </label>
                                    <input type="text" id="videoTitle" placeholder="Обзор жилого комплекса" 
                                           class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                </div>

                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">
                                        Описание (необязательно)
                                    </label>
                                    <textarea id="videoDescription" rows="2" placeholder="Краткое описание видео" 
                                              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"></textarea>
                                </div>

                                <button onclick="videoUploader.submitLink()" 
                                        class="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg font-medium transition-colors">
                                    <i class="fas fa-save mr-2"></i>Сохранить ссылку
                                </button>
                            </div>
                        </div>

                        <!-- Tab Content: Upload -->
                        <div id="upload-tab" class="tab-content hidden">
                            <div class="space-y-4">
                                <div class="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                                    <input type="file" id="videoFile" accept="video/mp4,video/webm" class="hidden" onchange="videoUploader.handleFileSelect(event)">
                                    <i class="fas fa-cloud-upload-alt text-4xl text-gray-400 mb-3"></i>
                                    <p class="text-gray-600 mb-2">Перетащите файл сюда или</p>
                                    <button onclick="document.getElementById('videoFile').click()" 
                                            class="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg">
                                        Выбрать файл
                                    </button>
                                    <p class="text-xs text-gray-500 mt-3">
                                        MP4 или WebM, до 50 МБ
                                    </p>
                                </div>

                                <div id="fileInfo" class="hidden bg-gray-50 p-4 rounded-lg">
                                    <p class="text-sm text-gray-700"><strong>Файл:</strong> <span id="fileName"></span></p>
                                    <p class="text-sm text-gray-700"><strong>Размер:</strong> <span id="fileSize"></span></p>
                                </div>

                                <button onclick="videoUploader.submitFile()" id="uploadFileBtn" 
                                        class="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg font-medium transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed" disabled>
                                    <i class="fas fa-upload mr-2"></i>Загрузить видео
                                </button>

                                <div id="uploadProgress" class="hidden">
                                    <div class="bg-gray-200 rounded-full h-2 mb-2">
                                        <div id="progressBar" class="bg-blue-600 h-2 rounded-full transition-all" style="width: 0%"></div>
                                    </div>
                                    <p class="text-sm text-center text-gray-600"><span id="progressText">0%</span></p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.initializeTabs();
    }

    initializeTabs() {
        const tabs = document.querySelectorAll('.tab-btn');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                
                // Update tab buttons
                tabs.forEach(t => t.classList.remove('active', 'border-blue-600', 'text-blue-600'));
                tabs.forEach(t => t.classList.add('text-gray-600'));
                tab.classList.add('active', 'border-blue-600', 'text-blue-600');
                tab.classList.remove('text-gray-600');

                // Update tab content
                document.querySelectorAll('.tab-content').forEach(content => content.classList.add('hidden'));
                document.getElementById(`${tabName}-tab`).classList.remove('hidden');
            });
        });
    }

    openModal() {
        document.getElementById('videoUploadModal').classList.remove('hidden');
    }

    closeModal() {
        document.getElementById('videoUploadModal').classList.add('hidden');
        this.resetForm();
    }

    resetForm() {
        document.getElementById('videoUrl').value = '';
        document.getElementById('videoTitle').value = '';
        document.getElementById('videoDescription').value = '';
        document.getElementById('videoFile').value = '';
        document.getElementById('fileInfo').classList.add('hidden');
        document.getElementById('uploadFileBtn').disabled = true;
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;

        // Check file size (50MB max)
        if (file.size > 50 * 1024 * 1024) {
            alert('Файл слишком большой. Максимальный размер: 50 МБ');
            return;
        }

        // Show file info
        document.getElementById('fileName').textContent = file.name;
        document.getElementById('fileSize').textContent = this.formatFileSize(file.size);
        document.getElementById('fileInfo').classList.remove('hidden');
        document.getElementById('uploadFileBtn').disabled = false;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    getCSRFToken() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    async submitLink() {
        const url = document.getElementById('videoUrl').value.trim();
        const title = document.getElementById('videoTitle').value.trim();
        const description = document.getElementById('videoDescription').value.trim();
        const type = document.getElementById('videoType').value;

        if (!url || !title) {
            alert('Заполните обязательные поля');
            return;
        }

        try {
            const response = await fetch(`/api/manager/complex/${this.complexId}/video/add-link`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ url, title, description, type })
            });

            const data = await response.json();

            if (data.success) {
                alert('Видео успешно добавлено!');
                this.closeModal();
                location.reload(); // Перезагружаем страницу чтобы показать видео
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось добавить видео'));
            }
        } catch (error) {
            console.error('Error adding video link:', error);
            alert('Произошла ошибка при добавлении видео');
        }
    }

    async submitFile() {
        const fileInput = document.getElementById('videoFile');
        const file = fileInput.files[0];

        if (!file) {
            alert('Выберите файл для загрузки');
            return;
        }

        const formData = new FormData();
        formData.append('video', file);

        try {
            document.getElementById('uploadProgress').classList.remove('hidden');
            document.getElementById('uploadFileBtn').disabled = true;

            const response = await fetch(`/api/manager/complex/${this.complexId}/video/upload`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                alert('Видео успешно загружено!');
                this.closeModal();
                location.reload();
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось загрузить видео'));
                document.getElementById('uploadFileBtn').disabled = false;
            }
        } catch (error) {
            console.error('Error uploading video:', error);
            alert('Произошла ошибка при загрузке видео');
            document.getElementById('uploadFileBtn').disabled = false;
        } finally {
            document.getElementById('uploadProgress').classList.add('hidden');
        }
    }
}

// Инициализация при загрузке страницы
let videoUploader = null;

document.addEventListener('DOMContentLoaded', function() {
    const complexId = document.querySelector('[data-complex-id]')?.dataset.complexId;
    const complexSlug = document.querySelector('[data-complex-slug]')?.dataset.complexSlug;
    
    if (complexId && complexSlug) {
        videoUploader = new ComplexVideoUploader(complexId, complexSlug);
    }
});
