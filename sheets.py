import os
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import jdatetime
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

IRAN_TZ = ZoneInfo('Asia/Tehran')
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

_client = None
_workbook = None

JALALI_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


# ---------- Jalali helpers ----------

def greg_str_to_jalali(date_str: str) -> str:
    """YYYY-MM-DD → ۱۴۰۵/۰۳/۱۰"""
    try:
        g = datetime.strptime(date_str, '%Y-%m-%d').date()
        jd = jdatetime.date.fromgregorian(date=g)
        return f'{jd.year}/{jd.month:02d}/{jd.day:02d}'
    except Exception:
        return date_str


def greg_str_to_jalali_verbose(date_str: str) -> str:
    """YYYY-MM-DD → ۱۰ خرداد ۱۴۰۵"""
    try:
        g = datetime.strptime(date_str, '%Y-%m-%d').date()
        jd = jdatetime.date.fromgregorian(date=g)
        return f'{jd.day} {JALALI_MONTHS[jd.month - 1]} {jd.year}'
    except Exception:
        return date_str


def parse_jalali_input(text: str) -> str:
    """Parse user Jalali input (1405/03/10 or 1405-03-10) → YYYY-MM-DD for storage."""
    text = text.strip().replace('-', '/')
    parts = text.split('/')
    if len(parts) != 3:
        raise ValueError('فرمت نادرست')
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    jd = jdatetime.date(y, m, d)
    return jd.togregorian().strftime('%Y-%m-%d')


def today_jalali() -> str:
    today = datetime.now(IRAN_TZ).date()
    jd = jdatetime.date.fromgregorian(date=today)
    return f'{jd.year}/{jd.month:02d}/{jd.day:02d}'


# ---------- Google Sheets connection ----------

def _get_client():
    global _client
    if _client is None:
        creds_json = os.getenv('GOOGLE_CREDS_JSON', '').strip()
        if creds_json:
            import json
            info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
            creds = Credentials.from_service_account_file(
                os.path.join(base, 'creds.json'), scopes=SCOPES
            )
        _client = gspread.authorize(creds)
    return _client


def get_wb():
    global _workbook
    if _workbook is None:
        sheet_id = os.getenv('SHEET_ID', '').strip()
        if not sheet_id:
            raise RuntimeError('SHEET_ID در .env تنظیم نشده.')
        _workbook = _get_client().open_by_key(sheet_id)
    return _workbook


# ---------- Tasks ----------

def add_task(title: str, deadline: str = None, assigned_to: str = None, priority: str = 'medium') -> int:
    ws = get_wb().worksheet('tasks')
    rows = ws.get_all_values()
    new_id = len(rows)
    now = datetime.now(IRAN_TZ).strftime('%Y-%m-%d %H:%M')
    ws.append_row([new_id, title, deadline or '', assigned_to or '', 'pending', priority, now])
    return new_id


def get_tasks(status: str = None) -> list:
    ws = get_wb().worksheet('tasks')
    rows = ws.get_all_records()
    if status:
        return [r for r in rows if r.get('status') == status]
    return rows


def complete_task(task_id: int) -> bool:
    ws = get_wb().worksheet('tasks')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]) == str(task_id):
            ws.update_cell(i, 5, 'done')
            return True
    return False


def delete_task(task_id: int) -> bool:
    ws = get_wb().worksheet('tasks')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]) == str(task_id):
            ws.delete_rows(i)
            return True
    return False


def update_task(task_id: int, title: str, deadline: str, assigned_to: str) -> bool:
    ws = get_wb().worksheet('tasks')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]) == str(task_id):
            ws.update(f'B{i}:D{i}', [[title, deadline or '', assigned_to or '']])
            return True
    return False


# ---------- Events ----------

def delete_event(event_id: int) -> bool:
    ws = get_wb().worksheet('events')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]) == str(event_id):
            ws.delete_rows(i)
            return True
    return False


def update_event(event_id: int, title: str, event_date: str, event_time: str) -> bool:
    ws = get_wb().worksheet('events')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]) == str(event_id):
            ws.update(f'B{i}:D{i}', [[title, event_date, event_time or '']])
            return True
    return False


