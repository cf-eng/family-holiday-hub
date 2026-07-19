import csv, io, json, os, secrets
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, make_response, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
BASE_DIR=Path(__file__).resolve().parent
UPLOAD_DIR=BASE_DIR/'uploads'; UPLOAD_DIR.mkdir(exist_ok=True)
app=Flask(__name__)
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32),SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL','sqlite:///holiday_hub.db'),SQLALCHEMY_TRACK_MODIFICATIONS=False,MAX_CONTENT_LENGTH=int(os.getenv('MAX_UPLOAD_MB','12'))*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true')
db=SQLAlchemy(app); csrf=CSRFProtect(app); login_manager=LoginManager(app); login_manager.login_view='login'
ALLOWED_EXTENSIONS={'pdf','png','jpg','jpeg','webp','txt'}
CATEGORIES=['flight','transport','hotel','food','beach','activity','shopping','kids','golf','emergency','other']
ICONS={'flight':'✈','transport':'🚗','hotel':'🏨','food':'🍽','beach':'🏖','activity':'🎟','shopping':'🛍','kids':'🎈','golf':'⛳','emergency':'✚','other':'📍'}

def clean(v,n=500): return ' '.join((v or '').strip().split())[:n]
def ffloat(v,default=0):
    try:return float(v or default)
    except:return default
def fdate(v,default=None):
    try:return datetime.strptime(v,'%Y-%m-%d').date()
    except:return default
def ftime(v):
    try:return datetime.strptime(v,'%H:%M').time()
    except:return None
def valid_url(v):
    if not v:return False
    p=urlparse(v); return p.scheme in {'http','https'} and bool(p.netloc)

class User(UserMixin,db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(80),nullable=False); email=db.Column(db.String(254),unique=True,nullable=False,index=True); password_hash=db.Column(db.String(255),nullable=False)
    memberships=db.relationship('TripMember',back_populates='user',cascade='all, delete-orphan')
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)
class Trip(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(120),nullable=False); destination=db.Column(db.String(120),nullable=False); start_date=db.Column(db.Date,nullable=False); end_date=db.Column(db.Date,nullable=False)
    header_url=db.Column(db.String(600),nullable=False,default=''); origin=db.Column(db.String(120),default='Dublin'); origin_lat=db.Column(db.Float,default=53.3498); origin_lng=db.Column(db.Float,default=-6.2603); destination_lat=db.Column(db.Float,default=39.5696); destination_lng=db.Column(db.Float,default=2.6502)
    currency=db.Column(db.String(8),default='EUR'); budget=db.Column(db.Float,default=0); accommodation=db.Column(db.String(180),default=''); wifi=db.Column(db.String(120),default=''); emergency_number=db.Column(db.String(60),default='112'); hospital=db.Column(db.String(180),default=''); taxi=db.Column(db.String(120),default=''); embassy=db.Column(db.String(180),default=''); spotify_url=db.Column(db.String(600),default=''); door_code=db.Column(db.String(80),default='')
    members=db.relationship('TripMember',back_populates='trip',cascade='all, delete-orphan'); people=db.relationship('FamilyMember',back_populates='trip',cascade='all, delete-orphan'); events=db.relationship('Event',back_populates='trip',cascade='all, delete-orphan'); packing_items=db.relationship('PackingItem',back_populates='trip',cascade='all, delete-orphan'); expenses=db.relationship('Expense',back_populates='trip',cascade='all, delete-orphan'); documents=db.relationship('Document',back_populates='trip',cascade='all, delete-orphan'); notes=db.relationship('Note',back_populates='trip',cascade='all, delete-orphan')
