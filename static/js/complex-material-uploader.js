/**
 * Complex Marketing Material Uploader
 * Управление маркетинговыми материалами для жилых комплексов (только для администраторов)
 */

class ComplexMaterialUploader {
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
            <div id="materialUploadModal" class="hidden fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
                <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                    <div class="p-6">
                        <div class="flex justify-between items-center mb-4">
                            <h3 class="text-xl font-bold text-gray-900">Добавить материал</h3>
                            <button onclick="materialUploader.closeModal()" class="text-gray-400 hover:text-gray-600">
                                <i class="fas fa-times text-2xl"></i>
                            </button>
                        </div>

                        <form id="materialUploadForm" class="space-y-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Название материала *
                                </label>
                                <input type="text" id="materialTitle" placeholder="Презентация ЖК" required
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Тип материала *
                                </label>
                                <select id="materialType" required
                                        class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                    <option value="">Выберите тип</option>
                                    <option value="Буклет">Буклет</option>
                                    <option value="Фото">Фото</option>
                                    <option value="Рендер">Рендер</option>
                                    <option value="Другое">Другое</option>
                                </select>
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Описание (необязательно)
                                </label>
                                <textarea id="materialDescription" rows="3" placeholder="Подробное описание материала" 
                                          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"></textarea>
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Файл *
                                </label>
                                <div class="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
                                    <input type="file" id="materialFile" 
                                           accept="application/pdf,image/jpeg,image/png,image/webp,image/jpg" 
                                           class="hidden" onchange="materialUploader.handleFileSelect(event)" required>
                                    <i class="fas fa-file-upload text-4xl text-gray-400 mb-3"></i>
                                    <p class="text-gray-600 mb-2">Перетащите файл сюда или</p>
                                    <button type="button" onclick="document.getElementById('materialFile').click()" 
                                            class="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg">
                                        Выбрать файл
                                    </button>
                                    <p class="text-xs text-gray-500 mt-3">
                                        PDF (до 10 МБ) или изображение JPG, PNG, WebP (до 5 МБ)
                                    </p>
                                </div>
                            </div>

                            <div id="filePreview" class="hidden mt-4">
                                <label class="block text-sm font-medium text-gray-700 mb-2">Выбранный файл:</label>
                                <div class="bg-gray-50 p-4 rounded-lg">
                                    <div class="flex items-center justify-between">
                                        <div class="flex items-center space-x-3">
                                            <i id="fileIcon" class="fas fa-file text-3xl text-blue-500"></i>
                                            <div>
                                                <p class="font-medium text-gray-900" id="fileName"></p>
                                                <p class="text-sm text-gray-600" id="fileSize"></p>
                                            </div>
                                        </div>
                                        <button type="button" onclick="materialUploader.clearFile()" 
                                                class="bg-red-500 hover:bg-red-600 text-white p-2 rounded-full">
                                            <i class="fas fa-times"></i>
                                        </button>
                                    </div>
                                    <div id="imagePreviewContainer" class="hidden mt-3">
                                        <img id="imagePreview" src="" alt="Preview" class="w-full h-48 object-cover rounded-lg">
                                    </div>
                                </div>
                            </div>

                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-1">
                                    Порядок отображения
                                </label>
                                <input type="number" id="materialSortOrder" value="0" min="0" 
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <p class="text-xs text-gray-500 mt-1">Меньшее число = выше в списке</p>
                            </div>

