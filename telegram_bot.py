"""
Telegram Bot - Gửi thông báo dự đoán và kết quả
"""
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import List

import config

logger = logging.getLogger(__name__)

SEP = "────────────────────"


class TelegramBot:
    def __init__(self):
        self.token   = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base    = f"https://api.telegram.org/bot{self.token}"

    def _send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram chua cau hinh token/chat_id")
            return False
        try:
            r = requests.post(
                f"{self.base}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
            if r.ok and r.json().get('ok'):
                return True
            if r.status_code == 400 or (r.ok and not r.json().get('ok')):
                import re
                plain = re.sub(r'<[^>]+>', '', text)
                r2 = requests.post(
                    f"{self.base}/sendMessage",
                    json={"chat_id": self.chat_id, "text": plain},
                    timeout=10
                )
                if r2.ok and r2.json().get('ok'):
                    return True
            logger.error("Telegram error %d: %s", r.status_code, r.text[:300])
            return False
        except Exception as e:
            logger.error("Telegram send error: %s", e)
            return False

    # ── Constants ─────────────────────────────────────────────────
    _SIZE_ICON  = {'NHO': '🔵', 'HOA': '🟡', 'LON': '🔴'}
    _SIZE_VI    = {'NHO': 'NHỎ', 'HOA': 'HÒA', 'LON': 'LỚN'}
    _VOTER_SHORT = {
        'markov':           'Markov',
        'markov2_size':     'Markov2',
        'sum_transition':   'SumTrans',
        'ml':               'RF',
        'prior_nho':        'AnchorNHO',
        'prior_lon':        'AnchorLON',
        'carryover':        'Carry',
        'lstm':             'LSTM',
        'lstm_full':        'LSTM56',
        'cold_voter':       'Cold',
        'fwbr':             'FWBR',
    }

    @staticmethod
    def _size_cat(numbers: List[int]) -> str:
        s = sum(numbers)
        return "NHO" if s <= 9 else ("HOA" if s <= 11 else "LON")

    def _sum_cat(self, numbers: List[int]) -> str:
        s = sum(numbers)
        return f"{s}·{self._SIZE_VI.get(self._size_cat(numbers), '')}"

    @staticmethod
    def _conf_tier(conf: float) -> str:
        if conf >= 0.44:   return "✅"
        if conf >= 0.355:  return "→"
        return "⚠️"

    # ── send_prediction ───────────────────────────────────────────
    def send_prediction(self, draw_number: int, model_name: str,
                        numbers: List[int], confidence: float,
                        signal: str = "", vote_tally: dict = None,
                        vote_info: dict = None, reason_info: dict = None,
                        last_result: dict = None, is_confident: bool = True) -> bool:

        nums_str  = "  ·  ".join(str(n) for n in numbers)
        vn_now    = datetime.now(timezone(timedelta(hours=7)))
        draw_time = vn_now.strftime("%H:%M  %d/%m")
        size      = self._size_cat(numbers)
        size_vi   = self._SIZE_VI[size]
        size_icon = self._SIZE_ICON[size]
        s         = sum(numbers)

        lines = []

        # ── Kết quả kỳ trước ──────────────────────────────────────
        if last_result:
            lr       = last_result
            act      = lr.get('actual_numbers', [])
            is_win   = lr.get('is_win', False)
            wl       = lr.get('recent_wl', [])
            act_str  = "·".join(str(n) for n in act)
            verdict  = "THẮNG" if is_win else "THUA"
            icon     = "✅" if is_win else "❌"
            trail    = "  ".join("✅" if w else "❌" for w in (wl[-6:] + [is_win]))
            lines += [
                f"{icon}  <b>KỲ #{lr.get('draw_number')}</b>  {act_str} ({self._sum_cat(act)})  —  <b>{verdict}</b>",
                f"{trail}  ← kỳ này",
                SEP,
            ]

        # ── Dự đoán chính ─────────────────────────────────────────
        lines += [
            f"🎯  <b>KỲ #{draw_number}</b>  ·  {draw_time}",
            f"",
            f"     <b>{nums_str}</b>",
            f"     Tổng <b>{s}</b>  {size_icon}  <b>{size_vi}</b>   ·   Tin cậy <b>{confidence:.1%}</b>  {self._conf_tier(confidence)}",
            f"",
        ]

        # ── Compact voter summary ──────────────────────────────────
        vi      = vote_info or {}
        detail  = vi.get('all_votes_detail', {})
        majority = vi.get('final_size') or vi.get('majority_size') or size
        sw      = vi.get('size_weights', {})
        sw_total = sum(sw.values()) or 1.0

        if detail:
            w_pct = sw.get(majority, 0) / sw_total * 100
            majority_vi = self._SIZE_VI.get(majority, majority)
            voters_sorted = sorted(
                detail.items(),
                key=lambda x: (-int(x[1].get('winner', False)), -x[1].get('eff_w_pct', 0))
            )
            voter_parts = []
            for vname, vd in voters_sorted[:7]:
                short = self._VOTER_SHORT.get(vname, vname[:7])
                mark  = '✅' if vd.get('winner', False) else '❌'
                voter_parts.append(f"{short}{mark}")
            lines.append(f"<b>{majority_vi} {w_pct:.0f}%</b>  |  {'  '.join(voter_parts)}")

        # ── Cold rank + vắng mặt ──────────────────────────────────
        ri          = reason_info or {}
        absence     = ri.get('absence', {})
        combo_rank  = ri.get('combo_rank')
        combo_total = ri.get('combo_total')

        cold_parts = []
        if combo_rank and combo_total:
            cold_parts.append(f"🧊 Lạnh #{combo_rank}/{combo_total}")
        if absence:
            nums_sorted = sorted(numbers)
            abs_parts = [f"{n}→{absence.get(n, 0)}k" for n in nums_sorted if n in absence]
            if abs_parts:
                cold_parts.append("Vắng: " + " · ".join(abs_parts))
        if cold_parts:
            lines.append("  ·  ".join(cold_parts))

        # ── Extras ────────────────────────────────────────────────
        hot_note = ri.get('hot_adjust')
        if hot_note:
            lines.append(f"🔥 HotAdjust: {hot_note}")

        if signal:
            lines.append(f"📡 {signal}")

        loss_streak = ri.get('loss_streak', 0)
        if loss_streak >= 7:
            lines.append(f"⚠️ Thua {loss_streak} kỳ liên tiếp")

        if not is_confident:
            lines.append(f"⚠️ Tín hiệu yếu — tỷ lệ thắng lịch sử ở mức đồng thuận này thấp")

        lines.append(SEP)
        return self._send("\n".join(lines))

    # ── send_result ───────────────────────────────────────────────
    def send_result(self, draw_number: int, actual_numbers: List[int],
                    predicted: List[int], model_name: str,
                    match_count: int, is_win: bool,
                    is_win_sum: bool = False,
                    recent_wl: List[bool] = None) -> bool:

        actual_str    = "·".join(str(n) for n in actual_numbers)
        predicted_str = "·".join(str(n) for n in predicted)
        is_win_size   = self._size_cat(predicted) == self._size_cat(actual_numbers)
        verdict       = "THẮNG" if is_win_size else "THUA"
        icon          = "✅" if is_win_size else "❌"
        size_icon     = "✅" if is_win_size else "❌"
        sum_icon      = "✅" if is_win_sum  else "❌"

        wl_line = ""
        if recent_wl:
            trail   = recent_wl[-7:] + [is_win_size]
            wl_line = "\n" + "  ".join("✅" if w else "❌" for w in trail) + "  ← kỳ này"

        text = (
            f"{icon}  <b>KỲ #{draw_number}</b>  —  <b>{verdict}</b>\n"
            f"{SEP}\n"
            f"Kết quả:  <b>{actual_str}</b>  ({self._sum_cat(actual_numbers)})\n"
            f"Dự đoán:  <b>{predicted_str}</b>  ({self._sum_cat(predicted)})\n"
            f"Khớp <b>{match_count}/3</b>   ·   Size {size_icon}   ·   Tổng {sum_icon}"
            f"{wl_line}\n"
            f"{SEP}"
        )
        return self._send(text)

    # ── send_combo_stats ──────────────────────────────────────────
    def send_combo_stats(self, draws_df, top_n: int = 6) -> bool:
        from collections import Counter
        import ast

        recent = draws_df.head(len(draws_df))
        combo_counts: Counter = Counter()
        sum_counts:   Counter = Counter()
        size_counts:  Counter = Counter()

        for nums in recent['numbers']:
            try:
                if isinstance(nums, str):
                    nums = ast.literal_eval(nums)
                combo_counts[tuple(sorted(int(x) for x in nums))] += 1
                s = sum(int(x) for x in nums)
                sum_counts[s] += 1
                size_counts['NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')] += 1
            except Exception:
                continue

        total  = sum(combo_counts.values()) or 1
        vn_now = datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M %d/%m')
        window = len(draws_df)

        hot_lines = "\n".join(
            f"  {'·'.join(str(x) for x in c):<9}  {cnt}x  ({cnt/total*100:.1f}%)"
            for c, cnt in combo_counts.most_common(top_n)
        )
        sum_hot   = "  ".join(f"Σ{s}={cnt}x" for s, cnt in sum_counts.most_common(5))
        nho_pct   = size_counts.get('NHO', 0) / total * 100
        hoa_pct   = size_counts.get('HOA', 0) / total * 100
        lon_pct   = size_counts.get('LON', 0) / total * 100

        text = (
            f"📊 <b>THỐNG KÊ {window} KỲ GẦN NHẤT</b>  ·  {vn_now}\n"
            f"{SEP}\n"
            f"🔥 <b>Top {top_n} nóng:</b>\n{hot_lines}\n"
            f"{SEP}\n"
            f"📈 Tổng nóng:  {sum_hot}\n"
            f"⚖️ SIZE:  NHỎ {nho_pct:.1f}%  ·  HÒA {hoa_pct:.1f}%  ·  LỚN {lon_pct:.1f}%\n"
            f"<i>Tham khảo — không phải tín hiệu dự đoán</i>"
        )
        return self._send(text)

    # ── Helpers ───────────────────────────────────────────────────
    def send_message(self, text: str) -> bool:
        return self._send(text)

    def send_document(self, file_bytes: bytes, filename: str, caption: str = "") -> bool:
        if not self.token or not self.chat_id:
            return False
        try:
            r = requests.post(
                f"{self.base}/sendDocument",
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": (filename, file_bytes,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                timeout=30,
            )
            if not r.ok:
                logger.error("Telegram sendDocument error %d: %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as e:
            logger.error("Telegram send_document error: %s", e)
            return False