class TripMember(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); role=db.Column(db.String(20),default='member'); trip=db.relationship('Trip',back_populates='members'); user=db.relationship('User',back_populates='memberships'); __table_args__=(db.UniqueConstraint('trip_id','user_id'),)
class FamilyMember(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); name=db.Column(db.String(90),nullable=False); member_type=db.Column(db.String(10),default='adult'); age=db.Column(db.Integer); avatar_url=db.Column(db.String(600),default=''); passport_last4=db.Column(db.String(4),default=''); notes=db.Column(db.String(250),default=''); trip=db.relationship('Trip',back_populates='people')
class Event(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); title=db.Column(db.String(140),nullable=False); event_date=db.Column(db.Date,nullable=False); event_time=db.Column(db.Time); end_time=db.Column(db.Time); category=db.Column(db.String(30),default='activity'); location=db.Column(db.String(180),default=''); latitude=db.Column(db.Float); longitude=db.Column(db.Float); confirmation=db.Column(db.String(100),default=''); notes=db.Column(db.Text,default=''); position=db.Column(db.Integer,default=0); status=db.Column(db.String(20),default='planned'); cost=db.Column(db.Float,default=0); booking_url=db.Column(db.String(600),default=''); assigned_to=db.Column(db.String(180),default='Everyone'); rating=db.Column(db.Float,default=0); travel_minutes=db.Column(db.Integer,default=0); weather=db.Column(db.String(80),default=''); temperature=db.Column(db.String(20),default=''); flight_status=db.Column(db.String(40),default=''); gate=db.Column(db.String(20),default=''); trip=db.relationship('Trip',back_populates='events')
class PackingItem(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); label=db.Column(db.String(120),nullable=False); owner=db.Column(db.String(80),default='Everyone'); packed=db.Column(db.Boolean,default=False); trip=db.relationship('Trip',back_populates='packing_items')
class Expense(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); label=db.Column(db.String(120),nullable=False); amount=db.Column(db.Float,nullable=False); category=db.Column(db.String(40),default='Other'); paid_by=db.Column(db.String(80),default=''); spent_on=db.Column(db.Date,default=date.today); trip=db.relationship('Trip',back_populates='expenses')
class Document(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); title=db.Column(db.String(120),nullable=False); doc_type=db.Column(db.String(30),default='Other'); stored_name=db.Column(db.String(220),nullable=False); original_name=db.Column(db.String(220),nullable=False); uploaded_at=db.Column(db.DateTime,default=datetime.utcnow); trip=db.relationship('Trip',back_populates='documents')
class Note(db.Model):
    id=db.Column(db.Integer,primary_key=True); trip_id=db.Column(db.Integer,db.ForeignKey('trip.id'),nullable=False); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); body=db.Column(db.String(500),nullable=False); created_at=db.Column(db.DateTime,default=datetime.utcnow); trip=db.relationship('Trip',back_populates='notes'); user=db.relationship('User')
@login_manager.user_loader
def load_user(uid):return db.session.get(User,int(uid))
def member(trip_id):return TripMember.query.filter_by(trip_id=trip_id,user_id=current_user.id).first()
def access(owner=False):
    def dec(fn):
        @wraps(fn)
        @login_required
        def wrap(trip_id,*a,**k):
            m=member(trip_id); t=db.session.get(Trip,trip_id)
            if not t:abort(404)
            if not m or owner and m.role!='owner':abort(403)
            return fn(t,m,*a,**k)
        return wrap
    return dec
@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff'; r.headers['X-Frame-Options']='DENY'; r.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    r.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    return r
@app.context_processor
def helpers():return {'ICONS':ICONS,'CATEGORIES':CATEGORIES,'today':date.today()}
@app.route('/')
def landing():return redirect(url_for('dashboard')) if current_user.is_authenticated else render_template('landing.html')
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=clean(request.form.get('name'),80); email=clean(request.form.get('email'),254).lower(); p=request.form.get('password','')
        if not name or '@' not in email or len(p)<10: flash('Use a valid email and a password of at least 10 characters.','error')
        elif User.query.filter_by(email=email).first(): flash('That email is already registered.','error')
        else:
            u=User(name=name,email=email);u.set_password(p);db.session.add(u);db.session.commit();login_user(u);return redirect(url_for('dashboard'))
    return render_template('auth.html',mode='register')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=User.query.filter_by(email=clean(request.form.get('email'),254).lower()).first()
        if u and u.check_password(request.form.get('password','')):login_user(u,remember=True);return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','error')
    return render_template('auth.html',mode='login')
@app.route('/logout')
@login_required
def logout():logout_user();return redirect(url_for('landing'))
@app.route('/dashboard')
@login_required
def dashboard():
    ms=TripMember.query.filter_by(user_id=current_user.id).all(); trips=[m.trip for m in ms]
    trips.sort(key=lambda t:t.start_date)
    return render_template('dashboard.html',trips=trips)
