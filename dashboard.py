"""
Builds the Google Sheets visual dashboard.
  - habit_tracker: colored monthly grid (like bullet-journal tracker)
  - calendar: Jalali monthly calendar with events + tasks
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import jdatetime

from sheets import (
    get_wb, get_habits_list, get_tasks, get_events_range, get_month_habits_log,
    IRAN_TZ, JALALI_MONTHS,
)

logger = logging.getLogger(__name__)

JALALI_WD = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج']   # Sat=0 … Fri=6

HABIT_COLORS = [
    (0.298, 0.686, 0.314),  # Green
    (0.129, 0.588, 0.953),  # Blue
    (1.000, 0.596, 0.000),  # Orange
    (0.612, 0.153, 0.690),  # Purple
    (0.957, 0.263, 0.212),  # Red
    (0.000, 0.588, 0.533),  # Teal
    (0.914, 0.118, 0.388),  # Pink
    (0.247, 0.318, 0.710),  # Indigo
    (0.475, 0.333, 0.282),  # Brown
    (0.376, 0.490, 0.545),  # Blue-grey
]

WHITE      = {'red': 1.00, 'green': 1.00, 'blue': 1.00}
LIGHT_GRAY = {'red': 0.93, 'green': 0.93, 'blue': 0.93}
HEADER_BG  = {'red': 0.20, 'green': 0.20, 'blue': 0.20}
CAL_HEAD   = {'red': 0.27, 'green': 0.51, 'blue': 0.71}
TODAY_BG   = {'red': 1.00, 'green': 0.93, 'blue': 0.24}
FRI_BG     = {'red': 1.00, 'green': 0.94, 'blue': 0.94}
PAST_BG    = {'red': 0.97, 'green': 0.97, 'blue': 0.97}


def _rgb(r, g, b):
    return {'red': r, 'green': g, 'blue': b}


def _py_to_jwd(wd: int) -> int:
    """Python weekday (Mon=0) → Jalali weekday (Sat=0)."""
    return {5: 0, 6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6}[wd]


def _month_days(jyear: int, jmonth: int) -> int:
    if jmonth <= 6:  return 31
    if jmonth <= 11: return 30
    g1 = jdatetime.date(jyear, 1, 1).togregorian()
    g2 = jdatetime.date(jyear + 1, 1, 1).togregorian()
    return 30 if (g2 - g1).days == 366 else 29


def _get_or_create(wb, title, rows=100, cols=40):
    try:
        return wb.worksheet(title)
    except Exception:
        return wb.add_worksheet(title, rows=rows, cols=cols)


def _rng(ws_id, r0, r1, c0, c1):
    return {'sheetId': ws_id, 'startRowIndex': r0, 'endRowIndex': r1,
            'startColumnIndex': c0, 'endColumnIndex': c1}


def _fmt(ws_id, r0, c0, r1=None, c1=None, **kw):
    """Single repeatCell request helper."""
    r1 = r1 or r0 + 1
    c1 = c1 or c0 + 1
    return {
        'repeatCell': {
            'range': _rng(ws_id, r0, r1, c0, c1),
            'cell': {'userEnteredFormat': kw},
            'fields': 'userEnteredFormat(' + ','.join(kw.keys()) + ')',
        }
    }


# ──────────────────────────── HABIT TRACKER ────────────────────────────

def update_habit_tracker():
    wb      = get_wb()
    ws      = _get_or_create(wb, 'habit_tracker', 60, 35)
    ws_id   = ws.id
    today   = datetime.now(IRAN_TZ).date()
    today_j = jdatetime.date.fromgregorian(date=today)
    jy, jm  = today_j.year, today_j.month
    nd      = _month_days(jy, jm)
    mname   = JALALI_MONTHS[jm - 1]
    habits  = get_habits_list()
    log     = get_month_habits_log(jy, jm, nd)

    # ── Build value matrix ──
    # Row 0: title (merged)
    # Row 1: "عادت" + day numbers
    # Row 2+: habit name + ✓ / blank per day

    day_header = ['عادت']
    for d in range(1, nd + 1):
        g  = jdatetime.date(jy, jm, d).togregorian()
        wd = JALALI_WD[_py_to_jwd(g.weekday())]
        day_header.append(f'{d}\n{wd}')

    rows_data = [
        [f'ردیاب عادت‌ها  —  {mname} {jy}'] + [''] * nd,
        day_header,
    ]
    for h in habits:
        row = [h]
        for d in range(1, nd + 1):
            g_str = jdatetime.date(jy, jm, d).togregorian().strftime('%Y-%m-%d')
            row.append('✓' if (g_str, h) in log else '')
        rows_data.append(row)

    ws.clear()
    ws.update('A1', rows_data, value_input_option='RAW')

    reqs = []

    # Merge + style header row
    reqs.append({'mergeCells': {'range': _rng(ws_id, 0, 1, 0, nd + 1), 'mergeType': 'MERGE_ALL'}})
    reqs.append(_fmt(ws_id, 0, 0, 1, nd + 1,
        backgroundColor=HEADER_BG,
        textFormat={'foregroundColor': WHITE, 'bold': True, 'fontSize': 13},
        horizontalAlignment='CENTER', verticalAlignment='MIDDLE'))

    # Day-number header row
    reqs.append(_fmt(ws_id, 1, 0, 2, nd + 1,
        backgroundColor={'red': 0.85, 'green': 0.85, 'blue': 0.85},
        textFormat={'bold': True, 'fontSize': 9},
        horizontalAlignment='CENTER', verticalAlignment='MIDDLE',
        wrapStrategy='WRAP'))

    # Habit rows
    for h_idx, habit in enumerate(habits):
        r, g, b = HABIT_COLORS[h_idx % len(HABIT_COLORS)]
        hab_col = _rgb(r, g, b)
        row_i   = h_idx + 2

        # Habit name cell
        reqs.append(_fmt(ws_id, row_i, 0, row_i + 1, 1,
            backgroundColor=hab_col,
            textFormat={'foregroundColor': WHITE, 'bold': True, 'fontSize': 10},
            horizontalAlignment='CENTER', verticalAlignment='MIDDLE'))

        # Day cells
        for d in range(1, nd + 1):
            g_date = jdatetime.date(jy, jm, d).togregorian()
            g_str  = g_date.strftime('%Y-%m-%d')
            done   = (g_str, habit) in log
            future = g_date > today

            bg = LIGHT_GRAY if future else (hab_col if done else WHITE)
            reqs.append(_fmt(ws_id, row_i, d, row_i + 1, d + 1,
                backgroundColor=bg,
                textFormat={'foregroundColor': WHITE if done else {'red':0.4,'green':0.4,'blue':0.4},
                            'bold': done, 'fontSize': 10},
                horizontalAlignment='CENTER', verticalAlignment='MIDDLE'))

    # Column widths
    reqs += [
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 1},
            'properties': {'pixelSize': 110}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'COLUMNS', 'startIndex': 1, 'endIndex': nd + 1},
            'properties': {'pixelSize': 32}, 'fields': 'pixelSize'}},
    ]
    # Row heights
    reqs += [
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
            'properties': {'pixelSize': 36}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 2},
            'properties': {'pixelSize': 42}, 'fields': 'pixelSize'}},
    ]
    if habits:
        reqs.append({'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 2, 'endIndex': 2 + len(habits)},
            'properties': {'pixelSize': 34}, 'fields': 'pixelSize'}})

    # RTL + freeze header columns
    reqs.append({'updateSheetProperties': {
        'properties': {'sheetId': ws_id, 'rightToLeft': True},
        'fields': 'rightToLeft'}})
    reqs.append({'updateFrozenProperties': {
        'range': {'sheetId': ws_id},
        'frozenRowCount': 2, 'frozenColumnCount': 1,
        'fields': 'frozenRowCount,frozenColumnCount'}})

    if reqs:
        wb.batch_update({'requests': reqs})
    logger.info('habit_tracker updated.')


# ──────────────────────────── JALALI CALENDAR ────────────────────────────

def update_calendar():
    wb      = get_wb()
    ws      = _get_or_create(wb, 'calendar', 100, 8)
    ws_id   = ws.id
    today   = datetime.now(IRAN_TZ).date()
    today_j = jdatetime.date.fromgregorian(date=today)
    jy, jm  = today_j.year, today_j.month
    nd      = _month_days(jy, jm)
    mname   = JALALI_MONTHS[jm - 1]

    first_g    = jdatetime.date(jy, jm, 1).togregorian()
    first_jwd  = _py_to_jwd(first_g.weekday())   # 0=Sat

    last_g  = jdatetime.date(jy, jm, nd).togregorian()
    events  = get_events_range(first_g, last_g)
    tasks   = [t for t in get_tasks('pending') if t.get('deadline')]

    # Build day → content list
    day_items: dict[int, list] = {}
    for e in events:
        try:
            jd = jdatetime.date.fromgregorian(
                date=datetime.strptime(e['date'], '%Y-%m-%d').date())
            if jd.month == jm and jd.year == jy:
                t = f' {e["time"]}' if e.get('time') else ''
                day_items.setdefault(jd.day, []).append(f'📅 {e["title"]}{t}')
        except Exception:
            pass
    for t in tasks:
        try:
            jd = jdatetime.date.fromgregorian(
                date=datetime.strptime(t['deadline'], '%Y-%m-%d').date())
            if jd.month == jm and jd.year == jy:
                who = f' ({t["assigned_to"]})' if t.get('assigned_to') else ''
                day_items.setdefault(jd.day, []).append(f'📌 {t["title"]}{who}')
        except Exception:
            pass

    # Build grid rows (each week = one row of 7 cols)
    grid: list[list[str]] = []
    week = [''] * 7
    for d in range(1, nd + 1):
        g_date = jdatetime.date(jy, jm, d).togregorian()
        jwd    = _py_to_jwd(g_date.weekday())
        items  = day_items.get(d, [])
        cell   = str(d) + ('\n' + '\n'.join(items[:3]) if items else '')
        week[jwd] = cell
        if jwd == 6 or d == nd:
            grid.append(week)
            week = [''] * 7

    all_vals = [
        [f'تقویم شمسی  —  {mname} {jy}'] + [''] * 6,
        JALALI_WD,
        *grid,
    ]

    ws.clear()
    ws.update('A1', all_vals, value_input_option='RAW')

    reqs = []

    # Header merge + style
    reqs.append({'mergeCells': {'range': _rng(ws_id, 0, 1, 0, 7), 'mergeType': 'MERGE_ALL'}})
    reqs.append(_fmt(ws_id, 0, 0, 1, 7,
        backgroundColor=CAL_HEAD,
        textFormat={'foregroundColor': WHITE, 'bold': True, 'fontSize': 14},
        horizontalAlignment='CENTER', verticalAlignment='MIDDLE'))

    # Weekday header row: Fri column in red, rest dark
    for col in range(7):
        bg = {'red': 0.72, 'green': 0.11, 'blue': 0.11} if col == 6 else {'red': 0.22, 'green': 0.22, 'blue': 0.22}
        reqs.append(_fmt(ws_id, 1, col, 2, col + 1,
            backgroundColor=bg,
            textFormat={'foregroundColor': WHITE, 'bold': True, 'fontSize': 12},
            horizontalAlignment='CENTER', verticalAlignment='MIDDLE'))

    # Day cells
    for d in range(1, nd + 1):
        g_date = jdatetime.date(jy, jm, d).togregorian()
        jwd    = _py_to_jwd(g_date.weekday())
        pos    = first_jwd + d - 1
        row_i  = 2 + pos // 7
        col_i  = jwd

        is_today  = (g_date == today)
        is_fri    = (jwd == 6)
        is_past   = (g_date < today)

        if is_today:  bg = TODAY_BG
        elif is_fri:  bg = FRI_BG
        elif is_past: bg = PAST_BG
        else:         bg = WHITE

        reqs.append(_fmt(ws_id, row_i, col_i, row_i + 1, col_i + 1,
            backgroundColor=bg,
            horizontalAlignment='CENTER', verticalAlignment='TOP',
            wrapStrategy='WRAP',
            textFormat={'fontSize': 10}))

    # Column widths + row heights
    reqs += [
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 7},
            'properties': {'pixelSize': 130}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
            'properties': {'pixelSize': 38}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 2},
            'properties': {'pixelSize': 30}, 'fields': 'pixelSize'}},
    ]
    if grid:
        reqs.append({'updateDimensionProperties': {
            'range': {'sheetId': ws_id, 'dimension': 'ROWS', 'startIndex': 2, 'endIndex': 2 + len(grid)},
            'properties': {'pixelSize': 90}, 'fields': 'pixelSize'}})

    reqs.append({'updateSheetProperties': {
        'properties': {'sheetId': ws_id, 'rightToLeft': True},
        'fields': 'rightToLeft'}})
    reqs.append({'updateFrozenProperties': {
        'range': {'sheetId': ws_id},
        'frozenRowCount': 2, 'frozenColumnCount': 0,
        'fields': 'frozenRowCount,frozenColumnCount'}})

    if reqs:
        wb.batch_update({'requests': reqs})
    logger.info('calendar updated.')


def refresh_all():
    try:
        update_habit_tracker()
    except Exception as e:
        logger.error(f'habit_tracker error: {e}')
    try:
        update_calendar()
    except Exception as e:
        logger.error(f'calendar error: {e}')
