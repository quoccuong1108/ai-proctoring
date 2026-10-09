"""Focused API regression checks for the mobile time/event update; isolated data."""
import argparse,pathlib,tempfile,os,sys,io,json
from datetime import datetime,timedelta,timezone
p=argparse.ArgumentParser();p.add_argument('--backend',required=True);p.add_argument('--output',required=True);a=p.parse_args()
out=pathlib.Path(a.output).resolve();sys.path.insert(0,str(pathlib.Path(a.backend).resolve()));os.environ['PROCTOR_API_TOKEN']='report-fixture-only'
work=tempfile.TemporaryDirectory();os.chdir(work.name)
from main import app
from database import init_db,SessionLocal,ExamStart,ExamSubmission
from fastapi.testclient import TestClient
from openpyxl import Workbook
init_db();c=TestClient(app);h={'X-Proctor-Token':'report-fixture-only'};results=[]
def check(n,b):
 results.append({'case':n,'passed':bool(b)})
 assert b,n
w=Workbook();w.active.append(['STT','Câu hỏi','A','B','C','D','Đáp án']);w.active.append([1,'Một câu','a','b','c','d','A']);f=io.BytesIO();w.save(f)
r=c.post('/api/exams/upload',headers=h,data={'title':'Mobile test','exam_code':'MOBILE'},files={'file':('test.xlsx',f.getvalue())});assert r.status_code==200;eid=r.json()['exam']['id']
check('M01 /start từ chối đề nháp',c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'}).status_code==403)
c.post(f'/api/exams/{eid}/publish',headers=h,json={'duration_minutes':10,'pass_score':5})
r=c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'});d=r.json();check('M02 Bắt đầu ghi giờ server',r.status_code==200 and 598<=d['remaining_seconds']<=600 and d['started_at'].endswith('Z'))
r2=c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'});db=SessionLocal();check('M03 Gọi lại không tạo mốc mới',r2.json()['started_at']==d['started_at'] and db.query(ExamStart).count()==1)
x=db.query(ExamStart).first();x.started_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=120);db.commit()
r=c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'});check('M04 Thời gian còn lại giảm theo mốc cũ',478<=r.json()['remaining_seconds']<=480)
x.started_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=660);db.commit();check('M05 Quá thời lượng trả 0',c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'}).json()['remaining_seconds']==0)
q=c.get('/api/exams/code/MOBILE/take').json()['questions'][0]['id'];payload={'student_id':'S1','answers':[{'question_id':q,'selected_option':'A'}]}
r=c.post('/api/exams/code/MOBILE/submit',json=payload);check('M06 Xác nhận giới hạn: vẫn nhận bài quá hạn',r.status_code==200)
db.expire_all();check('M07 started_at được chép vào bài nộp',db.query(ExamSubmission).first().started_at==db.query(ExamStart).first().started_at)
check('M08 Đã nộp không được bắt đầu lại',c.post('/api/exams/code/MOBILE/start',json={'student_id':'S1'}).status_code==409)
check('M09 Nhận nhãn TAB_SWITCH không cần ảnh',c.post('/api/violations',json={'student_id':'S1','violation_type':'TAB_SWITCH','captured_at':'2026-10-01T09:00:00Z'}).status_code==201)
check('M10 Mã đề không tồn tại trả 404',c.post('/api/exams/code/MISSING/start',json={'student_id':'S1'}).status_code==404)
check('M11 Xác nhận giới hạn: submit không bắt buộc start',c.post('/api/exams/code/MOBILE/submit',json={'student_id':'S2','answers':[]}).status_code==200)
out.write_text(json.dumps(results,ensure_ascii=False,indent=2));print('PASS',len(results),'focused API cases; no real-device test.')
