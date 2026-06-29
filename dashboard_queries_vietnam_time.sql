-- =====================================================
-- BINGO18 DASHBOARD - VIETNAM TIMEZONE QUERIES
-- =====================================================
-- Use these queries in your dashboard/app to display correct Vietnam time

-- =====================================================
-- 1. GET LATEST PREDICTION (for "Dự đoán tiếp theo")
-- =====================================================
SELECT 
    draw_number,
    predicted_numbers,
    model_name,
    confidence,
    display_time_vietnam as update_time,  -- Use this for display: "CẬP NHẬT 16:01"
    full_time_vietnam as full_time
FROM predictions_vn
ORDER BY draw_number DESC
LIMIT 1;

-- Result example:
-- draw_number: 164675
-- predicted_numbers: [2, 4, 6]
-- update_time: "16:01"  ← Display this instead of "09:01"
-- full_time: "2026-04-30 16:01:42"


-- =====================================================
-- 2. GET RECENT PREDICTIONS WITH RESULTS
-- =====================================================
SELECT 
    p.draw_number,
    p.predicted_numbers,
    p.model_name,
    p.display_time_vietnam as prediction_time,
    dh.numbers as actual_numbers,
    dh.display_time_vietnam as draw_time,
    pr.is_win,
    pr.match_count
FROM predictions_vn p
LEFT JOIN draw_history_vn dh ON p.draw_number = dh.draw_number
LEFT JOIN prediction_results pr ON p.id = pr.prediction_id
ORDER BY p.draw_number DESC
LIMIT 20;

-- Result shows Vietnam time for both predictions and draws


-- =====================================================
-- 3. GET CURRENT VIETNAM TIME
-- =====================================================
SELECT 
    vietnam_now() as current_time,
    TO_CHAR(vietnam_now(), 'HH24:MI') as display_time,
    TO_CHAR(vietnam_now(), 'DD/MM/YYYY HH24:MI:SS') as full_display;

-- Result example:
-- current_time: 2026-04-30 16:06:13
-- display_time: "16:06"
-- full_display: "30/04/2026 16:06:13"


-- =====================================================
-- 4. CHECK IF PREDICTION TIME IS RECENT (within 5 minutes)
-- =====================================================
SELECT 
    draw_number,
    predicted_numbers,
    display_time_vietnam,
    CASE 
        WHEN created_at_vietnam >= vietnam_now() - INTERVAL '5 minutes' 
        THEN 'FRESH'
        ELSE 'OLD'
    END as freshness,
    EXTRACT(EPOCH FROM (vietnam_now() - created_at_vietnam))/60 as minutes_ago
FROM predictions_vn
ORDER BY draw_number DESC
LIMIT 5;


-- =====================================================
-- 5. DASHBOARD STATS WITH VIETNAM TIME
-- =====================================================
SELECT 
    COUNT(*) as total_predictions_today,
    MAX(display_time_vietnam) as latest_prediction_time,
    MIN(display_time_vietnam) as first_prediction_time,
    COUNT(DISTINCT model_name) as models_used
FROM predictions_vn
WHERE DATE(created_at_vietnam) = DATE(vietnam_now());


-- =====================================================
-- 6. NEXT DRAW COUNTDOWN (for "Kỳ tiếp theo")
-- =====================================================
WITH next_expected AS (
    SELECT 
        MAX(draw_number) + 1 as next_draw_number,
        MAX(draw_time_vietnam) + INTERVAL '6 minutes' as expected_time
    FROM draw_history_vn
)
SELECT 
    next_draw_number,
    TO_CHAR(expected_time, 'HH24:MI') as expected_time_display,
    EXTRACT(EPOCH FROM (expected_time - vietnam_now())) as seconds_until_draw,
    CASE 
        WHEN expected_time > vietnam_now() THEN 'UPCOMING'
        ELSE 'OVERDUE'
    END as status
FROM next_expected;


-- =====================================================
-- HELPER FUNCTIONS AVAILABLE:
-- =====================================================
-- to_vietnam_time(timestamp) - Convert UTC to Vietnam time
-- vietnam_now() - Get current Vietnam time
-- 
-- VIEWS AVAILABLE:
-- predictions_vn - Predictions with Vietnam time
-- draw_history_vn - Draw history with Vietnam time
-- =====================================================
