from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os, re, secrets
import pytesseract
from PIL import Image
import pdfplumber
from docx import Document
from datetime import timedelta

# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "supersecretkey"  # change for real deployments
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blood_analyzer.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.permanent_session_lifetime = timedelta(days=7)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---------------- DATABASE MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    reports = db.relationship('Report', backref='user', lazy=True, cascade="all, delete-orphan")

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symptoms = db.Column(db.Text)
    filename = db.Column(db.String(255))
    doctor_recommendation = db.Column(db.String(255))

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)      # hashed password
    plain_password = db.Column(db.String(200), nullable=True) # plaintext stored (INSECURE)

# ---------------- CREATE DB & DEFAULT ADMIN ----------------
with app.app_context():
    db.create_all()
    admin_email = "admin@example.com"
    admin_password = "admin123"
    if not Admin.query.filter_by(email=admin_email).first():
        hashed_password = generate_password_hash(admin_password)
        new_admin = Admin(email=admin_email, password=hashed_password, plain_password=admin_password)
        db.session.add(new_admin)
        db.session.commit()
        print(f"Default admin created! Email: {admin_email}, Password: {admin_password}")
    else:
        print("Admin already exists.")

# ---------------- REFERENCE DATA ----------------
# ---------------- REFERENCE DATA ----------------
reference_ranges = {
    'hemoglobin': {'min': 13.5, 'max': 17.5, 'unit': 'g/dL', 'explanation': 'Low hemoglobin may indicate anemia.'},
    'rbc': {'min': 4.7, 'max': 6.1, 'unit': 'million cells/mcL', 'explanation': 'Abnormal RBC count may suggest anemia or polycythemia.'},
    'wbc': {'min': 4500, 'max': 11000, 'unit': 'cells/mcL', 'explanation': 'High WBC can indicate infection or inflammation.'},
    'platelets': {'min': 150000, 'max': 450000, 'unit': 'platelets/mcL', 'explanation': 'Low platelets may lead to bleeding problems.'},
    'glucose': {'min': 70, 'max': 100, 'unit': 'mg/dL', 'explanation': 'High glucose levels can indicate diabetes.'},
    'cholesterol_total': {'min': 125, 'max': 200, 'unit': 'mg/dL', 'explanation': 'High cholesterol increases risk of heart disease.'},
    'hdl': {'min': 40, 'max': 60, 'unit': 'mg/dL', 'explanation': 'Low HDL can increase heart disease risk.'},
    'ldl': {'min': 0, 'max': 100, 'unit': 'mg/dL', 'explanation': 'High LDL is bad for cardiovascular health.'},
    'triglycerides': {'min': 0, 'max': 150, 'unit': 'mg/dL', 'explanation': 'High triglycerides may increase heart disease risk.'},
    'creatinine': {'min': 0.6, 'max': 1.3, 'unit': 'mg/dL', 'explanation': 'Abnormal creatinine may indicate kidney issues.'},
    'urea': {'min': 7, 'max': 20, 'unit': 'mg/dL', 'explanation': 'High urea may indicate kidney dysfunction.'},
    'bilirubin_total': {'min': 0.3, 'max': 1.2, 'unit': 'mg/dL', 'explanation': 'High bilirubin can indicate liver issues.'},
    'ast': {'min': 10, 'max': 40, 'unit': 'U/L', 'explanation': 'High AST may indicate liver damage.'},
    'alt': {'min': 7, 'max': 56, 'unit': 'U/L', 'explanation': 'High ALT may indicate liver damage.'},
    'vitamin_b12': {'min': 200, 'max': 900, 'unit': 'pg/mL', 'explanation': 'Low B12 can lead to fatigue and anemia.'},
    'vitamin_d': {'min': 30, 'max': 100, 'unit': 'ng/mL', 'explanation': 'Low vitamin D may cause bone issues.'},
    'thyroid_tsh': {'min': 0.4, 'max': 4.0, 'unit': 'mIU/L', 'explanation': 'High TSH may indicate hypothyroidism.'},
    'thyroid_t3': {'min': 80, 'max': 200, 'unit': 'ng/dL', 'explanation': 'Abnormal T3 may indicate thyroid disorder.'},
    'thyroid_t4': {'min': 5, 'max': 12, 'unit': 'µg/dL', 'explanation': 'Abnormal T4 may indicate thyroid disorder.'},
    'crp': {'min': 0, 'max': 10, 'unit': 'mg/L', 'explanation': 'High CRP may indicate inflammation or infection.'},
}

