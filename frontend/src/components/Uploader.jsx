import React, { useCallback, useState } from 'react';
import { UploadCloud, FileVideo, CheckCircle2 } from 'lucide-react';
import { API_BASE } from '../api';

export default function Uploader({ onUploadSuccess }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true);
    } else if (e.type === 'dragleave') {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files[0]);
    }
  }, []);

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files[0]);
    }
  };

  const handleFiles = async (file) => {
    if (!file.type.includes('video')) {
      alert('Vui lòng chọn file video!');
      return;
    }
    
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        onUploadSuccess(data.filename);
      } else {
        alert('Lỗi upload: ' + data.message);
      }
    } catch (error) {
      console.error(error);
      alert('Không thể kết nối đến Backend');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.1s' }}>
      <h3 style={{ marginBottom: '16px', color: 'var(--text-main)' }}>Tải Video Lên</h3>
      
      <div 
        className={`upload-zone ${isDragging ? 'drag-active' : ''}`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <div className="upload-icon">
          {isUploading ? <UploadCloud className="animate-pulse" /> : <FileVideo />}
        </div>
        
        <div>
          <h4 style={{ marginBottom: '8px' }}>Kéo thả file video vào đây</h4>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '16px' }}>
            Hỗ trợ MP4, MKV, AVI (Tối đa 500MB)
          </p>
          <label className="btn btn-primary">
            {isUploading ? 'Đang tải lên...' : 'Chọn file'}
            <input 
              type="file" 
              accept="video/*" 
              style={{ display: 'none' }} 
              onChange={handleChange}
              disabled={isUploading}
            />
          </label>
        </div>
      </div>
    </div>
  );
}