def get_month_habits_log(jyear: int, jmonth: int, num_days: int) -> set:
    """Returns set of (date_str, habit_name) for completed habits in the given Jalali month."""
    ws = get_wb().worksheet('habits')
    rows = ws.get_all_records()
    month_dates = set()
    for d in range(1, num_days + 1):
        g = jdatetime.date(jyear, jmonth, d).togregorian()
        month_dates.add(g.strftime('%Y-%m-%d'))
    return {(r['date'], r['habit_name'])
            for r in rows
            if r['date'] in month_dates and str(r.get('completed', '')).upper() == 'TRUE'}


def add_event(title: str, event_date: str, event_time: str = None, category: str = 'personal') -> int:
    ws = get_wb().worksheet('events')
    rows = ws.get_all_values()
    new_id = len(rows)
    now = datetime.now(IRAN_TZ).strftime('%Y-%m-%d %H:%M')
    ws.append_row([new_id, title, event_date, event_time or '', category, now])
    return new_id


def get_events_range(from_date: date, to_date: date) -> list:
    ws = get_wb().worksheet('events')
    rows = ws.get_all_records()
    result = []
    for r in rows:
        try:
            d = datetime.strptime(r['date'], '%Y-%m-%d').date()
            if from_date <= d <= to_date:
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda x: (x['date'], x.get('time', '')))


# ---------- Habits ----------

def get_habits_list() -> list:
    ws = get_wb().worksheet('habit_list')
    rows = ws.get_all_records()
    return [r['name'] for r in rows if str(r.get('active', 'TRUE')).upper() == 'TRUE']


def add_habit_to_list(habit_name: str):
    ws = get_wb().worksheet('habit_list')
    ws.append_row([habit_name, 'TRUE'])


def remove_habit(habit_name: str) -> bool:
    ws = get_wb().worksheet('habit_list')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row[0] == habit_name:
            ws.update_cell(i, 2, 'FALSE')
            return True
    return False


def update_habit_name(old_name: str, new_name: str) -> bool:
    ws_list = get_wb().worksheet('habit_list')
    rows = ws_list.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row[0] == old_name:
            ws_list.update_cell(i, 1, new_name)
            ws_habits = get_wb().worksheet('habits')
            all_rows = ws_habits.get_all_values()
            for j, r in enumerate(all_rows[1:], start=2):
                if r[1] == old_name:
                    ws_habits.update_cell(j, 2, new_name)
            return True
    return False


def get_logged_habits_today(today: date) -> set:
    ws = get_wb().worksheet('habits')
    date_str = today.strftime('%Y-%m-%d')
    rows = ws.get_all_records()
    return {r['habit_name'] for r in rows if r['date'] == date_str and str(r.get('completed', '')).upper() == 'TRUE'}


def toggle_habit(habit_name: str, habit_date: date) -> bool:
    ws = get_wb().worksheet('habits')
    date_str = habit_date.strftime('%Y-%m-%d')
    rows = ws.get_all_values()

    for i, row in enumerate(rows[1:], start=2):
        if row[0] == date_str and row[1] == habit_name:
            new_val = 'FALSE' if str(row[2]).upper() == 'TRUE' else 'TRUE'
            ws.update_cell(i, 3, new_val)
            return new_val == 'TRUE'

    ws.append_row([date_str, habit_name, 'TRUE'])
    return True


def get_habit_week_stats() -> dict:
    ws = get_wb().worksheet('habits')
    rows = ws.get_all_records()
    today = datetime.now(IRAN_TZ).date()
    week_start = today - timedelta(days=today.weekday())

    stats = {}
    for r in rows:
        try:
            d = datetime.strptime(r['date'], '%Y-%m-%d').date()
            if week_start <= d <= today and str(r.get('completed', '')).upper() == 'TRUE':
                stats[r['habit_name']] = stats.get(r['habit_name'], 0) + 1
        except Exception:
            pass
    return stats


# ---------- Summaries ----------