# ---------------- SYMPTOMS TO TESTS ----------------
symptom_to_tests = {
    'fatigue': ['Complete Blood Count (CBC)', 'Thyroid Function Test', 'Vitamin B12 Test', 'Vitamin D Test', 'CRP Test'],
    'fever': ['CBC', 'Blood Culture', 'Malaria Test', 'CRP Test'],
    'weight loss': ['Thyroid Function Test', 'Glucose Test', 'CBC', 'Vitamin B12 Test'],
    'weakness': ['CBC', 'Iron Test', 'Vitamin B12 Test', 'Thyroid Function Test'],
    'headache': ['Blood Pressure Test', 'CBC', 'Glucose Test'],
    'joint pain': ['CRP Test', 'Rheumatoid Factor', 'Uric Acid Test'],
    'yellowing of eyes': ['Liver Function Test', 'Bilirubin Test', 'AST', 'ALT'],
    'swelling': ['Kidney Function Test', 'Creatinine', 'Urea', 'Electrolytes Test'],
    'high cholesterol': ['Lipid Profile', 'Cholesterol Test', 'HDL', 'LDL', 'Triglycerides'],
    'diabetes risk': ['Glucose Test', 'HbA1c Test', 'Insulin Test'],
    'shortness of breath': ['CBC', 'Chest X-ray', 'Oxygen Saturation', 'Electrolytes Test'],
    'palpitations': ['ECG', 'CBC', 'Thyroid Function Test', 'Electrolytes Test'],
    'dizziness': ['CBC', 'Blood Pressure Test', 'Glucose Test', 'Electrolytes Test'],
    'nausea': ['Liver Function Test', 'Renal Function Test', 'Electrolytes Test'],
    'vomiting': ['CBC', 'Liver Function Test', 'Renal Function Test', 'Electrolytes Test'],
    'abdominal pain': ['Liver Function Test', 'Ultrasound Abdomen', 'Amylase', 'Lipase'],
    'diarrhea': ['CBC', 'Stool Culture', 'Electrolytes Test'],
    'constipation': ['CBC', 'Thyroid Function Test', 'Vitamin D Test'],
    'blurred vision': ['Blood Glucose Test', 'CBC', 'Eye Exam', 'Blood Pressure Test'],
    'cold hands and feet': ['CBC', 'Iron Test', 'Vitamin B12 Test', 'Thyroid Function Test'],
    'sleep disturbances': ['Thyroid Function Test', 'Vitamin D Test', 'CBC', 'CRP Test'],
    'anxiety': ['Thyroid Function Test', 'CBC', 'Vitamin B12 Test', 'Electrolytes Test'],
    'depression': ['Vitamin D Test', 'CBC', 'Thyroid Function Test', 'Vitamin B12 Test'],
    'hair loss': ['Thyroid Function Test', 'Iron Test', 'Vitamin D Test', 'Vitamin B12 Test'],
    'skin rash': ['CBC', 'Allergy Test', 'CRP Test', 'Liver Function Test'],
    'itching': ['Liver Function Test', 'Allergy Test', 'CBC', 'Renal Function Test'],
    'easy bruising': ['Platelet Count', 'CBC', 'Vitamin K Test', 'Coagulation Profile'],
    'bleeding gums': ['Platelet Count', 'CBC', 'Vitamin K Test', 'Coagulation Profile'],
    'frequent infections': ['WBC Count', 'CBC', 'Immunoglobulin Test', 'Vitamin D Test'],
    'slow wound healing': ['Glucose Test', 'CBC', 'Vitamin C Test', 'HbA1c Test'],
    'chest pain': ['ECG', 'Cardiac Enzymes', 'CBC', 'Lipid Profile'],
    'high blood pressure': ['Blood Pressure Test', 'Electrolytes Test', 'CBC', 'Renal Function Test'],
    'low blood pressure': ['CBC', 'Electrolytes Test', 'Renal Function Test', 'Glucose Test'],
    'frequent urination': ['Glucose Test', 'Renal Function Test', 'CBC', 'Urinalysis'],
    'thirst': ['Glucose Test', 'CBC', 'Electrolytes Test', 'Renal Function Test'],
    'back pain': ['CBC', 'Renal Function Test', 'CRP Test', 'X-ray Spine'],
    'muscle cramps': ['Electrolytes Test', 'CBC', 'Vitamin D Test', 'Magnesium Test'],
    'numbness': ['CBC', 'Vitamin B12 Test', 'Electrolytes Test', 'Thyroid Function Test'],
    'tingling': ['CBC', 'Vitamin B12 Test', 'Electrolytes Test', 'Thyroid Function Test'],
    'swollen lymph nodes': ['CBC', 'Blood Culture', 'CRP Test', 'Ultrasound'],
    'loss of appetite': ['CBC', 'Liver Function Test', 'Thyroid Function Test', 'Vitamin B12 Test'],
    'vomiting blood': ['CBC', 'Coagulation Profile', 'Liver Function Test', 'Endoscopy'],
    'blood in stool': ['CBC', 'Coagulation Profile', 'Stool Occult Blood Test', 'Colonoscopy'],
    'abnormal bleeding': ['CBC', 'Coagulation Profile', 'Platelet Count', 'Vitamin K Test'],
    'weight gain': ['Thyroid Function Test', 'CBC', 'Lipid Profile', 'Glucose Test'],
    'hair thinning': ['Thyroid Function Test', 'Iron Test', 'Vitamin B12 Test', 'Vitamin D Test'],
    'cold intolerance': ['Thyroid Function Test', 'CBC', 'Vitamin D Test', 'Iron Test'],
    'heat intolerance': ['Thyroid Function Test', 'CBC', 'Glucose Test', 'Electrolytes Test'],
    'brittle nails': ['Iron Test', 'Vitamin B12 Test', 'Zinc Test', 'CBC'],
    'mouth ulcers': ['CBC', 'Vitamin B12 Test', 'Folate Test', 'Iron Test'],
    'frequent headaches': ['Blood Pressure Test', 'CBC', 'Glucose Test', 'Thyroid Function Test'],
    'brain fog': ['Vitamin B12 Test', 'Thyroid Function Test', 'CBC', 'Glucose Test'],
    'cold sores': ['CBC', 'Viral PCR', 'Vitamin D Test'],
    'joint stiffness': ['CRP Test', 'Rheumatoid Factor', 'Uric Acid Test', 'X-ray Joint'],
    'swollen feet': ['Renal Function Test', 'CBC', 'Electrolytes Test', 'Liver Function Test'],
    'chronic cough': ['CBC', 'Chest X-ray', 'Sputum Culture', 'CRP Test'],
    'short-term memory loss': ['Vitamin B12 Test', 'Thyroid Function Test', 'CBC', 'Glucose Test'],
    'difficulty concentrating': ['Vitamin B12 Test', 'Thyroid Function Test', 'CBC', 'Glucose Test'],
    'frequent colds': ['WBC Count', 'CBC', 'Vitamin D Test', 'Immunoglobulin Test'],
    'swelling around eyes': ['Renal Function Test', 'CBC', 'Electrolytes Test', 'Liver Function Test'],
    'dark urine': ['Liver Function Test', 'Renal Function Test', 'CBC', 'Bilirubin Test'],
    'pale skin': ['CBC', 'Iron Test', 'Vitamin B12 Test', 'Folate Test'],
    'yellow skin': ['Liver Function Test', 'Bilirubin Test', 'AST', 'ALT'],
    'abdominal bloating': ['Liver Function Test', 'CBC', 'Ultrasound Abdomen', 'Amylase', 'Lipase'],
    'acid reflux': ['CBC', 'Liver Function Test', 'Endoscopy', 'H. Pylori Test'],
    'heartburn': ['CBC', 'Liver Function Test', 'Endoscopy', 'H. Pylori Test'],
    'difficulty swallowing': ['CBC', 'Endoscopy', 'Thyroid Function Test', 'Liver Function Test'],
    'persistent diarrhea': ['CBC', 'Stool Culture', 'Electrolytes Test', 'CBC'],
    'persistent constipation': ['CBC', 'Thyroid Function Test', 'Vitamin D Test', 'CBC'],
    'excessive sweating': ['CBC', 'Thyroid Function Test', 'Electrolytes Test', 'Glucose Test'],
    'slow reflexes': ['Vitamin B12 Test', 'Electrolytes Test', 'CBC', 'Thyroid Function Test'],
    'poor coordination': ['Vitamin B12 Test', 'Electrolytes Test', 'CBC', 'Thyroid Function Test'],
    'difficulty walking': ['Vitamin B12 Test', 'Electrolytes Test', 'CBC', 'MRI Spine'],
    'persistent cough': ['CBC', 'Chest X-ray', 'Sputum Culture', 'CRP Test'],
    'hoarseness': ['CBC', 'Thyroid Function Test', 'Liver Function Test', 'Endoscopy'],
    'swollen tongue': ['CBC', 'Vitamin B12 Test', 'Iron Test', 'Folate Test'],
    'dry skin': ['Vitamin D Test', 'Thyroid Function Test', 'CBC', 'Iron Test'],
    'itchy eyes': ['Allergy Test', 'CBC', 'Vitamin D Test', 'CRP Test'],
    'blurred vision at night': ['Glucose Test', 'CBC', 'Vitamin A Test', 'Eye Exam'],
    'tremors': ['Thyroid Function Test', 'CBC', 'Electrolytes Test', 'Vitamin B12 Test'],
    'muscle weakness': ['Electrolytes Test', 'CBC', 'Vitamin D Test', 'Magnesium Test'],
    'muscle pain': ['Electrolytes Test', 'CBC', 'Vitamin D Test', 'CRP Test'],
    'frequent urination at night': ['Glucose Test', 'CBC', 'Renal Function Test', 'Urinalysis'],
    'snoring': ['CBC', 'Sleep Study', 'Electrolytes Test', 'Glucose Test'],
    'dry mouth': ['CBC', 'Glucose Test', 'Renal Function Test', 'Electrolytes Test'],
    'thirsty all the time': ['Glucose Test', 'CBC', 'Renal Function Test', 'Electrolytes Test'],
    'weight fluctuation': ['Thyroid Function Test', 'CBC', 'Glucose Test', 'Lipid Profile'],
    'frequent mood swings': ['Thyroid Function Test', 'CBC', 'Vitamin D Test', 'Vitamin B12 Test'],
    'nervousness': ['Thyroid Function Test', 'CBC', 'Electrolytes Test', 'Vitamin B12 Test'],
    'rapid heartbeat': ['ECG', 'Thyroid Function Test', 'CBC', 'Electrolytes Test'],
    'slow heartbeat': ['ECG', 'Thyroid Function Test', 'CBC', 'Electrolytes Test'],
    'cold sweat': ['CBC', 'Glucose Test', 'ECG', 'Electrolytes Test'],
    'chest tightness': ['ECG', 'CBC', 'Cardiac Enzymes', 'Lipid Profile'],
    'fainting': ['CBC', 'Glucose Test', 'ECG', 'Electrolytes Test'],
    'nosebleeds': ['CBC', 'Platelet Count', 'Coagulation Profile', 'Vitamin K Test'],
    'cough with blood': ['CBC', 'Chest X-ray', 'Sputum Culture', 'Coagulation Profile'],
    'shortness of breath on exertion': ['CBC', 'Oxygen Saturation', 'ECG', 'Lipid Profile'],
    'leg cramps at night': ['Electrolytes Test', 'Vitamin D Test', 'CBC', 'Magnesium Test'],
    'foot ulcers': ['Glucose Test', 'CBC', 'Renal Function Test', 'Vitamin C Test'],
    'swollen joints': ['CRP Test', 'Rheumatoid Factor', 'Uric Acid Test', 'X-ray Joint'],
    'difficulty climbing stairs': ['Vitamin D Test', 'CBC', 'Electrolytes Test', 'Thyroid Function Test'],
    'frequent thirst': ['Glucose Test', 'CBC', 'Renal Function Test', 'Electrolytes Test'],
    'dark circles under eyes': ['CBC', 'Iron Test', 'Vitamin B12 Test', 'Vitamin D Test'],
    'pale lips': ['CBC', 'Iron Test', 'Vitamin B12 Test', 'Folate Test'],
}




