import sys
sys.stdout.reconfigure(encoding='utf-8')

"""
این اسکریپت تب‌های لازم رو در گوگل شیتی که خودت ساختی ایجاد می‌کنه.

قبل از اجرا:
  1. یه Google Sheet دستی بساز (sheets.google.com)
  2. با ایمیل  dastiar-sheets@dastiar-bot.iam.gserviceaccount.com  اشتراک‌گذاری (Editor) کن
  3. SHEET_ID رو در .env بذار
  4. python setup.py رو اجرا کن
"""

import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def add_sheet(wb, name, rows, cols, headers, color):
    try:
        ws = wb.worksheet(name)
        print(f'  تب "{name}" قبلاً وجود داره — هدر چک می‌شه.')
    except gspread.WorksheetNotFound:
        ws = wb.add_worksheet(name, rows=rows, cols=cols)
        print(f'  تب "{name}" ساخته شد.')

    existing = ws.row_values(1)
    if not existing:
        ws.append_row(headers)
        ws.format(f'A1:{chr(64 + len(headers))}1', {
            'textFormat': {'bold': True},
            'backgroundColor': color,
        })
    return ws


def setup():
    sheet_id = os.getenv('SHEET_ID', '').strip()
    if not sheet_id:
        print('❌ SHEET_ID در .env خالیه.')
        print('   مراحل:')
        print('   1. یه Google Sheet دستی بساز')
        print('   2. با dastiar-sheets@dastiar-bot.iam.gserviceaccount.com شیر کن (Editor)')
        print('   3. SHEET_ID رو از URL شیت کپی کن و در .env بذار')
        sys.exit(1)

    creds = Credentials.from_service_account_file(
        os.path.join(BASE, 'creds.json'), scopes=SCOPES
    )
    client = gspread.authorize(creds)

    print(f'در حال اتصال به شیت {sheet_id} ...')
    try:
        wb = client.open_by_key(sheet_id)
    except gspread.exceptions.APIError as e:
        print(f'❌ خطا در اتصال: {e}')
        print('مطمئن شو که:')
        print('  - Google Sheets API فعاله (console.cloud.google.com)')
        print('  - شیت با سرویس اکانت شیر شده')
        sys.exit(1)

    blue   = {'red': 0.27, 'green': 0.51, 'blue': 0.71}
    green  = {'red': 0.18, 'green': 0.65, 'blue': 0.47}
    orange = {'red': 0.95, 'green': 0.61, 'blue': 0.07}

    print('در حال ساخت تب‌ها...')
    add_sheet(wb, 'tasks',      1000, 7, ['id', 'title', 'deadline', 'assigned_to', 'status', 'priority', 'created_at'], blue)
    add_sheet(wb, 'events',     1000, 6, ['id', 'title', 'date', 'time', 'category', 'created_at'], green)
    add_sheet(wb, 'habits',     5000, 3, ['date', 'habit_name', 'completed'], orange)
    add_sheet(wb, 'habit_list',  100, 2, ['name', 'active'], orange)

    print('\n✅ ستاپ کامل شد! حالا python bot.py رو بزن.')


if __name__ == '__main__':
    setup()
