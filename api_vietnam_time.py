"""
Bingo18 API - Vietnam Timezone Fix
Example code to fetch predictions with correct Vietnam time
"""

from supabase import create_client
import os

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']

class Bingo18API:
    def __init__(self):
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    def get_latest_prediction_vietnam_time(self):
        """
        Get latest prediction with Vietnam timezone
        Returns prediction with display_time_vietnam (e.g., "16:01")
        """
        result = self.supabase.table('predictions_vn')\
            .select('draw_number, predicted_numbers, model_name, confidence, display_time_vietnam, full_time_vietnam')\
            .order('draw_number', desc=True)\
            .limit(1)\
            .execute()
        
        if result.data:
            pred = result.data[0]
            return {
                'draw_number': pred['draw_number'],
                'prediction': pred['predicted_numbers'],
                'model': pred['model_name'],
                'confidence': pred['confidence'],
                'update_time': pred['display_time_vietnam'],  # "16:01" format
                'full_time': pred['full_time_vietnam']  # "2026-04-30 16:01:42"
            }
        return None
    
    def get_current_vietnam_time(self):
        """Get current time in Vietnam timezone"""
        result = self.supabase.rpc('vietnam_now').execute()
        if result.data:
            return result.data
        return None
    
    def get_recent_predictions_with_results(self, limit=10):
        """
        Get recent predictions with results, all in Vietnam time
        """
        result = self.supabase.table('predictions_vn')\
            .select('''
                draw_number,
                predicted_numbers,
                model_name,
                display_time_vietnam,
                created_at_vietnam
            ''')\
            .order('draw_number', desc=True)\
            .limit(limit)\
            .execute()
        
        return result.data if result.data else []
    
    def format_for_dashboard(self):
        """
        Format data for dashboard display
        Returns JSON ready for frontend
        """
        latest = self.get_latest_prediction_vietnam_time()
        
        if not latest:
            return {
                'success': False,
                'error': 'No predictions available'
            }
        
        return {
            'success': True,
            'next_draw': {
                'draw_number': latest['draw_number'],
                'prediction': latest['prediction'],
                'model': latest['model'],
                'update_time': f"CẬP NHẬT {latest['update_time']}",  # "CẬP NHẬT 16:01"
                'confidence': f"{latest['confidence']:.1%}"
            }
        }


# ========================================
# USAGE EXAMPLE
# ========================================

if __name__ == '__main__':
    api = Bingo18API()
    
    # Get latest prediction with Vietnam time
    print("📊 LATEST PREDICTION (Vietnam Time):")
    print("=" * 50)
    
    data = api.format_for_dashboard()
    
    if data['success']:
        info = data['next_draw']
        print(f"Kỳ tiếp theo: #{info['draw_number']}")
        print(f"Dự đoán: {info['prediction']}")
        print(f"Model: {info['model']}")
        print(f"Thời gian: {info['update_time']}")  # Shows "CẬP NHẬT 16:01" not "09:01"
        print(f"Confidence: {info['confidence']}")
    else:
        print(f"Error: {data['error']}")
    
    print("\n" + "=" * 50)
    
    # Show current Vietnam time
    current_vn = api.get_current_vietnam_time()
    print(f"Current Vietnam time: {current_vn}")


# ========================================
# FOR FLASK/FASTAPI ENDPOINT
# ========================================

# Flask example:
"""
from flask import Flask, jsonify

app = Flask(__name__)
api = Bingo18API()

@app.route('/api/next-prediction')
def get_next_prediction():
    data = api.format_for_dashboard()
    return jsonify(data)

@app.route('/api/vietnam-time')
def get_vietnam_time():
    vn_time = api.get_current_vietnam_time()
    return jsonify({'vietnam_time': vn_time})
"""

# FastAPI example:
"""
from fastapi import FastAPI

app = FastAPI()
api = Bingo18API()

@app.get("/api/next-prediction")
async def get_next_prediction():
    return api.format_for_dashboard()

@app.get("/api/vietnam-time")
async def get_vietnam_time():
    return {"vietnam_time": api.get_current_vietnam_time()}
"""
