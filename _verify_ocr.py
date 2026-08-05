# -*- coding: utf-8 -*-
import json
import sys
sys.path.insert(0, r'C:\Users\29095\WorkBuddy\2026-06-07-22-05-26\StepLearn')
import db

conn = db.get_connection()
rows = conn.execute(
    "SELECT id, input_data FROM ai_tasks WHERE input_data LIKE '%_ocr_text%' ORDER BY id DESC LIMIT 3"
).fetchall()
print('找到任务:', [r['id'] for r in rows])
for r in rows:
    d = json.loads(r['input_data'])
    t = d.get('_ocr_text', '')
    for kw in ('tried his best', 'maintenance staff'):
        i = t.find(kw)
        if i >= 0:
            print(f'\n=== task {r["id"]} OCR 片段（含 {kw}）===')
            print(t[max(0, i - 500):i + 600])
            break
    else:
        print(f'\ntask {r["id"]} 未找到关键词')
conn.close()
