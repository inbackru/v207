/**
 * Complex Offer Uploader
 * Управление акциями для жилых комплексов (только для администраторов)
 */

class ComplexOfferUploader {
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
            <div id="offerUploadModal" class="hidden fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
                <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                    <div class="p-6">
                        <div class="flex justify-between items-center mb-4">
                            <h3 class="text-xl font-bold text-gray-900">Добавить акцию</h3>
                            <button onclick="offerUploader.closeModal()" class="text-gray-400 hover:text-gray-600">
                                <i class="fas fa-times text-2xl"></i>
                            </button>
                        </div>

                        <form id="offerUploadForm" class="space-y-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Название акции *
                                </label>
                                <input type="text" id="offerTitle" placeholder="Скидка 10% при 100% оплате" required
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Описание акции (необязательно)
                                </label>
                                <textarea id="offerDescription" rows="3" placeholder="Подробное описание условий акции" 
                                          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"></textarea>
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Изображение акции *
                                </label>
                                <div class="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
                                    <input type="file" id="offerImage" accept="image/jpeg,image/png,image/webp,image/jpg" 
                                           class="hidden" onchange="offerUploader.handleFileSelect(event)" required>
                                    <i class="fas fa-image text-4xl text-gray-400 mb-3"></i>
                                    <p class="text-gray-600 mb-2">Перетащите изображение сюда или</p>
                                    <button type="button" onclick="document.getElementById('offerImage').click()" 
                                            class="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg">
                                        Выбрать файл
                                    </button>
                                    <p class="text-xs text-gray-500 mt-3">
                                        JPG, PNG или WebP, до 5 МБ
                                    </p>
                                </div>
                            </div>

                            <div id="imagePreview" class="hidden mt-4">
                                <label class="block text-sm font-medium text-gray-700 mb-2">Предпросмотр:</label>
                                <div class="relative">
                                    <img id="previewImg" src="" alt="Preview" class="w-full h-48 object-cover rounded-lg">
                                    <button type="button" onclick="offerUploader.clearImage()" 
                                            class="absolute top-2 right-2 bg-red-500 hover:bg-red-600 text-white p-2 rounded-full">
                                        <i class="fas fa-times"></i>
                                    </button>
                                </div>
                                <p class="text-sm text-gray-600 mt-2">
                                    <strong>Файл:</strong> <span id="fileName"></span><br>
                                    <strong>Размер:</strong> <span id="fileSize"></span>
                                </p>
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Порядок отображения
                                </label>
                                <input type="number" id="offerSortOrder" value="0" min="0" 
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <p class="text-xs text-gray-500 mt-1">Меньшее число = выше в списке</p>
                            </div>

                            <button type="submit" 
                                    class="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg font-medium transition-colors">
                                <i class="fas fa-save mr-2"></i>Сохранить акцию
                            </button>

                            <div id="uploadProgress" class="hidden mt-4">
                                <div class="bg-gray-200 rounded-full h-2 mb-2">
                                    <div id="progressBar" class="bg-blue-600 h-2 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <p class="text-sm text-center text-gray-600"><span id="progressText">Загрузка...</span></p>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.setupFormSubmit();
    }

    setupFormSubmit() {
        const form = document.getElementById('offerUploadForm');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitOffer();
        });
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;

        // Check file size (5MB max)
        if (file.size > 5 * 1024 * 1024) {
            alert('Файл слишком большой. Максимальный размер: 5 МБ');
            event.target.value = '';
            return;
        }

        // Check file type
        if (!file.type.match(/^image\/(jpeg|jpg|png|webp)$/)) {
            alert('Неподдерживаемый формат файла. Используйте JPG, PNG или WebP');
            event.target.value = '';
            return;
        }

        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('previewImg').src = e.target.result;
            document.getElementById('imagePreview').classList.remove('hidden');
        };
        reader.readAsDataURL(file);

        // Show file info
        document.getElementById('fileName').textContent = file.name;
        document.getElementById('fileSize').textContent = this.formatFileSize(file.size);
    }

    clearImage() {
        document.getElementById('offerImage').value = '';
        document.getElementById('imagePreview').classList.add('hidden');
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

    openModal() {
        document.getElementById('offerUploadModal').classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }

    closeModal() {
        document.getElementById('offerUploadModal').classList.add('hidden');
        document.body.style.overflow = '';
        this.resetForm();
    }

    resetForm() {
        document.getElementById('offerUploadForm').reset();
        document.getElementById('imagePreview').classList.add('hidden');
        document.getElementById('uploadProgress').classList.add('hidden');
        document.getElementById('progressBar').style.width = '0%';
    }

    async submitOffer() {
        const title = document.getElementById('offerTitle').value.trim();
        const description = document.getElementById('offerDescription').value.trim();
        const sortOrder = document.getElementById('offerSortOrder').value;
        const fileInput = document.getElementById('offerImage');
        const file = fileInput.files[0];

        if (!title) {
            alert('Введите название акции');
            return;
        }

        if (!file) {
            alert('Выберите изображение для акции');
            return;
        }

        const formData = new FormData();
        formData.append('title', title);
        formData.append('description', description);
        formData.append('sort_order', sortOrder);
        formData.append('image', file);

        try {
            document.getElementById('uploadProgress').classList.remove('hidden');
            const submitBtn = document.querySelector('#offerUploadForm button[type="submit"]');
            submitBtn.disabled = true;

            const response = await fetch(`/api/admin/complex/${this.complexId}/offer/add`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                alert('Акция успешно добавлена!');
                this.closeModal();
                location.reload(); // Перезагружаем страницу чтобы показать новую акцию
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось добавить акцию'));
                submitBtn.disabled = false;
            }
        } catch (error) {
            console.error('Error adding offer:', error);
            alert('Произошла ошибка при добавлении акции');
            document.querySelector('#offerUploadForm button[type="submit"]').disabled = false;
        } finally {
            document.getElementById('uploadProgress').classList.add('hidden');
        }
    }
}

// Инициализация при загрузке страницы
let offerUploader = null;

document.addEventListener('DOMContentLoaded', function() {
    const complexId = document.querySelector('[data-complex-id]')?.dataset.complexId;
    const complexSlug = document.querySelector('[data-complex-slug]')?.dataset.complexSlug;
    
    if (complexId && complexSlug && window.admin_authenticated) {
        offerUploader = new ComplexOfferUploader(complexId, complexSlug);
        console.log('✅ Offer uploader initialized for admin');
    }
});
