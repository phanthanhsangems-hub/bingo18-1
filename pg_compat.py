"""Dịch SQL Postgres sang SQLite — CHỈ dùng khi chạy local, không có DATABASE_URL.

Vì sao cần: 33/142 endpoint GET viết SQL riêng của Postgres (``%s``, ``::int``,
``AT TIME ZONE``, ``INTERVAL``, ``json_array_elements_text``...). Trên Cloud Run
chúng chạy tốt, nhưng chạy local thì trả 500 — nghĩa là **23% số endpoint không
thể test trước khi deploy**. Đó là lý do vài lỗi chỉ lộ ra khi đã lên production.

Lớp dịch này KHÔNG bao giờ chạm tới Postgres: nó chỉ được gắn vào connection
SQLite (xem ``database.py``). Sai sót ở đây cùng lắm làm hỏng môi trường dev,
không ảnh hưởng dữ liệu thật.

Phạm vi: chỉ dịch những cấu trúc thực sự có trong app.py. Gặp cấu trúc lạ thì
để nguyên cho SQLite tự báo lỗi — im lặng dịch sai còn tệ hơn báo lỗi.
"""
import re

__all__ = ["to_sqlite"]

# ── json_array_elements_text(COT::json) v  →  json_each(COT) v ────────────
_JSON_ELEMS = re.compile(
    r"jsonb?_array_elements_text\s*\(\s*(.+?)\s*(?:::\s*jsonb?)?\s*\)\s*"
    r"(?:AS\s+)?([a-zA-Z_]\w*)\s*(?:\(\s*([a-zA-Z_]\w*)\s*\))?",
    re.I,
)

# ── X AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh' ─────────────────
_ATZ_PAIR = re.compile(
    r"(?P<expr>\w+\s*\([^()]*\)|[\w.\"]+|\([^()]*\))\s*"
    r"AT\s+TIME\s+ZONE\s*'[^']*'\s*"
    r"AT\s+TIME\s+ZONE\s*'(?P<tz>[^']*)'",
    re.I,
)
_ATZ_ONE = re.compile(
    r"(?P<expr>\w+\s*\([^()]*\)|[\w.\"]+|\([^()]*\))\s*"
    r"AT\s+TIME\s+ZONE\s*'(?P<tz>[^']*)'", re.I
)
_TZ_OFFSET = {"asia/ho_chi_minh": "+7 hours", "utc": "+0 hours"}

# ── NOW() ± INTERVAL 'n unit' ────────────────────────────────────────────
_NOW_INTERVAL = re.compile(
    r"NOW\s*\(\s*\)\s*(?P<op>[-+])\s*INTERVAL\s*'(?P<n>\d+)\s*(?P<unit>\w+)'", re.I
)
_NOW = re.compile(r"NOW\s*\(\s*\)", re.I)

# ── EXTRACT(field FROM expr) ─────────────────────────────────────────────
_TOCHAR_FMT = {"YYYY-MM": "%Y-%m", "YYYY-MM-DD": "%Y-%m-%d",
               "HH24:MI": "%H:%M", "HH24:MI DD/MM": "%H:%M %d/%m",
               "DD/MM": "%d/%m", "YYYY": "%Y", "MM": "%m", "DD": "%d"}
_TOCHAR = re.compile(r"TO_CHAR\s*\((?P<expr>.+),\s*'(?P<fmt>[^']+)'\s*\)", re.I | re.S)

_STRFTIME = {"hour": "%H", "dow": "%w", "day": "%d", "month": "%m",
             "year": "%Y", "minute": "%M", "doy": "%j", "week": "%W"}


