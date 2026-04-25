import os
import uuid
import shutil
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify, url_for
from werkzeug.utils import secure_filename
from PIL import Image
import img2pdf
import fitz

app = Flask(__name__)

# Render pe disk space available hai
UPLOAD_FOLDER = '/tmp/uploads'  # Render allows /tmp write
OUTPUT_FOLDER = '/tmp/outputs'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

ALLOWED_IMAGES = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGES

def cleanup_old_files(folder, hours=1):
    """Delete files older than specified hours"""
    now = datetime.now()
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if (now - modified).seconds > hours * 3600:
                os.remove(filepath)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/convert/images-to-pdf', methods=['POST'])
def images_to_pdf():
    cleanup_old_files(UPLOAD_FOLDER)
    cleanup_old_files(OUTPUT_FOLDER)
    
    if 'images' not in request.files:
        return jsonify({'error': 'No images uploaded'}), 400
    
    files = request.files.getlist('images')
    if not files or files[0].filename == '':
        return jsonify({'error': 'No images selected'}), 400
    
    # Quality setting
    quality = request.form.get('quality', 'high')
    
    image_paths = []
    for file in files:
        if allowed_file(file.filename):
            filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Compress based on quality
            if quality != 'original':
                img = Image.open(filepath)
                quality_val = 95 if quality == 'high' else (75 if quality == 'medium' else 50)
                img.save(filepath, quality=quality_val, optimize=True)
            
            image_paths.append(filepath)
    
    if not image_paths:
        return jsonify({'error': 'No valid images'}), 400
    
    output_filename = f"converted_{uuid.uuid4().hex}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    
    try:
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(image_paths))
        
        # Cleanup images
        for path in image_paths:
            os.remove(path)
        
        return jsonify({
            'success': True,
            'download_url': url_for('download_file', filename=output_filename),
            'message': f'Converted {len(image_paths)} images to PDF'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/convert/pdf-to-images', methods=['POST'])
def pdf_to_images():
    cleanup_old_files(UPLOAD_FOLDER)
    cleanup_old_files(OUTPUT_FOLDER)
    
    if 'pdf' not in request.files:
        return jsonify({'error': 'No PDF uploaded'}), 400
    
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({'error': 'No PDF selected'}), 400
    
    # Get settings
    image_format = request.form.get('image_format', 'png')
    dpi = int(request.form.get('dpi', 150))
    quality = request.form.get('quality', 'high')
    
    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    output_folder = os.path.join(OUTPUT_FOLDER, f"pdf_{uuid.uuid4().hex}")
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        doc = fitz.open(filepath)
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        image_paths = []
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix)
            
            img_filename = f"page_{page_num + 1}.{image_format}"
            img_path = os.path.join(output_folder, img_filename)
            
            if image_format == 'png':
                pix.save(img_path)
            else:
                img = Image.open(io.BytesIO(pix.tobytes()))
                quality_val = 95 if quality == 'high' else (75 if quality == 'medium' else 50)
                img.save(img_path, quality=quality_val, optimize=True)
            
            image_paths.append(img_path)
        
        doc.close()
        
        # Create ZIP
        zip_filename = f"images_{uuid.uuid4().hex}.zip"
        zip_path = os.path.join(OUTPUT_FOLDER, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for img in image_paths:
                zipf.write(img, os.path.basename(img))
        
        # Cleanup
        shutil.rmtree(output_folder)
        os.remove(filepath)
        
        return jsonify({
            'success': True,
            'download_url': url_for('download_file', filename=zip_filename),
            'message': f'Converted {len(image_paths)} pages to {image_format.upper()} images',
            'page_count': len(image_paths)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(OUTPUT_FOLDER, filename)
    if not os.path.exists(filepath):
        return "File not found", 404
    
    return send_file(filepath, as_attachment=True)

@app.route('/api/compress-image', methods=['POST'])
def compress_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    
    file = request.files['image']
    compression = int(request.form.get('compression', 70))
    
    filename = secure_filename(f"compressed_{uuid.uuid4().hex}_{file.filename}")
    filepath = os.path.join(OUTPUT_FOLDER, filename)
    
    img = Image.open(file)
    
    # Get original size
    import io
    orig_buffer = io.BytesIO()
    img.save(orig_buffer, format=img.format)
    original_size = len(orig_buffer.getvalue())
    
    # Compress
    img.save(filepath, quality=compression, optimize=True)
    compressed_size = os.path.getsize(filepath)
    
    reduction = ((original_size - compressed_size) / original_size) * 100
    
    return jsonify({
        'success': True,
        'download_url': url_for('download_file', filename=filename),
        'original_size': original_size,
        'compressed_size': compressed_size,
        'reduction': round(reduction, 2)
    })

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
