import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes,
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import sheets
import dashboard

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

IRAN_TZ  = ZoneInfo('Asia/Tehran')
TOKEN    = os.getenv('BOT_TOKEN', '').strip()
ALLOWED  = [int(x) for x in os.getenv('ALLOWED_USERS', '').split(',') if x.strip().isdigit()]
EXECUTOR = ThreadPoolExecutor(max_workers=2)

JALALI_WD     = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']
JALALI_MONTHS = sheets.JALALI_MONTHS

# ── States ──────────────────────────────────────────────────────────────
(MENU,
 TASK_TITLE, DATE_PICK, DATE_MANUAL, TASK_ASSIGNED,
 EVENT_TITLE, EVENT_TIME,
 NEW_HABIT, HABIT_EDIT_NAME,
 LIST_HABITS, LIST_EVENTS, LIST_TASKS) = range(12)


# ── Helpers ──────────────────────────────────────────────────────────────

def allowed(uid): return not ALLOWED or uid in ALLOWED

def main_kb():
    webapp_url = os.getenv('WEBAPP_URL', os.getenv('WEBHOOK_URL', '')).strip().rstrip('/')
    rows = [
        [InlineKeyboardButton('➕ تسک جدید',   callback_data='add_task'),
         InlineKeyboardButton('📅 رویداد جدید', callback_data='add_event')],
        [InlineKeyboardButton('✅ ثبت عادت‌های امروز', callback_data='log_habits')],
        [InlineKeyboardButton('📊 هفته جاری',   callback_data='view_week'),
         InlineKeyboardButton('📋 امروز',        callback_data='view_today')],
        [InlineKeyboardButton('⚙️ عادت‌ها',     callback_data='list_habits'),
         InlineKeyboardButton('📌 تسک‌ها',      callback_data='list_tasks')],
        [InlineKeyboardButton('🗓 رویدادها',    callback_data='list_events'),
         InlineKeyboardButton('🔄 داشبورد',     callback_data='refresh_dash')],
    ]
    if webapp_url:
        rows.insert(0, [InlineKeyboardButton(
            '📱 باز کردن اپ تسک‌ها',
            web_app=WebAppInfo(url=f'{webapp_url}/')
        )])
    return InlineKeyboardMarkup(rows)

def back_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('🔙 منو', callback_data='back_menu')]])

def date_picker_kb():
    today = datetime.now(IRAN_TZ).date()
    buttons, row = [], []
    for i in range(10):
        g = today + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=g)
        mn = JALALI_MONTHS[jd.month - 1]
        if   i == 0: label = f'امروز  {jd.day} {mn}'
        elif i == 1: label = f'فردا  {jd.day} {mn}'
        else:        label = f'{JALALI_WD[g.weekday()]}  {jd.day} {mn}'
        row.append(InlineKeyboardButton(label, callback_data=f'date_{g.strftime("%Y-%m-%d")}'))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton('✏️ وارد کردن تاریخ دستی', callback_data='date_manual')])
    buttons.append([InlineKeyboardButton('🔙 منو', callback_data='back_menu')])
    return InlineKeyboardMarkup(buttons)

def _run_bg(fn, *args):
    """Run a blocking function in the thread pool (fire-and-forget)."""
    EXECUTOR.submit(fn, *args)


# ── /start ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not allowed(update.effective_user.id):
        await update.message.reply_text('⛔ دسترسی غیرمجاز.'); return ConversationHandler.END
    u = update.effective_user
    _run_bg(sheets.register_user, u.id,
            f'{u.first_name or ""} {u.last_name or ""}'.strip() or u.username or str(u.id),
            u.username or '')
    ctx.user_data.clear()
    await update.message.reply_text('👋 سلام! MonazamBot اینجاست.\nاز منو انتخاب کن:', reply_markup=main_kb())
    return MENU