doctor_mapping = {
    'Hematologist': ['hemoglobin', 'rbc', 'wbc', 'platelets', 'vitamin_b12', 'iron'],
    'Endocrinologist': ['glucose', 'thyroid_tsh', 'thyroid_t3', 'thyroid_t4', 'vitamin_d', 'insulin'],
    'Cardiologist': ['cholesterol_total', 'hdl', 'ldl', 'triglycerides', 'blood_pressure'],
    'Nephrologist': ['creatinine', 'urea', 'electrolytes', 'urine_protein'],
    'Hepatologist': ['bilirubin_total', 'ast', 'alt', 'alp'],
    'Rheumatologist': ['crp', 'rheumatoid_factor', 'uric_acid'],
    'General Physician': ['cbc', 'vitamin_d', 'urinalysis', 'glucose'],
}

# ---------------- UTILS ----------------
def extract_text_from_file(filepath):
    text = ''
    if filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
        try:
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)
        except Exception:
            text = ''
    elif filepath.lower().endswith('.pdf'):
        try:
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + '\n'
        except Exception:
            text = ''
    elif filepath.lower().endswith(('.doc', '.docx')):
        try:
            doc = Document(filepath)
            for para in doc.paragraphs:
                text += para.text + '\n'
        except Exception:
            text = ''
    elif filepath.lower().endswith('.txt'):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception:
            text = ''
    return text.lower()

