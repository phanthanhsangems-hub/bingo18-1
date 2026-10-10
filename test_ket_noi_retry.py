"""Het slot Supabase (EMAXCONNSESSION) -> thu lai; loi khac -> nem ngay."""
import os, sys
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as D
import psycopg2
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
het = psycopg2.OperationalError('FATAL:  (EMAXCONNSESSION) max clients reached in session mode')
with mock.patch('time.sleep'):
    with mock.patch.object(psycopg2, 'connect', side_effect=[het, het, 'CONN']) as m:
        kiem("het slot 2 lan roi duoc -> tra ket noi", D.DatabaseManager._connect_pg_retry() == 'CONN' and m.call_count == 3)
    with mock.patch.object(psycopg2, 'connect', side_effect=het) as m:
        try: D.DatabaseManager._connect_pg_retry(); ok = False
        except psycopg2.OperationalError: ok = m.call_count == 4
        kiem("het slot mai mai -> thu 4 lan roi nem loi", ok, m.call_count)
    with mock.patch.object(psycopg2, 'connect', side_effect=psycopg2.OperationalError('password authentication failed')) as m:
        try: D.DatabaseManager._connect_pg_retry(); ok = False
        except psycopg2.OperationalError: ok = m.call_count == 1
        kiem("loi khac (sai mat khau) -> KHONG thu lai", ok, m.call_count)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
