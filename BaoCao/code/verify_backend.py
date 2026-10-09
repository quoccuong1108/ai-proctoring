import os,sys,tempfile,io,json,pathlib
import argparse
parser=argparse.ArgumentParser(description='17 isolated EduShield backend checks; synthetic data only')
parser.add_argument('--backend',required=True)
parser.add_argument('--output',default='report-results.json')
args=parser.parse_args()
output_path=pathlib.Path(args.output).resolve()
source=pathlib.Path(args.backend).resolve();sys.path.insert(0,str(source));os.environ['PROCTOR_API_TOKEN']='report-fixture-only'
work=tempfile.TemporaryDirectory();os.chdir(work.name)
from fastapi.testclient import TestClient
from main import app
from database import init_db
from openpyxl import Workbook
from docx import Document
from exam_parser import parse_exam_file
init_db();c=TestClient(app);h={'X-Proctor-Token':'report-fixture-only'};results=[]
def check(name,condition,detail=''):
 results.append({'case':name,'passed':bool(condition),'detail':detail})
 if not condition:raise AssertionError(name)
def sheet(rows):
 w=Workbook();ws=w.active;ws.append(['STT','Câu hỏi','A','B','C','D','Đáp án đúng'])
 for row in rows:ws.append(row)
 b=io.BytesIO();w.save(b);return b.getvalue()
valid=[[1,'Câu hỏi thứ nhất','a','b','c','d','A'],[2,'Câu hỏi thứ hai','a','b','c','d','B']]
check('P01 Excel hợp lệ',parse_exam_file('a.xlsx',sheet(valid)).valid_count==2)
check('P02 Loại câu trùng',parse_exam_file('a.xlsx',sheet(valid+[valid[0]])).valid_count==2)
check('P03 Bỏ câu thiếu đáp án',parse_exam_file('a.xlsx',sheet(valid+[[3,'Thiếu','a','','c','d','A']])).valid_count==2)
check('P04 Từ chối vượt 200 câu',parse_exam_file('a.xlsx',sheet([[i,str(i),'a','b','c','d','A'] for i in range(201)])).valid_count==0)
d=Document()
for line in ['Câu 1: Một câu hỏi','A. a','B. b','C. c','D. d','Đáp án: A']:d.add_paragraph(line)
b=io.BytesIO();d.save(b);check('P05 Word hợp lệ',parse_exam_file('a.docx',b.getvalue()).valid_count==1)
check('P06 Từ chối định dạng khác',parse_exam_file('a.txt',b'x').valid_count==0)
check('A01 API quản lý cần token',c.get('/api/exams').status_code==401)
r=c.post('/api/exams/upload',headers=h,data={'title':'Đề kiểm thử','exam_code':'DE-TEST'},files={'file':('test.xlsx',sheet(valid))});check('A02 Tạo đề nháp',r.status_code==200 and r.json()['exam']['status']=='DRAFT');eid=r.json()['exam']['id']
check('A03 Đề nháp không được lấy',c.get('/api/exams/code/DE-TEST/take').status_code==403)
check('A04 Công bố đề',c.post(f'/api/exams/{eid}/publish',headers=h,json={'duration_minutes':10,'pass_score':5}).status_code==200)
r=c.get('/api/exams/code/DE-TEST/take');qs=r.json()['questions'];check('A05 Không lộ đáp án đúng',r.status_code==200 and all('correct_option' not in q for q in qs))
payload={'student_id':'SV-TEST','student_name':'Dữ liệu tổng hợp','answers':[{'question_id':qs[0]['id'],'selected_option':'A'},{'question_id':qs[1]['id'],'selected_option':'A'}]};r=c.post('/api/exams/code/DE-TEST/submit',json=payload);check('A06 Chấm đúng 5 trên 10',r.status_code==200 and r.json()['total_score']==5,r.text)
check('A07 Chặn nộp trùng',c.post('/api/exams/code/DE-TEST/submit',json=payload).status_code==409)
check('A08 Xuất Excel',c.get(f'/api/exams/{eid}/export',headers=h).status_code==200)
r=c.post('/api/violations',json={'student_id':'SV-TEST','violation_type':'NO_FACE','captured_at':'2026-09-25T14:00:00+07:00'});check('A09 Chuẩn hóa UTC',r.status_code==201 and r.json()['captured_at'].startswith('2026-09-25T07:00:00'))
check('A10 Nhãn vi phạm không hợp lệ',c.post('/api/violations',json={'student_id':'SV-TEST','violation_type':'UNKNOWN','captured_at':'2026-09-25T07:00:00Z'}).status_code==400)
check('A11 Ảnh yêu cầu token',c.get('/api/snapshots/SV-TEST/nonexistent.jpg').status_code==401)
output_path.parent.mkdir(parents=True,exist_ok=True)
output_path.write_text(json.dumps(results,ensure_ascii=False,indent=2));print('PASS',len(results),'cases. Synthetic data, isolated SQLite.')
