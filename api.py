"""
Production server: FastAPI handles Telegram webhook + Mini App API.
Run with: uvicorn api:app --host 0.0.0.0 --port $PORT
"""
import os, hmac, hashlib, asyncio
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters,
)
from telegram.request import HTTPXRequest

import sheets, dashboard

load_dotenv()

TOKEN       = os.getenv('BOT_TOKEN', '').strip()
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '').strip().rstrip('/')

ptb_app: Application = None


# ── Bot setup (same handlers as bot.py) ────────────────────────────────

def _build_ptb():
    """Build the python-telegram-bot Application with all handlers."""
    import bot as b
    proxy = os.getenv('PROXY_URL', '').strip()
    builder = Application.builder().token(TOKEN)
    if proxy:
        builder = builder.request(HTTPXRequest(proxy=proxy))
    app = builder.build()

    bk      = CallbackQueryHandler(b.menu_cb,      pattern='^back_menu$')
    bdp     = CallbackQueryHandler(b.back_dp_cb,   pattern=r'^bdp_')
    DATE_P  = r'^date_(\d{4}-\d{2}-\d{2}|manual)$'

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', b.start)],
        states={
            b.MENU:         [CallbackQueryHandler(b.menu_cb, pattern='^(add_task|add_event|log_habits|view_week|view_today|refresh_dash|list_habits|list_events|list_tasks|back_menu)$'),
                             CallbackQueryHandler(b.habit_toggle_cb, pattern=r'^ht_\d+$')],
            b.TASK_TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, b.task_title), bk],
            b.DATE_PICK:    [CallbackQueryHandler(b.date_pick_cb, pattern=DATE_P), bk],
            b.DATE_MANUAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, b.date_manual_input), bdp, bk],
            b.TASK_ASSIGNED:[MessageHandler(filters.TEXT & ~filters.COMMAND, b.task_assigned), bk],
            b.EVENT_TITLE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, b.event_title), bk],
            b.EVENT_TIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, b.event_time_h), bk],
            b.NEW_HABIT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, b.new_habit),
                             CallbackQueryHandler(b.habit_manage_cb, pattern='^list_habits$'), bk],
            b.HABIT_EDIT_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, b.habit_edit_name), bk],
            b.LIST_HABITS:  [CallbackQueryHandler(b.habit_manage_cb, pattern=r'^(edit_h_|del_h_|new_habit_prompt|list_habits|noop)'), bk],
            b.LIST_EVENTS:  [CallbackQueryHandler(b.event_list_cb, pattern=r'^(edit_e_|del_e_|noop)'), bk],
            b.LIST_TASKS:   [CallbackQueryHandler(b.task_list_cb, pattern=r'^(edit_t_|done_t_|del_t_|noop)'), bk],
        },
        fallbacks=[CommandHandler('cancel', b.cancel), CommandHandler('start', b.start), CommandHandler('done', b.done_cmd)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app


# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app_fast: FastAPI):
    global ptb_app
    ptb_app = _build_ptb()
    await ptb_app.initialize()
    await ptb_app.start()
    if WEBHOOK_URL:
        await ptb_app.bot.set_webhook(f'{WEBHOOK_URL}/webhook')
    yield
    if ptb_app:
        await ptb_app.stop()
        await ptb_app.shutdown()


app = FastAPI(lifespan=lifespan)


# ── Telegram webhook ────────────────────────────────────────────────────

@app.post('/webhook')
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {'ok': True}


# ── Init data validation ────────────────────────────────────────────────

def _validate(init_data: str):
    if not init_data or not TOKEN:
        return
    pairs = {}
    for part in init_data.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            pairs[unquote(k)] = unquote(v)
    received = pairs.pop('hash', '')
    if not received:
        return
    check_str = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(403, 'Invalid init data')


# ── Mini App API ────────────────────────────────────────────────────────

@app.get('/api/tasks')
async def api_tasks(init_data: str = '', x_init_data: str = Header(default='')):
    _validate(init_data or x_init_data)
    task_list = sheets.get_tasks()
    result = []
    for t in task_list:
        dl_greg = t.get('deadline', '')
        dl_jalali = sheets.greg_str_to_jalali(dl_greg) if dl_greg else ''
        result.append({
            'id':               t.get('id', 0),
            'title':            t.get('title', ''),
            'deadline':         dl_jalali,
            'deadline_greg':    dl_greg,
            'assigned_to':      t.get('assigned_to', ''),
            'assigned_user_id': str(t.get('assigned_user_id', '') or ''),
            'status':           t.get('status', 'pending'),
            'priority':         t.get('priority', 'medium'),
            'reminder_at':      t.get('reminder_at', ''),
        })
    return result


@app.post('/api/tasks')
async def api_add_task(request: Request, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    body = await request.json()
    title               = body.get('title', '').strip()
    deadline            = body.get('deadline', '')
    assigned            = body.get('assigned_to', '')
    reminder_time       = body.get('reminder_time', '')
    created_by_user_id  = str(body.get('created_by_user_id', '') or '')
    assigned_user_id    = str(body.get('assigned_user_id', '') or '')

    greg_dl = None
    if deadline:
        try:
            greg_dl = sheets.parse_jalali_input(deadline)
        except Exception:
            greg_dl = None

    reminder_at = None
    if reminder_time and greg_dl:
        reminder_at = f'{greg_dl} {reminder_time}'

    task_id = sheets.add_task(title, greg_dl, assigned or None,
                              reminder_at=reminder_at,
                              created_by_user_id=created_by_user_id or None,
                              assigned_user_id=assigned_user_id or None)
    asyncio.get_event_loop().run_in_executor(None, dashboard.update_calendar)
    return {
        'id': task_id, 'title': title,
        'deadline': deadline, 'deadline_greg': greg_dl or '',
        'assigned_to': assigned, 'status': 'pending', 'priority': 'medium',
        'reminder_at': reminder_at or '',
    }


@app.put('/api/tasks/{task_id}')
async def api_update_task(task_id: int, request: Request, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    body = await request.json()
    title            = body.get('title', '').strip()
    deadline         = body.get('deadline', '')
    assigned         = body.get('assigned_to', '')
    reminder_time    = body.get('reminder_time', '')
    assigned_user_id = str(body.get('assigned_user_id', '') or '')

    greg_dl = None
    if deadline:
        try:
            greg_dl = sheets.parse_jalali_input(deadline)
        except Exception:
            greg_dl = deadline if len(deadline) == 10 else None

    reminder_at = ''
    if reminder_time and greg_dl:
        reminder_at = f'{greg_dl} {reminder_time}'

    ok = sheets.update_task(task_id, title, greg_dl or '', assigned or '',
                            reminder_at=reminder_at, assigned_user_id=assigned_user_id)
    asyncio.get_event_loop().run_in_executor(None, dashboard.update_calendar)
    return {'ok': ok, 'deadline_greg': greg_dl or '', 'reminder_at': reminder_at}


@app.post('/api/tasks/{task_id}/complete')
async def api_complete(task_id: int, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    return {'ok': sheets.complete_task(task_id)}


@app.delete('/api/tasks/{task_id}')
async def api_delete(task_id: int, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    return {'ok': sheets.delete_task(task_id)}


@app.get('/api/users')
async def api_users(init_data: str = '', x_init_data: str = Header(default='')):
    _validate(init_data or x_init_data)
    return sheets.get_users()


@app.get('/api/habits')
async def api_habits(week_start: str = '', init_data: str = '', x_init_data: str = Header(default='')):
    _validate(init_data or x_init_data)
    if not week_start:
        from datetime import datetime as _dt
        today = _dt.now(sheets.IRAN_TZ).date()
        dow = today.weekday()  # Mon=0 … Sat=5, Sun=6
        days_since_sat = (dow + 2) % 7
        sat = today - __import__('datetime').timedelta(days=days_since_sat)
        week_start = sat.strftime('%Y-%m-%d')
    return sheets.get_habits_week(week_start)


@app.post('/api/habits/toggle')
async def api_toggle_habit(request: Request, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    body = await request.json()
    habit_name = body.get('habit_name', '')
    date_str   = body.get('date', '')
    from datetime import datetime as _dt
    habit_date = _dt.strptime(date_str, '%Y-%m-%d').date()
    result = sheets.toggle_habit(habit_name, habit_date)
    return {'completed': result}


@app.post('/api/habits')
async def api_add_habit(request: Request, x_init_data: str = Header(default='')):
    _validate(x_init_data)
    body = await request.json()
    name = body.get('name', '').strip()
    if not name:
        raise HTTPException(400, 'name required')
    sheets.add_habit_to_list(name)
    return {'ok': True}


# ── Mini App page ────────────────────────────────────────────────────────

@app.get('/app', response_class=HTMLResponse)
async def mini_app():
    try:
        with open('static/index.html', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return '<h1>Not found</h1>'


@app.get('/')
async def root():
    return {'status': 'MonazamBot OK'}