@app.route('/trips/new',methods=['GET','POST'])
@login_required
def new_trip():
    if request.method=='POST':
        s=fdate(request.form.get('start_date'));e=fdate(request.form.get('end_date'));url=clean(request.form.get('header_url'),600)
        if not s or not e or e<s or not valid_url(url):flash('Add valid dates and a full HTTPS photo header URL.','error')
        else:
            t=Trip(name=clean(request.form.get('name'),120),destination=clean(request.form.get('destination'),120),start_date=s,end_date=e,header_url=url,origin=clean(request.form.get('origin'),120) or 'Dublin',origin_lat=ffloat(request.form.get('origin_lat'),53.3498),origin_lng=ffloat(request.form.get('origin_lng'),-6.2603),destination_lat=ffloat(request.form.get('destination_lat'),39.5696),destination_lng=ffloat(request.form.get('destination_lng'),2.6502),budget=ffloat(request.form.get('budget')),currency=clean(request.form.get('currency'),8) or 'EUR')
            db.session.add(t);db.session.flush();db.session.add(TripMember(trip=t,user=current_user,role='owner'));db.session.add(FamilyMember(trip=t,name=current_user.name,member_type='adult'));db.session.commit();return redirect(url_for('trip_home',trip_id=t.id))
    return render_template('trip_form.html')
def stats(t):
    spent=sum(x.amount for x in t.expenses); packed=sum(1 for x in t.packing_items if x.packed); total=len(t.packing_items); now=date.today(); countdown=(t.start_date-now).days; day=max(1,(now-t.start_date).days+1) if t.start_date<=now<=t.end_date else None
    return dict(spent=spent,remaining=t.budget-spent,packed=packed,packing_total=total,packing_pct=round(packed/total*100) if total else 0,countdown=countdown,day=day,duration=(t.end_date-t.start_date).days+1)
def warnings_for(t):
    out=[]
    ev=sorted(t.events,key=lambda x:(x.event_date,x.event_time or datetime.min.time(),x.position))
    for a,b in zip(ev,ev[1:]):
        if a.event_date==b.event_date and a.event_time and b.event_time:
            gap=(datetime.combine(a.event_date,b.event_time)-datetime.combine(a.event_date,a.event_time)).total_seconds()/60
            if a.end_time and b.event_time < a.end_time:out.append(f'Overlap: {a.title} and {b.title}.')
            elif b.travel_minutes and gap<b.travel_minutes:out.append(f'Only {int(gap)} minutes before {b.title}; travel needs {b.travel_minutes}.')
    return out[:6]
@app.route('/trips/<int:trip_id>')
@access()
def trip_home(t,m):
    upcoming=sorted([e for e in t.events if e.event_date>=date.today()],key=lambda e:(e.event_date,e.event_time or datetime.min.time()))[:5]
    route_points=[{'name':t.origin,'lat':t.origin_lat,'lng':t.origin_lng},{'name':t.destination,'lat':t.destination_lat,'lng':t.destination_lng}]
    route_points += [{'name':e.location or e.title,'lat':e.latitude,'lng':e.longitude} for e in sorted(t.events,key=lambda e:(e.event_date,e.position)) if e.latitude is not None and e.longitude is not None]
    return render_template('trip_home.html',trip=t,stats=stats(t),upcoming=upcoming,warnings=warnings_for(t),route_points=route_points)
@app.route('/trips/<int:trip_id>/itinerary',methods=['GET','POST'])
@access()
def itinerary(t,m):
    if request.method=='POST':
        ev=Event(trip=t,title=clean(request.form.get('title'),140),event_date=fdate(request.form.get('event_date'),t.start_date),event_time=ftime(request.form.get('event_time')),end_time=ftime(request.form.get('end_time')),category=request.form.get('category','activity'),location=clean(request.form.get('location'),180),latitude=ffloat(request.form.get('latitude'),None) if request.form.get('latitude') else None,longitude=ffloat(request.form.get('longitude'),None) if request.form.get('longitude') else None,confirmation=clean(request.form.get('confirmation'),100),notes=clean(request.form.get('notes'),1000),status=request.form.get('status','planned'),cost=ffloat(request.form.get('cost')),booking_url=clean(request.form.get('booking_url'),600),assigned_to=clean(request.form.get('assigned_to'),180) or 'Everyone',rating=ffloat(request.form.get('rating')),travel_minutes=int(ffloat(request.form.get('travel_minutes'))),weather=clean(request.form.get('weather'),80),temperature=clean(request.form.get('temperature'),20),flight_status=clean(request.form.get('flight_status'),40),gate=clean(request.form.get('gate'),20),position=len(t.events))
        if ev.title:db.session.add(ev);db.session.commit();flash('Activity added.','success')
        return redirect(url_for('itinerary',trip_id=t.id))
    grouped=defaultdict(list)
    for e in sorted(t.events,key=lambda e:(e.event_date,e.position,e.event_time or datetime.min.time())):grouped[e.event_date].append(e)
    return render_template('itinerary.html',trip=t,grouped=dict(grouped),warnings=warnings_for(t))