def analyze_blood_report(text):
    analysis = []
    for param, details in reference_ranges.items():
        pattern = rf"{param}[:\s]*([0-9]*\.?[0-9]+)"
        match = re.search(pattern, text)
        if match:
            try:
                value = float(match.group(1))
            except:
                continue
            if value < details['min']:
                status = 'Abnormal'
                explanation = f"Low {param}: may indicate {details['explanation']}"
            elif value > details['max']:
                status = 'Abnormal'
                explanation = details['explanation']
            else:
                status = 'Normal'
                explanation = 'Within normal range.'
            analysis.append({
                'parameter': param,
                'value': value,
                'unit': details['unit'],
                'status': status,
                'explanation': explanation
            })
    return analysis

# ---------------- AUTH ROUTES ----------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for('signup'))
        new_user = User(username=username, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        flash("Signup successful. Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session.permanent = True
            return redirect(url_for('index'))
        flash("Invalid credentials.", "danger")
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            session['admin_email'] = admin.email
            return redirect(url_for('admin_panel'))
        flash("Invalid admin credentials.", "danger")
        return redirect(url_for('admin_login'))
    return render_template('admin_login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

# ---------------- MAIN PAGES ----------------
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session.get('username'))

@app.route('/recommend-tests', methods=['POST'])
def recommend_tests():
    data = request.json or {}
    symptoms = data.get('symptoms', '').lower()
    recommended = set()
    for keyword, tests in symptom_to_tests.items():
        if keyword in symptoms:
            recommended.update(tests)
    return jsonify({'recommended_tests': list(recommended)})

@app.route('/upload-report', methods=['POST'])
def upload_report():
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401

    file = request.files.get('report-file')
    symptoms = request.form.get('symptoms', '')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    safe_name = f"user_{session['user_id']}_{secrets.token_hex(6)}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    file.save(filepath)

    text = extract_text_from_file(filepath)
    analysis = analyze_blood_report(text)

    abnormal = [item['parameter'] for item in analysis if item['status'] == 'Abnormal']
    recommended_doctors = {doc for doc, params in doctor_mapping.items() if any(p in params for p in abnormal)}
    doctor_recommendation = ", ".join(recommended_doctors) if recommended_doctors else "All parameters normal."

    new_report = Report(user_id=session['user_id'], symptoms=symptoms, filename=safe_name, doctor_recommendation=doctor_recommendation)
    db.session.add(new_report)
    db.session.commit()

    return jsonify({'analysis': analysis, 'doctor_recommendation': doctor_recommendation})

# ---------------- ADMIN PANEL ----------------
@app.route('/admin')
def admin_panel():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    users = User.query.all()
    reports = Report.query.all()
    admins = Admin.query.all()
    return render_template('admin.html', users=users, reports=reports, admins=admins)

@app.route('/create-admin', methods=['GET', 'POST'])
def create_admin():
    # Regular admin creates new admin
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        if Admin.query.filter_by(email=email).first():
            flash("Admin with this email already exists.", "danger")
            return redirect(url_for('create_admin'))
        hashed_password = generate_password_hash(password)
        new_admin = Admin(email=email, password=hashed_password, plain_password=password)
        db.session.add(new_admin)
        db.session.commit()
        flash("Admin created.", "success")
        return redirect(url_for('admin_panel'))
    return render_template('create_admin.html')

@app.route('/download/<filename>')
def download_report(filename):
    if 'user_id' not in session and 'admin_id' not in session:
        return redirect(url_for('login'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

# ---------------- ADMIN ACTIONS ----------------
@app.route('/admin/delete-report/<int:report_id>', methods=['POST'])
def admin_delete_report(report_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    r = Report.query.get_or_404(report_id)
    if r.filename:
        path = os.path.join(app.config['UPLOAD_FOLDER'], r.filename)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(r)
    db.session.commit()
    flash("Report deleted successfully.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    u = User.query.get_or_404(user_id)
    for r in list(u.reports):
        if r.filename:
            path = os.path.join(app.config['UPLOAD_FOLDER'], r.filename)
            if os.path.exists(path):
                os.remove(path)
    db.session.delete(u)
    db.session.commit()
    flash("User and all their reports deleted successfully.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/admin/reset-password/<int:user_id>', methods=['POST'])
def admin_reset_password(user_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    u = User.query.get_or_404(user_id)
    temp_password = secrets.token_urlsafe(8)
    u.password = generate_password_hash(temp_password)
    # We do not store user's plain password (only admins will be stored plain below)
    db.session.commit()
    flash(f"Temporary password for {u.email}: {temp_password}", "success")
    return redirect(url_for('admin_panel'))

# ---------------- SUPER-ADMIN (MASTER) ----------------
MASTER_PASSWORD = "supersecure123"  # change to something secret

# Super-admin login page (standalone, no normal admin required)
@app.route('/admin-master-login', methods=['GET', 'POST'])
def admin_master_login():
    if request.method == 'POST':
        mp = request.form.get('master_password', '')
        if mp == MASTER_PASSWORD:
            session['master_verified'] = True
            flash("Super-admin access granted.", "success")
            return redirect(url_for('admin_database'))
        flash("Invalid master password.", "danger")
        return redirect(url_for('admin_master_login'))

    return render_template('admin_master_login.html')

# Super-admin dashboard
@app.route('/admin-database', methods=['GET'])
def admin_database():
    if not session.get('master_verified'):
        return redirect(url_for('admin_master_login'))

    admins = Admin.query.all()
    return render_template('admin_database.html', admins=admins)

# ---------------- SUPER-ADMIN ACTIONS ----------------
@app.route('/super/create-admin', methods=['POST'])
def super_create_admin():
    if not session.get('master_verified'):
        return redirect(url_for('admin_master_login'))

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    if not email or not password:
        flash("Email and password required.", "danger")
        return redirect(url_for('admin_database'))

    if Admin.query.filter_by(email=email).first():
        flash("Admin already exists.", "danger")
        return redirect(url_for('admin_database'))

    hashed = generate_password_hash(password)
    a = Admin(email=email, password=hashed, plain_password=password)
    db.session.add(a)
    db.session.commit()
    flash(f"Admin created: {email} — plaintext shown once here.", "success")
    return redirect(url_for('admin_database'))

@app.route('/super/delete-admin/<int:admin_id>', methods=['POST'])
def super_delete_admin(admin_id):
    if not session.get('master_verified'):
        return redirect(url_for('admin_master_login'))

    a = Admin.query.get_or_404(admin_id)
    db.session.delete(a)
    db.session.commit()
    flash(f"Admin {a.email} deleted.", "success")
    return redirect(url_for('admin_database'))

@app.route('/super/reset-admin-password/<int:admin_id>', methods=['POST'])
def super_reset_admin_password(admin_id):
    if not session.get('master_verified'):
        return redirect(url_for('admin_master_login'))

    a = Admin.query.get_or_404(admin_id)
    temp_password = secrets.token_urlsafe(8)
    a.password = generate_password_hash(temp_password)
    a.plain_password = temp_password  # store plaintext (INSECURE)
    db.session.commit()
    flash(f"Temporary password for {a.email}: {temp_password}", "success")
    return redirect(url_for('admin_database'))

@app.route('/super/logout-master', methods=['POST'])
def super_logout_master():
    session.pop('master_verified', None)
    flash("Super-admin session ended.", "info")
    return redirect(url_for('admin_master_login'))


# ---------------- RUN APP ----------------
if __name__ == '__main__':
    app.run(debug=True) 