                            <button type="submit" 
                                    class="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg font-medium transition-colors">
                                <i class="fas fa-save mr-2"></i>Сохранить материал
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
        const form = document.getElementById('materialUploadForm');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitMaterial();
        });
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;

        // Check file type and size
        const isPDF = file.type === 'application/pdf';
        const isImage = file.type.match(/^image\/(jpeg|jpg|png|webp)$/);

        if (!isPDF && !isImage) {
            alert('Неподдерживаемый формат файла. Используйте PDF или изображения (JPG, PNG, WebP)');
            event.target.value = '';
            return;
        }

        // Check file size
        const maxSize = isPDF ? 10 * 1024 * 1024 : 5 * 1024 * 1024; // 10MB for PDF, 5MB for images
        if (file.size > maxSize) {
            const maxSizeMB = isPDF ? 10 : 5;
            alert(`Файл слишком большой. Максимальный размер: ${maxSizeMB} МБ`);
            event.target.value = '';
            return;
        }

        // Show file info
        document.getElementById('fileName').textContent = file.name;
        document.getElementById('fileSize').textContent = this.formatFileSize(file.size);
        document.getElementById('filePreview').classList.remove('hidden');

        // Update icon based on file type
        const fileIcon = document.getElementById('fileIcon');
        if (isPDF) {
            fileIcon.className = 'fas fa-file-pdf text-3xl text-red-500';
            document.getElementById('imagePreviewContainer').classList.add('hidden');
        } else if (isImage) {
            fileIcon.className = 'fas fa-file-image text-3xl text-green-500';
            // Show image preview
            const reader = new FileReader();
            reader.onload = (e) => {
                document.getElementById('imagePreview').src = e.target.result;
                document.getElementById('imagePreviewContainer').classList.remove('hidden');
            };
            reader.readAsDataURL(file);
        }
    }

    clearFile() {
        document.getElementById('materialFile').value = '';
        document.getElementById('filePreview').classList.add('hidden');
        document.getElementById('imagePreviewContainer').classList.add('hidden');
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
        document.getElementById('materialUploadModal').classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }

    closeModal() {
        document.getElementById('materialUploadModal').classList.add('hidden');
        document.body.style.overflow = '';
        this.resetForm();
    }

    resetForm() {
        document.getElementById('materialUploadForm').reset();
        document.getElementById('filePreview').classList.add('hidden');
        document.getElementById('uploadProgress').classList.add('hidden');
        document.getElementById('progressBar').style.width = '0%';
        document.getElementById('imagePreviewContainer').classList.add('hidden');
    }

    async submitMaterial() {
        const title = document.getElementById('materialTitle').value.trim();
        const materialType = document.getElementById('materialType').value;
        const description = document.getElementById('materialDescription').value.trim();
        const sortOrder = document.getElementById('materialSortOrder').value;
        const fileInput = document.getElementById('materialFile');
        const file = fileInput.files[0];

        if (!title) {
            alert('Введите название материала');
            return;
        }

        if (!materialType) {
            alert('Выберите тип материала');
            return;
        }

        if (!file) {
            alert('Выберите файл');
            return;
        }

        const formData = new FormData();
        formData.append('title', title);
        formData.append('material_type', materialType);
        formData.append('description', description);
        formData.append('sort_order', sortOrder);
        formData.append('file', file);

        try {
            document.getElementById('uploadProgress').classList.remove('hidden');
            const submitBtn = document.querySelector('#materialUploadForm button[type="submit"]');
            submitBtn.disabled = true;

            const response = await fetch(`/api/admin/complex/${this.complexId}/material/add`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                alert('Материал успешно добавлен!');
                this.closeModal();
                location.reload(); // Перезагружаем страницу чтобы показать новый материал
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось добавить материал'));
                submitBtn.disabled = false;
            }
        } catch (error) {
            console.error('Error adding material:', error);
            alert('Произошла ошибка при добавлении материала');
            document.querySelector('#materialUploadForm button[type="submit"]').disabled = false;
        } finally {
            document.getElementById('uploadProgress').classList.add('hidden');
        }
    }
}

// Инициализация при загрузке страницы
let materialUploader = null;

document.addEventListener('DOMContentLoaded', function() {
    const complexId = document.querySelector('[data-complex-id]')?.dataset.complexId;
    const complexSlug = document.querySelector('[data-complex-slug]')?.dataset.complexSlug;
    
    if (complexId && complexSlug && window.admin_authenticated) {
        materialUploader = new ComplexMaterialUploader(complexId, complexSlug);
        console.log('✅ Material uploader initialized for admin');
    }
});