@app.post('/trips/<int:trip_id>/itinerary/reorder')
@access()
def reorder(t,m):
    data=request.get_json(silent=True) or {}
    for row in data.get('items',[]):
        e=db.session.get(Event,int(row.get('id',0)))
        if e and e.trip_id==t.id:e.position=int(row.get('position',0));e.event_date=fdate(row.get('date'),e.event_date)
    db.session.commit();return jsonify(ok=True)
@app.post('/trips/<int:trip_id>/events/<int:event_id>/delete')
@access()
def delete_event(t,m,event_id):
    e=db.session.get(Event,event_id)
    if not e or e.trip_id!=t.id:abort(404)
    db.session.delete(e);db.session.commit();return redirect(url_for('itinerary',trip_id=t.id))
@app.post('/trips/<int:trip_id>/itinerary/import')
@access()
def import_csv(t,m):
    f=request.files.get('csv_file'); count=0
    if f:
        for r in csv.DictReader(io.StringIO(f.read().decode('utf-8-sig'))):
            d=fdate(r.get('date'))
            if not d or not r.get('title'):continue
            db.session.add(Event(trip=t,title=clean(r.get('title'),140),event_date=d,event_time=ftime(r.get('time')),end_time=ftime(r.get('end_time')),category=clean(r.get('category'),30) or 'activity',location=clean(r.get('location'),180),confirmation=clean(r.get('confirmation'),100),notes=clean(r.get('notes'),1000),cost=ffloat(r.get('cost')),status=clean(r.get('status'),20) or 'planned',booking_url=clean(r.get('booking_url'),600),assigned_to=clean(r.get('assigned_to'),180) or 'Everyone',travel_minutes=int(ffloat(r.get('travel_minutes'))),weather=clean(r.get('weather'),80),temperature=clean(r.get('temperature'),20),position=len(t.events)+count));count+=1
        db.session.commit()
    flash(f'Imported {count} activities.','success');return redirect(url_for('itinerary',trip_id=t.id))
@app.route('/trips/<int:trip_id>/itinerary/export')
@access()
def export_csv(t,m):
    s=io.StringIO();w=csv.writer(s);w.writerow(['date','time','end_time','title','category','location','confirmation','notes','cost','status','booking_url','assigned_to','travel_minutes','weather','temperature'])
    for e in sorted(t.events,key=lambda x:(x.event_date,x.position)):w.writerow([e.event_date,e.event_time.strftime('%H:%M') if e.event_time else '',e.end_time.strftime('%H:%M') if e.end_time else '',e.title,e.category,e.location,e.confirmation,e.notes,e.cost,e.status,e.booking_url,e.assigned_to,e.travel_minutes,e.weather,e.temperature])
    r=make_response(s.getvalue());r.headers['Content-Type']='text/csv';r.headers['Content-Disposition']=f'attachment; filename="{secure_filename(t.name)}-itinerary.csv"';return r
@app.route('/trips/<int:trip_id>/itinerary/print')
@access()
def itinerary_print(t,m):
    grouped=defaultdict(list)
    for e in sorted(t.events,key=lambda e:(e.event_date,e.position,e.event_time or datetime.min.time())):grouped[e.event_date].append(e)
    r=make_response(render_template('itinerary_print.html',trip=t,grouped=dict(grouped),print_date=date.today(),stats=stats(t)));r.headers['Cache-Control']='no-store';return r
@app.route('/trips/<int:trip_id>/overview/print')
@access()
def overview_print(t,m):
    grouped=defaultdict(list)
    for e in sorted(t.events,key=lambda e:(e.event_date,e.position,e.event_time or datetime.min.time())):grouped[e.event_date].append(e)
    return render_template('overview_print.html',trip=t,grouped=dict(grouped),stats=stats(t),warnings=warnings_for(t),print_date=date.today())
@app.route('/trips/<int:trip_id>/family',methods=['GET','POST'])
@access()
def family(t,m):
    if request.method=='POST':
        typ=request.form.get('member_type','adult'); age=None if typ=='adult' else int(ffloat(request.form.get('age')) or 0)
        p=FamilyMember(trip=t,name=clean(request.form.get('name'),90),member_type=typ,age=age,avatar_url=clean(request.form.get('avatar_url'),600),passport_last4=clean(request.form.get('passport_last4'),4),notes=clean(request.form.get('notes'),250))
        if p.name:db.session.add(p);db.session.commit()
        return redirect(url_for('family',trip_id=t.id))
    return render_template('family.html',trip=t)