def get_today_summary() -> str:
    today = datetime.now(IRAN_TZ).date()
    today_str = today.strftime('%Y-%m-%d')

    pending = get_tasks('pending')
    today_tasks = [t for t in pending if t.get('deadline') == today_str]
    overdue = [t for t in pending if t.get('deadline', '') and t['deadline'] < today_str]

    events = get_events_range(today, today)
    habits = get_habits_list()
    logged = get_logged_habits_today(today)

    jtoday = today_jalali()
    lines = [f'<b>📋 امروز — {jtoday}</b>\n']

    if overdue:
        lines.append('🔴 <b>تسک‌های عقب‌افتاده:</b>')
        for t in overdue:
            lines.append(f'  • {t["title"]}  (ددلاین: {greg_str_to_jalali_verbose(t["deadline"])})')
        lines.append('')

    if today_tasks:
        lines.append('📌 <b>تسک‌های امروز:</b>')
        for t in today_tasks:
            who = f'  👤 {t["assigned_to"]}' if t.get('assigned_to') else ''
            lines.append(f'  • {t["title"]}{who}')
        lines.append('')

    if events:
        lines.append('🗓 <b>رویدادهای امروز:</b>')
        for e in events:
            t_str = f' ساعت {e["time"]}' if e.get('time') else ''
            lines.append(f'  • {e["title"]}{t_str}')
        lines.append('')

    if habits:
        lines.append('✅ <b>عادت‌ها:</b>')
        done = sum(1 for h in habits if h in logged)
        lines.append(f'  {done}/{len(habits)} انجام شده')
        for h in habits:
            icon = '✅' if h in logged else '⭕'
            lines.append(f'  {icon} {h}')

    if len(lines) == 1:
        lines.append('هیچ موردی برای امروز ثبت نشده.')

    return '\n'.join(lines)


def get_weekly_summary() -> str:
    today = datetime.now(IRAN_TZ).date()
    today_str = today.strftime('%Y-%m-%d')
    week_end = today + timedelta(days=7)
    week_start = today - timedelta(days=today.weekday())
    days_elapsed = (today - week_start).days + 1

    pending = get_tasks('pending')
    overdue, upcoming = [], []
    for t in pending:
        dl = t.get('deadline', '')
        if not dl:
            continue
        if dl < today_str:
            overdue.append(t)
        elif dl <= week_end.strftime('%Y-%m-%d'):
            upcoming.append(t)

    events = get_events_range(today, week_end)
    habit_stats = get_habit_week_stats()
    habits = get_habits_list()

    lines = [f'<b>📊 خلاصه هفته جاری</b>\n']

    if overdue:
        lines.append('🔴 <b>تسک‌های معوق:</b>')
        for t in overdue[:5]:
            who = f' — {t["assigned_to"]}' if t.get('assigned_to') else ''
            jdl = greg_str_to_jalali_verbose(t['deadline'])
            lines.append(f'  • {t["title"]}{who}  📅 {jdl}')
        lines.append('')

    if upcoming:
        lines.append('🟡 <b>ددلاین‌های این هفته:</b>')
        for t in sorted(upcoming, key=lambda x: x['deadline'])[:5]:
            who = f' — {t["assigned_to"]}' if t.get('assigned_to') else ''
            jdl = greg_str_to_jalali_verbose(t['deadline'])
            lines.append(f'  • {t["title"]}{who}  📅 {jdl}')
        lines.append('')

    if events:
        lines.append('📅 <b>رویدادهای پیش رو:</b>')
        for e in events[:5]:
            t_str = f' ساعت {e["time"]}' if e.get('time') else ''
            jdate = greg_str_to_jalali_verbose(e['date'])
            lines.append(f'  • {e["title"]} — {jdate}{t_str}')
        lines.append('')

    if habits:
        lines.append(f'✅ <b>عادت‌ها ({days_elapsed} روز از این هفته):</b>')
        for h in habits:
            count = habit_stats.get(h, 0)
            filled = '🟢' * count + '⚪' * (days_elapsed - count)
            lines.append(f'  {h}: {filled}  {count}/{days_elapsed}')

    if len(lines) == 1:
        lines.append('هیچ موردی برای این هفته ثبت نشده.')

    return '\n'.join(lines)
