"""Run synthetic checks on a temporary, source-only copy of the final backend."""
import argparse, io, json, os, shutil, sys, tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
p=argparse.ArgumentParser();p.add_argument('--backend',required=True);p.add_argument('--output',required=True);args=p.parse_args()
source=Path(args.backend).resolve();out=Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
work=tempfile.TemporaryDirectory(prefix='edushield_final_');root=Path(work.name)/'backend';root.mkdir()
for f in source.glob('*.py'):shutil.copy2(f,root/f.name)
os.environ['ALLOW_LEGACY_TOKEN']='0';os.environ.pop('PROCTOR_API_TOKEN',None)
os.chdir(root);sys.path.insert(0,str(root))
from fastapi.testclient import TestClient
from openpyxl import Workbook,load_workbook
from docx import Document
from main import app
from database import init_db,SessionLocal,Teacher,ExamStart,ExamSubmission,Violation,ExamEnrollment,Exam
from auth import hash_password
from exam_parser import parse_exam_file
init_db();client=TestClient(app);results=[]
def check(code,title,ok,detail=''):
 results.append(dict(code=code,title=title,passed=bool(ok),detail=detail))
 out.write_text(json.dumps(results,ensure_ascii=False,indent=2))
 if not ok:raise AssertionError((code,title,detail))
def xlsx(rows):
 w=Workbook();w.active.append(['STT','Câu hỏi','A','B','C','D','Đáp án']);
 for row in rows:w.active.append(row)
 b=io.BytesIO();w.save(b);return b.getvalue()
rows=[[1,'Câu một','a','b','c','d','A'],[2,'Câu hai','a','b','c','d','B']];data=xlsx(rows)
check('P01','Đọc Excel hợp lệ',parse_exam_file('a.xlsx',data).valid_count==2)
check('P02','Loại câu trùng',parse_exam_file('a.xlsx',xlsx(rows+[rows[0]])).valid_count==2)
check('P03','Bỏ câu thiếu lựa chọn',parse_exam_file('a.xlsx',xlsx(rows+[[3,'Câu ba','a','','c','d','A']])).valid_count==2)
check('P04','Từ chối bộ vượt 200 câu',parse_exam_file('a.xlsx',xlsx([[i,str(i),'a','b','c','d','A'] for i in range(201)])).valid_count==0)
d=Document()
for line in ['Câu 1: Câu hỏi','A. a','B. b','C. c','D. d','Đáp án: A']:d.add_paragraph(line)
b=io.BytesIO();d.save(b)
check('P05','Đọc Word đúng mẫu',parse_exam_file('a.docx',b.getvalue()).valid_count==1)
check('P06','Từ chối định dạng TXT',parse_exam_file('a.txt',b'x').valid_count==0)
with SessionLocal() as db:
 for code in ['GV-2026','GV-2027']:
  h,s=hash_password('Synthetic-only-2026!');db.add(Teacher(teacher_code=code,full_name='Giảng viên thử',password_hash=h,password_salt=s))
 db.commit()
check('A01','Chặn API quản lý khi thiếu phiên',client.get('/api/exams').status_code==401)
r=client.post('/api/auth/teacher/login',json={'teacher_code':'GV-2026','password':'incorrect'})
check('A02','Từ chối mật khẩu sai',r.status_code==401)
def login(code):
 r=client.post('/api/auth/teacher/login',json={'teacher_code':code,'password':'Synthetic-only-2026!'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['access_token']}
h=login('GV-2026');h2=login('GV-2027')
check('A03','Đăng nhập và tra cứu phiên',client.get('/api/auth/teacher/me',headers=h).json()['teacher']['teacher_code']=='GV-2026')
r=client.post('/api/exams/upload',headers=h,data={'title':'Đề thử','subject':'AI','exam_code':'FINAL'},files={'file':('test.xlsx',data)})
check('E01','Tạo đề nháp theo môn',r.status_code==200 and r.json()['exam']['status']=='DRAFT',r.text)
eid=r.json()['exam']['id'];base=f'/api/exams/{eid}'
check('E02','Chặn giảng viên khác xem đề',client.get(base,headers=h2).status_code==404)
check('E03','Bắt buộc lịch công bố',client.post(base+'/publish',headers=h,json={'duration_minutes':10}).status_code==422)
now=datetime.now(timezone.utc)
r=client.post(base+'/publish',headers=h,json={'duration_minutes':10,'pass_score':5,'start_time':(now-timedelta(minutes=1)).isoformat(),'end_time':(now+timedelta(hours=2)).isoformat()})
check('E04','Công bố đề có lịch',r.status_code==200 and r.json()['status']=='PUBLISHED')
check('S01','Lấy đề cần phiên sinh viên',client.get('/api/exams/code/FINAL/take').status_code==401)
def enroll(sid):
 r=client.post(base+'/join-request',json={'student_id':sid,'student_name':'Sinh viên thử'})
 assert r.status_code==200,r.text
 en=r.json();rh={'X-Request-Token':en['request_token']}
 return en['enrollment_id'],rh
nid,rh=enroll('SV-00000001')
check('S02','Yêu cầu mới chờ duyệt',client.get('/api/exams/join-request/status',headers=rh).json()['status']=='PENDING')
check('S03','Giảng viên duyệt yêu cầu',client.post(base+f'/enrollments/{nid}/approve',headers=h).status_code==200)
r=client.get('/api/exams/join-request/status',headers=rh);sh={'X-Exam-Session':r.json()['exam_session_token']}
check('S04','Token phiên chỉ trả một lần','exam_session_token' not in client.get('/api/exams/join-request/status',headers=rh).json())
r=client.get('/api/exams/code/FINAL/take',headers=sh);qs=r.json()['questions']
check('S05','Đề sinh viên không có đáp án chuẩn',r.status_code==200 and all('correct_option' not in q for q in qs))
check('T01','Từ chối nộp khi chưa bắt đầu',client.post('/api/exams/code/FINAL/submit',headers=sh,json={'answers':[]}).status_code==403)
r=client.post('/api/exams/code/FINAL/start',headers=sh);first=r.json()
check('T02','Bắt đầu trả thời gian còn lại',r.status_code==200 and 595<=first['remaining_seconds']<=600)
r=client.post('/api/exams/code/FINAL/start',headers=sh)
with SessionLocal() as db:count=db.query(ExamStart).count()
check('T03','Gọi lại giữ mốc bắt đầu',r.json()['started_at']==first['started_at'] and count==1)
with SessionLocal() as db:
 x=db.query(ExamStart).first();x.started_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=120);db.commit()