@app.post('/trips/<int:trip_id>/family/<int:person_id>/delete')
@access(owner=True)
def delete_person(t,m,person_id):
    p=db.session.get(FamilyMember,person_id)
    if not p or p.trip_id!=t.id:abort(404)
    db.session.delete(p);db.session.commit();return redirect(url_for('family',trip_id=t.id))
@app.route('/trips/<int:trip_id>/documents',methods=['GET','POST'])
@access()
def documents(t,m):
    if request.method=='POST':
        f=request.files.get('file')
        if f and '.' in f.filename and f.filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS:
            original=secure_filename(f.filename);stored=f'{secrets.token_hex(12)}-{original}';f.save(UPLOAD_DIR/stored);db.session.add(Document(trip=t,title=clean(request.form.get('title'),120) or original,doc_type=clean(request.form.get('doc_type'),30) or 'Other',stored_name=stored,original_name=original));db.session.commit()
        return redirect(url_for('documents',trip_id=t.id))
    return render_template('documents.html',trip=t)
@app.route('/trips/<int:trip_id>/documents/<int:document_id>')
@access()
def document_file(t,m,document_id):
    d=db.session.get(Document,document_id)
    if not d or d.trip_id!=t.id:abort(404)
    return send_from_directory(UPLOAD_DIR,d.stored_name,as_attachment=False,download_name=d.original_name)
@app.post('/trips/<int:trip_id>/documents/<int:document_id>/delete')
@access()
def delete_document(t,m,document_id):
    d=db.session.get(Document,document_id)
    if not d or d.trip_id!=t.id:abort(404)
    try:(UPLOAD_DIR/d.stored_name).unlink(missing_ok=True)
    except:pass
    db.session.delete(d);db.session.commit();return redirect(url_for('documents',trip_id=t.id))
@app.route('/trips/<int:trip_id>/packing',methods=['GET','POST'])
@access()
def packing(t,m):
    if request.method=='POST':
        db.session.add(PackingItem(trip=t,label=clean(request.form.get('label'),120),owner=clean(request.form.get('owner'),80) or 'Everyone'));db.session.commit();return redirect(url_for('packing',trip_id=t.id))
    return render_template('packing.html',trip=t,stats=stats(t))
@app.post('/trips/<int:trip_id>/packing/<int:item_id>/toggle')
@access()
def toggle_packing(t,m,item_id):
    x=db.session.get(PackingItem,item_id)
    if not x or x.trip_id!=t.id:abort(404)
    x.packed=not x.packed;db.session.commit();return redirect(url_for('packing',trip_id=t.id))
@app.route('/trips/<int:trip_id>/expenses',methods=['GET','POST'])
@access()
def expenses(t,m):
    if request.method=='POST':
        db.session.add(Expense(trip=t,label=clean(request.form.get('label'),120),amount=ffloat(request.form.get('amount')),category=clean(request.form.get('category'),40),paid_by=clean(request.form.get('paid_by'),80),spent_on=fdate(request.form.get('spent_on'),date.today())));db.session.commit();return redirect(url_for('expenses',trip_id=t.id))
    cats=defaultdict(float)
    for x in t.expenses:cats[x.category]+=x.amount
    return render_template('expenses.html',trip=t,stats=stats(t),cats=dict(cats))
@app.route('/trips/<int:trip_id>/settings',methods=['GET','POST'])
@access(owner=True)
def settings(t,m):
    if request.method=='POST':
        for key,n in [('name',120),('destination',120),('header_url',600),('origin',120),('accommodation',180),('wifi',120),('door_code',80),('emergency_number',60),('hospital',180),('taxi',120),('embassy',180),('spotify_url',600)]:setattr(t,key,clean(request.form.get(key),n))
        t.budget=ffloat(request.form.get('budget'));t.origin_lat=ffloat(request.form.get('origin_lat'),t.origin_lat);t.origin_lng=ffloat(request.form.get('origin_lng'),t.origin_lng);t.destination_lat=ffloat(request.form.get('destination_lat'),t.destination_lat);t.destination_lng=ffloat(request.form.get('destination_lng'),t.destination_lng);db.session.commit();flash('Trip updated.','success');return redirect(url_for('settings',trip_id=t.id))
    return render_template('settings.html',trip=t)
@app.errorhandler(403)
def forbidden(e):return render_template('error.html',message='You do not have access to this trip.'),403
@app.errorhandler(404)
def missing(e):return render_template('error.html',message='That page could not be found.'),404
with app.app_context():db.create_all()
if __name__=='__main__':app.run(debug=os.getenv('FLASK_DEBUG','true').lower()=='true')