def _apply_extract(sql: str) -> str:
    """EXTRACT(field FROM expr) → strftime. Quét ngoặc cân bằng vì expr hay
    lồng ngoặc, vd EXTRACT(HOUR FROM (datetime(x, '+7 hours')))."""
    low = sql.lower()
    i = 0
    while True:
        j = low.find('extract', i)
        if j < 0:
            return sql
        k = j + len('extract')
        while k < len(sql) and sql[k].isspace():
            k += 1
        if k >= len(sql) or sql[k] != '(':
            i = j + 1
            continue
        depth, end = 0, None
        for t in range(k, len(sql)):
            if sql[t] == '(':
                depth += 1
            elif sql[t] == ')':
                depth -= 1
                if depth == 0:
                    end = t
                    break
        if end is None:
            return sql
        inner = sql[k + 1:end]
        m = re.match(r"\s*(\w+)\s+FROM\s+(.+)$", inner, re.I | re.S)
        if m and m.group(1).lower() == 'epoch':
            # EXTRACT(EPOCH FROM (a - b)) → số giây, qua julianday
            parts = _split_top_minus(m.group(2))
            if parts:
                repl = (f"((julianday({parts[0]}) - julianday({parts[1]}))"
                        f" * 86400.0)")
                sql = sql[:j] + repl + sql[end + 1:]
                low = sql.lower()
                i = j + len(repl)
                continue
        if not m or m.group(1).lower() not in _STRFTIME:
            i = end + 1
            low = sql.lower()
            continue
        repl = (f"CAST(strftime('{_STRFTIME[m.group(1).lower()]}', "
                f"{m.group(2).strip()}) AS INTEGER)")
        sql = sql[:j] + repl + sql[end + 1:]
        low = sql.lower()
        i = j + len(repl)

# ── ::type → hàm SQLite tương ứng ───────────────────────────────────────
# CHÚ Ý: ::date KHÔNG được dịch thành CAST(x AS DATE). SQLite không có kiểu
# DATE, CAST('2026-08-17 10:00:00' AS DATE) trả về 2026 — sai âm thầm, mọi
# phép so sánh theo ngày sẽ hỏng mà không báo lỗi. Phải dùng date(x).
_CAST_FN = {"date": "date", "timestamp": "datetime", "time": "time"}
_SQLITE_TYPE = {"int": "INTEGER", "integer": "INTEGER", "bigint": "INTEGER",
                "smallint": "INTEGER", "float": "REAL", "float8": "REAL",
                "double": "REAL", "numeric": "REAL", "decimal": "REAL",
                "text": "TEXT", "varchar": "TEXT", "json": "TEXT", "jsonb": "TEXT"}


def _operand_start(sql: str, end: int) -> int:
    """Lùi từ vị trí ngay trước '::' để tìm đầu toán hạng, khớp ngoặc cân bằng."""
    i = end
    while i > 0 and sql[i - 1].isspace():
        i -= 1
    if i > 0 and sql[i - 1] == ')':
        depth = 0
        while i > 0:
            i -= 1
            if sql[i] == ')':
                depth += 1
            elif sql[i] == '(':
                depth -= 1
                if depth == 0:
                    break
        # nuốt luôn tên hàm đứng trước, vd SUM(...)
        while i > 0 and (sql[i - 1].isalnum() or sql[i - 1] in '_."'):
            i -= 1
        return i
    if i > 0 and sql[i - 1] == "'":
        i -= 1
        while i > 0:
            i -= 1
            if sql[i] == "'":
                break
        return i
    while i > 0 and (sql[i - 1].isalnum() or sql[i - 1] in '_."'):
        i -= 1
    return i


def _apply_casts(sql: str) -> str:
    while True:
        pos = sql.find('::')
        if pos < 0:
            return sql
        m = re.match(r'::\s*(\w+)', sql[pos:])
        if not m:
            return sql.replace('::', ' ', 1)
        typ = m.group(1).lower()
        start = _operand_start(sql, pos)
        operand = sql[start:pos].strip()
        if typ in _CAST_FN:
            repl = f"{_CAST_FN[typ]}({operand})"
        elif typ in ('json', 'jsonb'):
            repl = operand                      # SQLite nhận thẳng chuỗi JSON
        else:
            repl = f"CAST({operand} AS {_SQLITE_TYPE.get(typ, 'TEXT')})"
        sql = sql[:start] + repl + sql[pos + m.end():]