# ── Main menu ─────────────────────────────────────────────────────────────

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer(); d = q.data

    if d == 'back_menu':
        ctx.user_data.clear()
        await q.edit_message_text('از منو انتخاب کن:', reply_markup=main_kb())
        return MENU
    if d == 'add_task':
        await q.edit_message_text('📝 عنوان تسک رو بنویس:\n(برای لغو /cancel)'); return TASK_TITLE
    if d == 'add_event':
        await q.edit_message_text('📅 عنوان رویداد رو بنویس:\n(برای لغو /cancel)'); return EVENT_TITLE
    if d == 'log_habits': return await _show_habits(q, ctx)
    if d == 'view_today':
        try: text = sheets.get_today_summary()
        except Exception as e: text = f'❌ خطا: {e}'
        await q.edit_message_text(text, parse_mode='HTML', reply_markup=back_kb()); return MENU
    if d == 'view_week':
        try: text = sheets.get_weekly_summary()
        except Exception as e: text = f'❌ خطا: {e}'
        await q.edit_message_text(text, parse_mode='HTML', reply_markup=back_kb()); return MENU
    if d == 'refresh_dash':
        await q.edit_message_text('🔄 در حال بروزرسانی داشبورد...')
        _run_bg(dashboard.refresh_all)
        await q.edit_message_text('✅ داشبورد بروزرسانی شد!\nگوگل شیت رو ببین.', reply_markup=back_kb())
        return MENU
    if d == 'list_habits': return await _list_habits_manage(q, ctx)
    if d == 'list_events': return await _list_events(q, ctx)
    if d == 'list_tasks':  return await _list_tasks(q, ctx)
    return MENU


# ── Habit habit tracking (toggle today) ──────────────────────────────────