r=client.post('/api/exams/code/FINAL/start',headers=sh)
check('T04','Giờ còn lại giảm theo mốc server',475<=r.json()['remaining_seconds']<=480)
r=client.post('/api/violations',headers=sh,json={'violation_type':'TAB_SWITCH','captured_at':datetime.now(timezone.utc).isoformat()})
check('V01','Nhận sự kiện không cần ảnh',r.status_code==201,r.text)
with SessionLocal() as db:
 v=db.query(Violation).first();linked=v.exam_id==eid and v.enrollment_id==nid and v.student_id=='SV-00000001'
check('V02','Sự kiện gắn đúng đề và ghi danh',linked)
check('V03','Từ chối danh tính chèn trong payload',client.post('/api/violations',headers=sh,json={'student_id':'SV-00000999','violation_type':'NO_FACE','captured_at':datetime.now(timezone.utc).isoformat()}).status_code==422)
check('V04','Từ chối nhãn không hợp lệ',client.post('/api/violations',headers=sh,json={'violation_type':'UNKNOWN','captured_at':datetime.now(timezone.utc).isoformat()}).status_code==400)
check('V05','Từ chối thời điểm lệch quá 5 phút',client.post('/api/violations',headers=sh,json={'violation_type':'NO_FACE','captured_at':(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()}).status_code==400)
check('V06','Ảnh yêu cầu phiên giảng viên',client.get('/api/snapshots/SV-00000001/missing.jpg').status_code==401)
with SessionLocal() as db:
 x=db.query(ExamStart).first();x.started_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=630);db.commit()
check('T05','Từ chối nộp quá thời lượng và ân hạn',client.post('/api/exams/code/FINAL/submit',headers=sh,json={'answers':[]}).status_code==403)
with SessionLocal() as db:
 x=db.query(ExamStart).first();x.started_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=605);db.commit()
payload={'answers':[{'question_id':q['id'],'selected_option':'A'} for q in qs]}
r=client.post('/api/exams/code/FINAL/submit',headers=sh,json=payload)
check('T06','Nhận bài trong ân hạn 15 giây',r.status_code==200,r.text)
check('G01','Chấm một trong hai câu đúng bằng 5 điểm',r.json()['total_score']==5 and r.json()['correct_count']==1)
check('G02','Chặn nộp bài trùng',client.post('/api/exams/code/FINAL/submit',headers=sh,json=payload).status_code==409)
r=client.get(base+'/export',headers=h)
w=load_workbook(io.BytesIO(r.content));check('G03','Xuất workbook Excel đọc được',r.status_code==200 and w.active.max_row>=2)
check('G04','Không xóa đề đã có bài nộp',client.delete(base,headers=h).status_code in (400,409))
n2,rh2=enroll('SV-00000002');client.post(base+f'/enrollments/{n2}/approve',headers=h)
s2={'X-Exam-Session':client.get('/api/exams/join-request/status',headers=rh2).json()['exam_session_token']}
client.post('/api/exams/code/FINAL/start',headers=s2)
with SessionLocal() as db:
 e=db.get(Exam,eid);e.end_time=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=2);db.commit()
check('T07','Giờ đóng đề giới hạn hạn nộp',client.post('/api/exams/code/FINAL/submit',headers=s2,json={'answers':[]}).status_code==403)
client.post(base+f'/enrollments/{n2}/revoke',headers=h)
check('S06','Phiên bị thu hồi không lấy được đề',client.get('/api/exams/code/FINAL/take',headers=s2).status_code==403)
r=client.post(base+'/close',headers=h);check('E05','Đóng đề chuyển trạng thái CLOSED',r.status_code==200 and r.json()['status']=='CLOSED')
client.post('/api/auth/teacher/logout',headers=h)
check('A04','Đăng xuất vô hiệu hóa token',client.get('/api/auth/teacher/me',headers=h).status_code==401)
print(f'PASS {len(results)}/{len(results)} checks. Temporary source-only backend; no original DB access.')
