// Expense Receipt File Upload JavaScript

class ExpenseFileUpload {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            maxFiles: options.maxFiles || 5,
            maxFileSize: options.maxFileSize || 10 * 1024 * 1024, // 10MB
            acceptedTypes: options.acceptedTypes || ['pdf', 'jpg', 'jpeg', 'png'],
            receiptId: options.receiptId || null,
            onUpload: options.onUpload || null,
            onError: options.onError || null,
            onProgress: options.onProgress || null
        };
        
        this.uploadedFiles = [];
        this.init();
    }
    
    init() {
        if (!this.container) {
            console.error('Upload container not found');
            return;
        }
        
        this.createUploadInterface();
        this.attachEventListeners();
    }
    
    createUploadInterface() {
        this.container.innerHTML = `
            <div class="file-upload-zone" id="dropZone">
                <div class="upload-content">
                    <i class="fa fa-cloud-upload-alt upload-icon"></i>
                    <h3>Drag & drop receipt files here</h3>
                    <p>or <button type="button" class="btn-link" id="browseFiles">browse files</button></p>
                    <small class="upload-hint">
                        Supported formats: ${this.options.acceptedTypes.join(', ').toUpperCase()} 
                        (Max ${this.options.maxFileSize / (1024 * 1024)}MB per file)
                    </small>
                </div>
                <input type="file" id="fileInput" multiple 
                       accept=".${this.options.acceptedTypes.join(',.')}" 
                       style="display: none;">
            </div>
            
            <div class="upload-progress" id="uploadProgress" style="display: none;">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <span class="progress-text" id="progressText">Uploading...</span>
            </div>
            
            <div class="uploaded-files-list" id="uploadedFilesList" style="display: none;">
                <h4>Attached Files</h4>
                <div class="files-grid" id="filesGrid"></div>
            </div>
        `;
    }
    
    attachEventListeners() {
        const dropZone = this.container.querySelector('#dropZone');
        const fileInput = this.container.querySelector('#fileInput');
        const browseBtn = this.container.querySelector('#browseFiles');
        
        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, this.preventDefaults, false);
            document.body.addEventListener(eventName, this.preventDefaults, false);
        });
        
        // Highlight drop zone when item is dragged over it
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => this.highlight(), false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => this.unhighlight(), false);
        });
        
        // Handle dropped files
        dropZone.addEventListener('drop', (e) => this.handleDrop(e), false);
        
        // Handle file input changes
        fileInput.addEventListener('change', (e) => this.handleFiles(e.target.files), false);
        
        // Handle browse button click
        browseBtn.addEventListener('click', () => fileInput.click(), false);
    }
    
    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    highlight() {
        const dropZone = this.container.querySelector('#dropZone');
        dropZone.classList.add('drag-over');
    }
    
    unhighlight() {
        const dropZone = this.container.querySelector('#dropZone');
        dropZone.classList.remove('drag-over');
    }
    
    handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        this.handleFiles(files);
    }
    
    handleFiles(files) {
        if (!files.length) return;
        
        // Check file count limit
        if (this.uploadedFiles.length + files.length > this.options.maxFiles) {
            this.showError(`Maximum ${this.options.maxFiles} files allowed`);
            return;
        }
        
        // Process each file
        Array.from(files).forEach(file => {
            if (this.validateFile(file)) {
                this.uploadFile(file);
            }
        });
    }
    
    validateFile(file) {
        // Check file type
        const extension = file.name.split('.').pop().toLowerCase();
        if (!this.options.acceptedTypes.includes(extension)) {
            this.showError(`File type ${extension} not supported`);
            return false;
        }
        
        // Check file size
        if (file.size > this.options.maxFileSize) {
            this.showError(`File too large. Maximum size: ${this.formatFileSize(this.options.maxFileSize)}`);
            return false;
        }
        
        return true;
    }
    
    async uploadFile(file) {
        try {
            const formData = new FormData();
            formData.append('file', file);
            if (this.options.receiptId) {
                formData.append('receipt_id', this.options.receiptId);
            }
            
            this.showProgress();
            
            const response = await fetch('/api/expenses/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || 'Upload failed');
            }
            
            // Add to uploaded files list
            const uploadedFile = {
                id: result.filename,
                name: file.name,
                url: result.url,
                size: result.file_info.size,
                type: result.file_info.extension,
                uploadedAt: new Date().toISOString()
            };
            
            this.uploadedFiles.push(uploadedFile);
            this.updateFilesList();
            this.hideProgress();
            
            // Call onUpload callback
            if (this.options.onUpload) {
                this.options.onUpload(uploadedFile);
            }
            
        } catch (error) {
            this.hideProgress();
            this.showError(error.message);
            
            if (this.options.onError) {
                this.options.onError(error);
            }
        }
    }
    
    showProgress() {
        const progressContainer = this.container.querySelector('#uploadProgress');
        progressContainer.style.display = 'block';
    }
    
    hideProgress() {
        const progressContainer = this.container.querySelector('#uploadProgress');
        progressContainer.style.display = 'none';
    }
    
    updateFilesList() {
        const filesList = this.container.querySelector('#uploadedFilesList');
        const filesGrid = this.container.querySelector('#filesGrid');
        
        if (this.uploadedFiles.length === 0) {
            filesList.style.display = 'none';
            return;
        }
        
        filesList.style.display = 'block';
        
        filesGrid.innerHTML = this.uploadedFiles.map(file => `
            <div class="file-item" data-file-id="${file.id}">
                <div class="file-icon">
                    ${this.getFileIcon(file.type)}
                </div>
                <div class="file-info">
                    <div class="file-name" title="${file.name}">${this.truncateFileName(file.name)}</div>
                    <div class="file-size">${this.formatFileSize(file.size)}</div>
                </div>
                <div class="file-actions">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="previewFile('${file.url}')">
                        <i class="fa fa-eye"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-danger" onclick="removeFile('${file.id}')">
                        <i class="fa fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    }
    
    getFileIcon(type) {
        switch (type.toLowerCase()) {
            case 'pdf':
                return '<i class="fa fa-file-pdf text-danger"></i>';
            case 'jpg':
            case 'jpeg':
            case 'png':
                return '<i class="fa fa-file-image text-primary"></i>';
            default:
                return '<i class="fa fa-file text-secondary"></i>';
        }
    }
    
    truncateFileName(name, maxLength = 20) {
        if (name.length <= maxLength) return name;
        const extension = name.split('.').pop();
        const baseName = name.slice(0, -(extension.length + 1));
        return `${baseName.slice(0, maxLength - extension.length - 4)}...${extension}`;
    }
    
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    showError(message) {
        // Show error message (can be enhanced with a proper notification system)
        alert(message);
    }
    
    removeFile(fileId) {
        this.uploadedFiles = this.uploadedFiles.filter(f => f.id !== fileId);
        this.updateFilesList();
    }
    
    clearAll() {
        this.uploadedFiles = [];
        this.updateFilesList();
    }
    
    getUploadedFiles() {
        return this.uploadedFiles;
    }
}

// Global functions for file actions
function previewFile(url) {
    window.open(url, '_blank', 'width=800,height=600,scrollbars=yes,resizable=yes');
}

function removeFile(fileId) {
    // This would typically make an API call to delete the file from server
    // For now, just remove from UI
    const fileItem = document.querySelector(`[data-file-id="${fileId}"]`);
    if (fileItem) {
        fileItem.remove();
    }
}

// Initialize file upload when page loads
document.addEventListener('DOMContentLoaded', function() {
    // Auto-initialize if container exists
    const uploadContainer = document.getElementById('expense-file-upload');
    if (uploadContainer) {
        const receiptId = uploadContainer.dataset.receiptId || null;
        window.expenseFileUpload = new ExpenseFileUpload('expense-file-upload', {
            receiptId: receiptId,
            onUpload: function(file) {
                console.log('File uploaded:', file);
            },
            onError: function(error) {
                console.error('Upload error:', error);
            }
        });
    }
});