async def _show_habits(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    today = datetime.now(IRAN_TZ).date()
    try: habits = sheets.get_habits_list(); logged = sheets.get_logged_habits_today(today)
    except Exception as e:
        await q.edit_message_text(f'❌ خطا: {e}', reply_markup=back_kb()); return MENU
    ctx.user_data['habits_list'] = habits
    if not habits:
        await q.edit_message_text('هنوز عادتی تعریف نشده.\nاز ⚙️ عادت‌ها اضافه کن.', reply_markup=back_kb())
        return MENU
    btns = [[InlineKeyboardButton(f'{"✅" if h in logged else "⭕"} {h}', callback_data=f'ht_{i}')] for i, h in enumerate(habits)]
    btns.append([InlineKeyboardButton('🔙 منو', callback_data='back_menu')])
    done = sum(1 for h in habits if h in logged)
    await q.edit_message_text(
        f'عادت‌های امروز ({sheets.today_jalali()}):\n{done}/{len(habits)} انجام شده:',
        reply_markup=InlineKeyboardMarkup(btns))
    return MENU

async def habit_toggle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    idx = int(q.data.split('_')[1])
    habits = ctx.user_data.get('habits_list', [])
    if idx < len(habits):
        try:
            sheets.toggle_habit(habits[idx], datetime.now(IRAN_TZ).date())
            _run_bg(dashboard.update_habit_tracker)
        except Exception as e: await q.answer(f'خطا: {e}', show_alert=True)
    return await _show_habits(q, ctx)


# ── Habit management (edit/delete) ────────────────────────────────────────

async def _list_habits_manage(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try: habits = sheets.get_habits_list()
    except Exception as e:
        await q.edit_message_text(f'❌ خطا: {e}', reply_markup=back_kb()); return MENU
    ctx.user_data['habits_list'] = habits
    if not habits:
        await q.edit_message_text('هنوز عادتی تعریف نشده.\nاسم عادت جدید رو بنویس:', reply_markup=back_kb())
        return NEW_HABIT
    btns = []
    for i, h in enumerate(habits):
        btns.append([
            InlineKeyboardButton(f'🔸 {h}', callback_data=f'noop'),
            InlineKeyboardButton('✏️', callback_data=f'edit_h_{i}'),
            InlineKeyboardButton('🗑', callback_data=f'del_h_{i}'),
        ])
    btns.append([InlineKeyboardButton('➕ عادت جدید', callback_data='new_habit_prompt')])
    btns.append([InlineKeyboardButton('🔙 منو', callback_data='back_menu')])
    await q.edit_message_text('⚙️ مدیریت عادت‌ها:', reply_markup=InlineKeyboardMarkup(btns))
    return LIST_HABITS

async def habit_manage_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer(); d = q.data
    habits = ctx.user_data.get('habits_list', [])

    if d == 'new_habit_prompt':
        await q.edit_message_text('اسم عادت جدید رو بنویس:',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت', callback_data='list_habits')]]))
        return NEW_HABIT

    if d.startswith('edit_h_'):
        idx = int(d.split('_')[-1])
        ctx.user_data['edit_habit_old'] = habits[idx]
        await q.edit_message_text(
            f'نام جدید عادت «{habits[idx]}» رو بنویس:',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت', callback_data='list_habits')]]))
        return HABIT_EDIT_NAME

    if d.startswith('del_h_'):
        idx = int(d.split('_')[-1])
        try: sheets.remove_habit(habits[idx])
        except Exception as e: await q.answer(f'خطا: {e}', show_alert=True); return LIST_HABITS
        await q.answer(f'✅ عادت «{habits[idx]}» حذف شد.')
        _run_bg(dashboard.update_habit_tracker)
        return await _list_habits_manage(q, ctx)

    if d == 'list_habits': return await _list_habits_manage(q, ctx)
    return LIST_HABITS

async def habit_edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    old_name = ctx.user_data.get('edit_habit_old', '')
    try: sheets.update_habit_name(old_name, new_name)
    except Exception as e:
        await update.message.reply_text(f'❌ خطا: {e}', reply_markup=main_kb()); return MENU
    _run_bg(dashboard.update_habit_tracker)
    await update.message.reply_text(f'✅ عادت «{old_name}» به «{new_name}» تغییر یافت.', reply_markup=main_kb())
    return MENU

async def new_habit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    try: sheets.add_habit_to_list(name)
    except Exception as e:
        await update.message.reply_text(f'❌ خطا: {e}', reply_markup=main_kb()); return MENU
    _run_bg(dashboard.update_habit_tracker)
    await update.message.reply_text(f'✅ عادت «{name}» اضافه شد!', reply_markup=main_kb())
    return MENU


# ── Event list (edit/delete) ──────────────────────────────────────────────

async def _list_events(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    today = datetime.now(IRAN_TZ).date()
    try: events = sheets.get_events_range(today, today + timedelta(days=60))
    except Exception as e:
        await q.edit_message_text(f'❌ خطا: {e}', reply_markup=back_kb()); return MENU
    if not events:
        await q.edit_message_text('هیچ رویدادی ثبت نشده.', reply_markup=back_kb()); return MENU
    btns = []
    for e in events[:8]:
        jd = sheets.greg_str_to_jalali_verbose(e['date'])
        t  = f' {e["time"]}' if e.get('time') else ''
        label = f'{e["title"]} — {jd}{t}'
        btns.append([
            InlineKeyboardButton(label[:38], callback_data='noop'),
        ])
        btns.append([
            InlineKeyboardButton('✏️ ویرایش', callback_data=f'edit_e_{e["id"]}'),
            InlineKeyboardButton('🗑 حذف',    callback_data=f'del_e_{e["id"]}'),
        ])
    btns.append([InlineKeyboardButton('🔙 منو', callback_data='back_menu')])
    await q.edit_message_text('🗓 رویدادهای پیش رو:', reply_markup=InlineKeyboardMarkup(btns))
    return LIST_EVENTS

async def event_list_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer(); d = q.data

    if d.startswith('del_e_'):
        eid = int(d.split('_')[-1])
        try: sheets.delete_event(eid)
        except Exception as e: await q.answer(f'خطا: {e}', show_alert=True); return LIST_EVENTS
        await q.answer('✅ رویداد حذف شد.')
        _run_bg(dashboard.update_calendar)
        return await _list_events(q, ctx)

    if d.startswith('edit_e_'):
        eid = int(d.split('_')[-1])
        ctx.user_data['edit_event_id'] = eid
        await q.edit_message_text('📅 عنوان جدید رویداد رو بنویس:')
        return EVENT_TITLE

    return LIST_EVENTS


# ── Task list (edit/delete) ───────────────────────────────────────────────

async def _list_tasks(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try: tasks = sheets.get_tasks('pending')
    except Exception as e:
        await q.edit_message_text(f'❌ خطا: {e}', reply_markup=back_kb()); return MENU
    if not tasks:
        await q.edit_message_text('هیچ تسک فعالی وجود ندارد.', reply_markup=back_kb()); return MENU
    btns = []
    for t in tasks[:8]:
        dl  = f' — {sheets.greg_str_to_jalali_verbose(t["deadline"])}' if t.get('deadline') else ''
        who = f' 👤{t["assigned_to"]}' if t.get('assigned_to') else ''
        label = f'{t["title"]}{dl}{who}'
        btns.append([InlineKeyboardButton(label[:40], callback_data='noop')])
        btns.append([
            InlineKeyboardButton('✏️ ویرایش',  callback_data=f'edit_t_{t["id"]}'),
            InlineKeyboardButton('✅ انجام شد', callback_data=f'done_t_{t["id"]}'),
            InlineKeyboardButton('🗑 حذف',     callback_data=f'del_t_{t["id"]}'),
        ])
    btns.append([InlineKeyboardButton('🔙 منو', callback_data='back_menu')])
    await q.edit_message_text('📌 تسک‌های فعال:', reply_markup=InlineKeyboardMarkup(btns))
    return LIST_TASKS

async def task_list_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer(); d = q.data

    if d.startswith('del_t_'):
        tid = int(d.split('_')[-1])
        try: sheets.delete_task(tid)
        except Exception as e: await q.answer(f'خطا: {e}', show_alert=True); return LIST_TASKS
        await q.answer('✅ تسک حذف شد.')
        _run_bg(dashboard.update_calendar)
        return await _list_tasks(q, ctx)

    if d.startswith('done_t_'):
        tid = int(d.split('_')[-1])
        try: sheets.complete_task(tid)
        except Exception as e: await q.answer(f'خطا: {e}', show_alert=True); return LIST_TASKS
        await q.answer('✅ تسک انجام‌شده ثبت شد.')
        return await _list_tasks(q, ctx)

    if d.startswith('edit_t_'):
        tid = int(d.split('_')[-1])
        ctx.user_data['edit_task_id'] = tid
        await q.edit_message_text('📝 عنوان جدید تسک رو بنویس:')
        return TASK_TITLE

    return LIST_TASKS


# ── Task add/edit flow ────────────────────────────────────────────────────

async def task_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data['task_title'] = update.message.text.strip()
    ctx.user_data['date_flow']  = 'task'
    await update.message.reply_text('📅 ددلاین رو از تقویم انتخاب کن:', reply_markup=date_picker_kb())
    return DATE_PICK

async def task_assigned(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text     = update.message.text.strip()
    assigned = None if text.lower() == 'skip' else text
    title    = ctx.user_data.get('task_title', '')
    deadline = ctx.user_data.get('selected_date')
    edit_id  = ctx.user_data.get('edit_task_id')
    try:
        if edit_id is not None:
            sheets.update_task(edit_id, title, deadline or '', assigned or '')
        else:
            sheets.add_task(title, deadline, assigned)
    except Exception as e:
        await update.message.reply_text(f'❌ خطا: {e}', reply_markup=main_kb()); ctx.user_data.clear(); return MENU
    _run_bg(dashboard.update_calendar)
    parts = [f'{"✅ تسک ویرایش شد" if edit_id else "✅ تسک ذخیره شد"}!\n📌 {title}']
    if deadline: parts.append(f'📅 {sheets.greg_str_to_jalali_verbose(deadline)}')
    if assigned: parts.append(f'👤 {assigned}')
    await update.message.reply_text('\n'.join(parts), reply_markup=main_kb())
    ctx.user_data.clear(); return MENU


# ── Event add/edit flow ────────────────────────────────────────────────────

async def event_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data['event_title'] = update.message.text.strip()
    ctx.user_data['date_flow']   = 'event'
    await update.message.reply_text('📅 تاریخ رویداد رو از تقویم انتخاب کن:', reply_markup=date_picker_kb())
    return DATE_PICK

async def event_time_h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text    = update.message.text.strip()
    ev_time = None if text.lower() == 'skip' else text
    title   = ctx.user_data.get('event_title', '')
    ev_date = ctx.user_data.get('selected_date', '')
    edit_id = ctx.user_data.get('edit_event_id')
    try:
        if edit_id is not None:
            sheets.update_event(edit_id, title, ev_date, ev_time or '')
        else:
            sheets.add_event(title, ev_date, ev_time)
    except Exception as e:
        await update.message.reply_text(f'❌ خطا: {e}', reply_markup=main_kb()); ctx.user_data.clear(); return MENU
    _run_bg(dashboard.update_calendar)
    jdate = sheets.greg_str_to_jalali_verbose(ev_date)
    t_str = f' ساعت {ev_time}' if ev_time else ''
    await update.message.reply_text(
        f'{"✅ رویداد ویرایش شد" if edit_id else "✅ رویداد ذخیره شد"}!\n📅 {title} — {jdate}{t_str}',
        reply_markup=main_kb())
    ctx.user_data.clear(); return MENU


# ── Date picker ────────────────────────────────────────────────────────────

async def date_pick_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer(); d = q.data
    if d == 'date_manual':
        flow = ctx.user_data.get('date_flow', 'task')
        await q.edit_message_text(
            '📅 تاریخ رو به شمسی بنویس:\nمثلاً:  <b>1405/03/15</b>',
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 تقویم', callback_data=f'bdp_{flow}')]]))
        return DATE_MANUAL
    greg = d[5:]
    ctx.user_data['selected_date'] = greg
    jlabel = sheets.greg_str_to_jalali_verbose(greg)
    flow = ctx.user_data.get('date_flow', 'task')
    if flow == 'task':
        await q.edit_message_text(f'📅 ددلاین: <b>{jlabel}</b>\n\n👤 مسئول این تسک کیه؟\nیا skip بنویس.', parse_mode='HTML')
        return TASK_ASSIGNED
    else:
        await q.edit_message_text(f'📅 تاریخ: <b>{jlabel}</b>\n\n🕐 ساعت رویداد رو بنویس (مثلاً: 19:00)\nیا skip بنویس.', parse_mode='HTML')
        return EVENT_TIME

async def back_dp_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    flow = q.data.split('_')[-1]
    ctx.user_data['date_flow'] = flow
    label = 'ددلاین تسک' if flow == 'task' else 'تاریخ رویداد'
    await q.edit_message_text(f'📅 {label} رو از تقویم انتخاب کن:', reply_markup=date_picker_kb())
    return DATE_PICK

async def date_manual_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try: greg = sheets.parse_jalali_input(text)
    except Exception:
        await update.message.reply_text('❌ فرمت نادرست.\nمثلاً: <b>1405/03/15</b>', parse_mode='HTML')
        return DATE_MANUAL
    ctx.user_data['selected_date'] = greg
    jlabel = sheets.greg_str_to_jalali_verbose(greg)
    flow = ctx.user_data.get('date_flow', 'task')
    if flow == 'task':
        await update.message.reply_text(f'📅 ددلاین: <b>{jlabel}</b>\n\n👤 مسئول این تسک کیه؟\nیا skip بنویس.', parse_mode='HTML')
        return TASK_ASSIGNED
    else:
        await update.message.reply_text(f'📅 تاریخ: <b>{jlabel}</b>\n\n🕐 ساعت رویداد رو بنویس (مثلاً: 19:00)\nیا skip بنویس.', parse_mode='HTML')
        return EVENT_TIME


# ── /cancel & /done ────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text('❌ لغو شد.', reply_markup=main_kb())
    return MENU

async def done_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text('استفاده: /done <شماره_تسک>'); return MENU
    try: ok = sheets.complete_task(int(args[0]))
    except Exception as e: await update.message.reply_text(f'❌ خطا: {e}'); return MENU
    await update.message.reply_text('✅ تسک انجام‌شده ثبت شد!' if ok else '❌ تسک پیدا نشد.', reply_markup=main_kb())
    return MENU


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    if not TOKEN: raise RuntimeError('BOT_TOKEN در .env تنظیم نشده.')
    proxy = os.getenv('PROXY_URL', '').strip()
    if proxy:
        app = Application.builder().token(TOKEN).request(HTTPXRequest(proxy=proxy)).build()
    else:
        app = Application.builder().token(TOKEN).build()

    bk  = CallbackQueryHandler(menu_cb,         pattern='^back_menu$')
    bdp = CallbackQueryHandler(back_dp_cb,       pattern=r'^bdp_')
    DATE_PAT = r'^date_(\d{4}-\d{2}-\d{2}|manual)$'

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MENU: [
                CallbackQueryHandler(menu_cb,        pattern='^(add_task|add_event|log_habits|view_week|view_today|refresh_dash|list_habits|list_events|list_tasks|back_menu)$'),
                CallbackQueryHandler(habit_toggle_cb, pattern=r'^ht_\d+$'),
            ],
            TASK_TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, task_title), bk],
            DATE_PICK:    [CallbackQueryHandler(date_pick_cb, pattern=DATE_PAT), bk],
            DATE_MANUAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, date_manual_input), bdp, bk],
            TASK_ASSIGNED:[MessageHandler(filters.TEXT & ~filters.COMMAND, task_assigned), bk],
            EVENT_TITLE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, event_title), bk],
            EVENT_TIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, event_time_h), bk],
            NEW_HABIT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, new_habit),
                           CallbackQueryHandler(habit_manage_cb, pattern='^list_habits$'), bk],
            HABIT_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, habit_edit_name), bk],
            LIST_HABITS:  [CallbackQueryHandler(habit_manage_cb, pattern=r'^(edit_h_|del_h_|new_habit_prompt|list_habits|noop)'), bk],
            LIST_EVENTS:  [CallbackQueryHandler(event_list_cb,   pattern=r'^(edit_e_|del_e_|noop)'), bk],
            LIST_TASKS:   [CallbackQueryHandler(task_list_cb,    pattern=r'^(edit_t_|done_t_|del_t_|noop)'), bk],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start), CommandHandler('done', done_cmd)],
        allow_reentry=True,
    )
    app.add_handler(conv)

    async def _send_reminders(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            tasks_due = sheets.get_pending_reminders()
        except Exception:
            return
        for t in tasks_due:
            uid = str(t.get('created_by_user_id', '')).strip()
            auid = str(t.get('assigned_user_id', '')).strip()
            text = f'⏰ یادآوری تسک:\n📌 {t.get("title", "")}'
            if t.get('deadline'):
                text += f'\n📅 ددلاین: {sheets.greg_str_to_jalali_verbose(t["deadline"])}'
            notified = set()
            for chat_id in [uid, auid]:
                if chat_id and chat_id.isdigit() and chat_id not in notified:
                    try:
                        await ctx.bot.send_message(chat_id=int(chat_id), text=text)
                        notified.add(chat_id)
                    except Exception as e:
                        logger.warning(f'Reminder send error {chat_id}: {e}')
            sheets.mark_reminder_sent(int(t.get('id', 0)))

    app.job_queue.run_repeating(_send_reminders, interval=60, first=15)
    logger.info('MonazamBot started.')

    webhook_url = os.getenv('WEBHOOK_URL', '').strip()
    if webhook_url:
        port = int(os.getenv('PORT', 8080))
        logger.info(f'Webhook mode: {webhook_url} port {port}')
        app.run_webhook(
            listen='0.0.0.0',
            port=port,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
