"""
One-time migration: adds missing columns to tasks sheet and creates users sheet.
Run once: python migrate_sheets.py
"""
import sheets

def run():
    wb = sheets.get_wb()

    # ── tasks sheet: add new columns if missing ──────────────────────
    ws_tasks = wb.worksheet('tasks')
    headers = ws_tasks.row_values(1)
    print(f'tasks headers now: {headers}')

    needed = ['reminder_at', 'created_by_user_id', 'assigned_user_id', 'reminder_sent']
    missing = [c for c in needed if c not in headers]
    if missing:
        # Resize sheet to fit new columns
        new_col_count = len(headers) + len(missing)
        ws_tasks.resize(rows=ws_tasks.row_count, cols=new_col_count)
        print(f'  resized to {new_col_count} columns')

    added = []
    for col_name in needed:
        if col_name not in headers:
            next_col = len(headers) + 1
            ws_tasks.update_cell(1, next_col, col_name)
            headers.append(col_name)
            added.append(col_name)
            print(f'  + added column: {col_name} (col {next_col})')

    if not added:
        print('  tasks sheet already has all columns.')

    # ── users sheet: create if missing ───────────────────────────────
    sheet_names = [s.title for s in wb.worksheets()]
    if 'users' not in sheet_names:
        ws_users = wb.add_worksheet(title='users', rows=200, cols=5)
        ws_users.append_row(['user_id', 'name', 'username'])
        print('+ created users sheet with headers.')
    else:
        print('  users sheet already exists.')

    print('\nMigration done.')

if __name__ == '__main__':
    run()
