"""
Admin Interface - Nhập kết quả Bingo 18 thủ công
"""

from flask import request, jsonify, render_template_string
from functools import wraps
from app import app, db
from datetime import datetime
import json
import config

# ── Auth decorator ────────────────────────────────────────────────────────────
def require_admin_key(f):
    """Yêu cầu header X-Admin-Key khớp ADMIN_SECRET_KEY"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Admin-Key", "")
        if key != config.ADMIN_SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ── HTML template ─────────────────────────────────────────────────────────────
ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - Nhập Kết Quả Bingo 18</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .admin-container {
            max-width: 600px;
            margin: 50px auto;
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        .number-input {
            width: 80px;
            height: 80px;
            font-size: 2rem;
            text-align: center;
            font-weight: bold;
            border: 3px solid #667eea;
            border-radius: 50%;
            margin: 10px;
        }
        .number-input:focus {
            border-color: #764ba2;
            box-shadow: 0 0 10px rgba(118, 75, 162, 0.5);
        }
        .btn-submit {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            padding: 15px 50px;
            font-size: 1.2rem;
            font-weight: bold;
            color: white;
            border-radius: 50px;
            margin-top: 20px;
        }
        .btn-submit:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(118, 75, 162, 0.4);
        }
        .alert { margin-top: 20px; border-radius: 10px; }
        h2 { color: #667eea; text-align: center; margin-bottom: 30px; }
        .number-container { display: flex; justify-content: center; align-items: center; }
        .recent-draws { margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 10px; }
    </style>
</head>
<body>
    <div class="admin-container">
        <h2>NHẬP KẾT QUẢ BINGO 18</h2>

        <!-- Nhập admin key -->
        <div class="mb-3">
            <label class="form-label"><strong>Admin Key:</strong></label>
            <input type="password" class="form-control" id="adminKey" placeholder="Nhập admin key">
        </div>

        <div class="mb-4">
            <label class="form-label"><strong>Kỳ số:</strong></label>
            <input type="number" class="form-control" id="drawNumber" required placeholder="Ví dụ: 1001">
        </div>

        <div class="mb-4">
            <label class="form-label"><strong>3 Số kết quả (1-6):</strong></label>
            <div class="number-container">
                <input type="number" class="form-control number-input" id="num1" min="1" max="6" required>
                <input type="number" class="form-control number-input" id="num2" min="1" max="6" required>
                <input type="number" class="form-control number-input" id="num3" min="1" max="6" required>
            </div>
        </div>

        <div class="text-center">
            <button type="button" class="btn btn-submit" onclick="submitResult()">LƯU KẾT QUẢ</button>
        </div>

        <div id="message"></div>

        <div class="recent-draws">
            <h5>Kết quả gần đây:</h5>
            <div id="recentList" class="mt-3">Đang tải...</div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function getKey() {
            return document.getElementById('adminKey').value;
        }

        async function loadRecent() {
            try {
                const response = await fetch('/api/recent_draws?limit=5');
                const draws = await response.json();
                const list = document.getElementById('recentList');
                if (!draws.length) {
                    list.innerHTML = '<em class="text-muted">Chưa có kết quả nào</em>';
                    return;
                }
                list.innerHTML = draws.map(draw => `
                    <div class="d-flex justify-content-between align-items-center mb-2 p-2 bg-white rounded">
                        <span><strong>Kỳ ${draw.draw_number}:</strong></span>
                        <span class="badge bg-primary">${draw.numbers.join(' - ')}</span>
                        <span class="text-muted small">${new Date(draw.draw_time).toLocaleString('vi-VN')}</span>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Error loading recent draws:', error);
            }
        }

        async function submitResult() {
            const drawNumber = document.getElementById('drawNumber').value;
            const num1 = parseInt(document.getElementById('num1').value);
            const num2 = parseInt(document.getElementById('num2').value);
            const num3 = parseInt(document.getElementById('num3').value);
            const numbers = [num1, num2, num3];

            if (numbers.some(n => isNaN(n) || n < 1 || n > 6)) {
                showMessage('Số phải từ 1 đến 6!', 'danger'); return;
            }

            try {
                const response = await fetch('/api/admin/submit-result', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Key': getKey()
                    },
                    body: JSON.stringify({ draw_number: parseInt(drawNumber), numbers })
                });
                const result = await response.json();
                if (response.ok) {
                    showMessage('✅ Đã lưu kết quả thành công!', 'success');
                    document.getElementById('num1').value = '';
                    document.getElementById('num2').value = '';
                    document.getElementById('num3').value = '';
                    document.getElementById('drawNumber').value = parseInt(drawNumber) + 1;
                    loadRecent();
                } else {
                    showMessage('❌ Lỗi: ' + result.error, 'danger');
                }
            } catch (error) {
                showMessage('❌ Lỗi kết nối: ' + error.message, 'danger');
            }
        }

        function showMessage(text, type) {
            const msgDiv = document.getElementById('message');
            msgDiv.innerHTML = `<div class="alert alert-${type}">${text}</div>`;
            setTimeout(() => { msgDiv.innerHTML = ''; }, 5000);
        }

        // Auto jump between number inputs
        ['num1', 'num2'].forEach((id, index) => {
            document.getElementById(id).addEventListener('input', function() {
                if (this.value.length === 1) {
                    document.getElementById(index === 0 ? 'num2' : 'num3').focus();
                }
            });
        });

        loadRecent();
        setInterval(loadRecent, 30000);
    </script>
</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/admin')
def admin_interface():
    """Admin interface for manual result input"""
    return render_template_string(ADMIN_TEMPLATE)


@app.route('/api/admin/submit-result', methods=['POST'])
@require_admin_key
def submit_result():
    """API endpoint to submit result manually"""
    try:
        data = request.json
        draw_number = data.get('draw_number')
        numbers = data.get('numbers')

        if not draw_number or numbers is None:
            return jsonify({'error': 'Missing draw_number or numbers'}), 400
        if len(numbers) != 3:
            return jsonify({'error': 'Must have exactly 3 numbers'}), 400
        if not all(1 <= n <= 6 for n in numbers):
            return jsonify({'error': 'Numbers must be between 1 and 6'}), 400

        # Insert into database
        result_id = db.insert_draw(draw_number, numbers, datetime.now())
        if result_id == -1:
            return jsonify({'error': 'Draw number already exists'}), 400

        # process_actual_result handles update_cold_numbers + markov online + telegram
        from prediction_service import process_actual_result
        result_info = process_actual_result(draw_number, numbers)

        return jsonify({
            'success':     True,
            'draw_number': draw_number,
            'numbers':     numbers,
            'result_id':   result_id,
            'prediction':  result_info
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Admin interface available at: http://localhost:5000/admin")