def _split_top_minus(expr: str):
    """Tách 'A - B' ở độ sâu ngoặc 0. Không tách được thì trả None."""
    e = expr.strip()
    while e.startswith('(') and e.endswith(')'):
        d = 0
        for i, ch in enumerate(e):
            d += (ch == '(') - (ch == ')')
            if d == 0 and i < len(e) - 1:
                break
        else:
            e = e[1:-1].strip()
            continue
        break
    depth = 0
    for i, ch in enumerate(e):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '-' and depth == 0 and i > 0:
            return e[:i].strip(), e[i + 1:].strip()
    return None


def _tz_shift(expr: str, tz: str) -> str:
    off = _TZ_OFFSET.get(tz.strip().lower())
    if off is None:                      # múi giờ lạ → để nguyên, SQLite sẽ báo lỗi
        return None
    return f"datetime({expr}, '{off}')"


def to_sqlite(sql: str) -> str:
    """Dịch một câu SQL Postgres sang SQLite. Không nhận diện được thì giữ nguyên."""
    if not isinstance(sql, str):
        return sql

    # 1. json_array_elements_text(COT::json) v → json_each(COT) v
    aliases = []
    colmap = []

    def _je(m):
        col, alias, colname = m.group(1), m.group(2), m.group(3)
        aliases.append(alias)
        if colname:                       # dạng "AS x(num)" → x.num chính là value
            colmap.append((alias, colname))
        return f"json_each({col}) {alias}"

    sql = _JSON_ELEMS.sub(_je, sql)
    # bí danh của json_each trỏ tới cột `value`, không phải chính nó
    for a, cname in colmap:           # x.num → x.value
        sql = re.sub(rf"\b{re.escape(a)}\.{re.escape(cname)}\b", f"{a}.value", sql)
    for a in set(aliases):
        sql = re.sub(rf"\b{re.escape(a)}\s*::\s*(\w+)",
                     lambda m, a=a: f"CAST({a}.value AS "
                                    f"{_SQLITE_TYPE.get(m.group(1).lower(), 'INTEGER')})",
                     sql)

    # 2. AT TIME ZONE (cặp trước, rồi lẻ)
    def _atz(m):
        out = _tz_shift(m.group("expr"), m.group("tz"))
        return out if out else m.group(0)

    sql = _ATZ_PAIR.sub(_atz, sql)
    sql = _ATZ_ONE.sub(_atz, sql)

    # 3. NOW() ± INTERVAL
    sql = _NOW_INTERVAL.sub(
        lambda m: f"datetime('now', '{'-' if m.group('op') == '-' else '+'}"
                  f"{m.group('n')} {m.group('unit')}')", sql)
    sql = _NOW.sub("datetime('now')", sql)
    # CURRENT_TIMESTAMP hợp lệ ở cả hai hệ — KHÔNG dịch. Dịch nó sẽ làm hỏng
    # "DEFAULT CURRENT_TIMESTAMP" trong DDL (SQLite đòi bọc ngoặc).

    # 4. EXTRACT
    sql = _apply_extract(sql)

    # 4b. TO_CHAR(expr, 'YYYY-MM') → strftime('%Y-%m', expr)
    sql = _TOCHAR.sub(
        lambda m: (f"strftime('{_TOCHAR_FMT[m.group('fmt')]}', {m.group('expr').strip()})"
                   if m.group('fmt') in _TOCHAR_FMT else m.group(0)), sql)

    # 5. ::type còn lại
    sql = _apply_casts(sql)

    # 6. placeholder %s → ?   (%% là dấu % thật, giữ lại)
    if "%s" in sql:
        sql = sql.replace("%%", "\x00").replace("%s", "?").replace("\x00", "%")

    return sql
