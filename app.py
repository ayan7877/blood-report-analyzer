from flask import Flask, request, jsonify, render_template
import os
import re
import pytesseract
from PIL import Image
import pdfplumber
from docx import Document

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Reference ranges for blood parameters
reference_ranges = {
    'hemoglobin': {'min': 13.5, 'max': 17.5, 'unit': 'g/dL', 'explanation': 'Low hemoglobin may indicate anemia.'},
    'rbc': {'min': 4.7, 'max': 6.1, 'unit': 'million cells/mcL', 'explanation': 'Abnormal RBC count may suggest anemia or polycythemia.'},
    'wbc': {'min': 4500, 'max': 11000, 'unit': 'cells/mcL', 'explanation': 'High WBC can indicate infection or inflammation.'},
    'platelets': {'min': 150000, 'max': 450000, 'unit': 'platelets/mcL', 'explanation': 'Low platelets may lead to bleeding problems.'},
    'glucose': {'min': 70, 'max': 100, 'unit': 'mg/dL', 'explanation': 'High glucose levels can indicate diabetes.'},
    'creatinine': {'min': 0.6, 'max': 1.3, 'unit': 'mg/dL', 'explanation': 'High creatinine may suggest kidney dysfunction.'},
    'urea': {'min': 7, 'max': 20, 'unit': 'mg/dL', 'explanation': 'High urea may suggest kidney dysfunction or dehydration.'},
    'bilirubin': {'min': 0.1, 'max': 1.2, 'unit': 'mg/dL', 'explanation': 'High bilirubin may suggest liver dysfunction or hemolysis.'},
    'alt': {'min': 7, 'max': 56, 'unit': 'U/L', 'explanation': 'High ALT may suggest liver injury.'},
    'ast': {'min': 10, 'max': 40, 'unit': 'U/L', 'explanation': 'High AST may suggest liver or muscle damage.'},
    'cholesterol': {'min': 125, 'max': 200, 'unit': 'mg/dL', 'explanation': 'High cholesterol is a risk factor for heart disease.'},
    'triglycerides': {'min': 0, 'max': 150, 'unit': 'mg/dL', 'explanation': 'High triglycerides may suggest metabolic syndrome or heart disease.'},
    'hdl': {'min': 40, 'max': 60, 'unit': 'mg/dL', 'explanation': 'Low HDL increases heart disease risk.'},
    'ldl': {'min': 0, 'max': 130, 'unit': 'mg/dL', 'explanation': 'High LDL increases heart disease risk.'},
    'sodium': {'min': 135, 'max': 145, 'unit': 'mEq/L', 'explanation': 'Abnormal sodium levels may cause dehydration or electrolyte imbalance.'},
    'potassium': {'min': 3.5, 'max': 5.0, 'unit': 'mEq/L', 'explanation': 'Abnormal potassium can cause heart rhythm problems.'},
    'calcium': {'min': 8.5, 'max': 10.2, 'unit': 'mg/dL', 'explanation': 'Low calcium may cause muscle spasms; high may suggest parathyroid disorder.'},
    'phosphate': {'min': 2.5, 'max': 4.5, 'unit': 'mg/dL', 'explanation': 'Abnormal phosphate can affect bone health and kidney function.'},
    'magnesium': {'min': 1.7, 'max': 2.2, 'unit': 'mg/dL', 'explanation': 'Low magnesium can cause muscle cramps and arrhythmias.'},
    'total protein': {'min': 6.0, 'max': 8.3, 'unit': 'g/dL', 'explanation': 'Abnormal protein may suggest liver or kidney disease.'},
    'albumin': {'min': 3.5, 'max': 5.0, 'unit': 'g/dL', 'explanation': 'Low albumin suggests liver/kidney disease or malnutrition.'},
    'crp': {'min': 0, 'max': 10, 'unit': 'mg/L', 'explanation': 'High CRP indicates inflammation or infection.'},
    'vitamin d': {'min': 20, 'max': 50, 'unit': 'ng/mL', 'explanation': 'Low vitamin D may suggest bone disorders or deficiency.'},
    'vitamin b12': {'min': 200, 'max': 900, 'unit': 'pg/mL', 'explanation': 'Low B12 can cause anemia and neurological issues.'},
}

symptom_to_tests = { 'fatigue': ['Complete Blood Count (CBC)', 'Thyroid Function Test', 'Vitamin B12 Test'], 'fever': ['CBC', 'Blood Culture', 'Malaria Test'], 'joint pain': ['Rheumatoid Factor Test', 'CRP Test', 'Uric Acid Test'], 'weight loss': ['Thyroid Function Test', 'HbA1c', 'Liver Function Test'], 'weight gain': ['Thyroid Function Test', 'Lipid Profile'], 'dizziness': ['CBC', 'Iron Studies', 'Vitamin B12 Test'], 'nausea': ['Liver Function Test', 'Amylase Test'], 'vomiting': ['Electrolyte Panel', 'Liver Function Test'], 'blurred vision': ['Blood Sugar Test', 'Thyroid Test'], 'shortness of breath': ['CBC', 'D-Dimer Test', 'Arterial Blood Gas (ABG)'], 'palpitations': ['Thyroid Function Test', 'Electrolyte Panel'], 'swelling': ['Kidney Function Test', 'Liver Function Test', 'Albumin Test'], 'persistent cough': ['CBC', 'Sputum Culture', 'Chest X-Ray (imaging)'], 'skin rash': ['Allergy Panel', 'CBC', 'Autoimmune Panel'], 'abdominal pain': ['Liver Function Test', 'Amylase/Lipase Test', 'CBC'], 'frequent urination': ['Blood Sugar Test', 'Kidney Function Test', 'Electrolyte Panel'], 'thirst': ['Blood Sugar Test', 'Electrolyte Panel'], 'hair loss': ['Thyroid Function Test', 'Vitamin D Test', 'Ferritin Test'], 'memory loss': ['Vitamin B12 Test', 'Thyroid Function Test', 'Electrolyte Panel'], 'muscle weakness': ['Electrolyte Panel', 'Thyroid Function Test', 'Creatinine Kinase (CK) Test'], 'anemia': ['CBC', 'Iron Studies', 'Vitamin B12 Test', 'Folate Test'], 'high blood pressure': ['Kidney Function Test', 'Lipid Profile', 'Electrolyte Panel'], 'low blood pressure': ['CBC', 'Electrolyte Panel', 'Cortisol Test'], 'chest pain': ['Troponin Test', 'Lipid Profile', 'CBC', 'CK-MB Test'], 'swollen lymph nodes': ['CBC', 'Lymph Node Biopsy (not blood test)', 'Viral Panel'], 'loss of appetite': ['Liver Function Test', 'Thyroid Function Test', 'CBC'], 'irregular periods': ['Hormone Panel', 'Thyroid Function Test', 'FSH/LH Test'], 'infertility': ['Hormone Panel', 'Thyroid Function Test', 'Prolactin Test'], 'itching': ['Allergy Panel', 'Liver Function Test', 'Kidney Function Test'], 'joint stiffness': ['Rheumatoid Factor Test', 'CRP Test', 'Anti-CCP Test'], 'blood in urine': ['Urinalysis (not blood test)', 'Kidney Function Test', 'CBC'], 'persistent fatigue': ['CBC', 'Thyroid Function Test', 'Vitamin D Test', 'Iron Studies'], 'chronic headache': ['CBC', 'Thyroid Function Test', 'Vitamin B12 Test'], 'confusion': ['Electrolyte Panel', 'Thyroid Function Test', 'Vitamin B12 Test'], 'tremors': ['Thyroid Function Test', 'Electrolyte Panel'], 'chest tightness': ['CBC', 'D-Dimer Test', 'Troponin Test'], 'swollen feet': ['Kidney Function Test', 'Liver Function Test', 'Albumin Test'], 'frequent infections': ['CBC with Differential', 'Immunoglobulin Panel'], 'slow wound healing': ['Blood Sugar Test', 'CBC', 'Vitamin C Test'], 'yellowing of skin or eyes': ['Liver Function Test', 'Bilirubin Test'], 'excessive sweating': ['Thyroid Function Test', 'Glucose Test'], }

# Doctor mapping
doctor_mapping = {
    'Hematologist': ['hemoglobin','rbc','wbc','platelets','crp'],
    'Endocrinologist': ['glucose','cholesterol','triglycerides','hdl','ldl','vitamin d','vitamin b12'],
    'Nephrologist': ['creatinine','urea','sodium','potassium','calcium','phosphate','magnesium'],
    'Hepatologist': ['alt','ast','bilirubin','albumin','total protein'],
    'Gastroenterologist': ['amylase','lipase'],
    'Cardiologist': ['cholesterol','triglycerides','hdl','ldl'],
    'General Physician': ['prothrombin time','inr']
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/recommend-tests', methods=['POST'])
def recommend_tests():
    data = request.json
    symptoms = data.get('symptoms', '').lower()
    recommended = set()
    for keyword, tests in symptom_to_tests.items():
        if keyword in symptoms:
            recommended.update(tests)
    return jsonify({'recommended_tests': list(recommended)})

# Extract text from different file types
def extract_text_from_file(filepath):
    text = ''
    if filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
        image = Image.open(filepath)
        text = pytesseract.image_to_string(image)
    elif filepath.lower().endswith('.pdf'):
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
    elif filepath.lower().endswith(('.doc', '.docx')):
        doc = Document(filepath)
        for para in doc.paragraphs:
            text += para.text + '\n'
    elif filepath.lower().endswith('.txt'):
        with open(filepath, 'r') as f:
            text = f.read()
    return text.lower()

# Analyze blood report
def analyze_blood_report(text):
    analysis = []
    for param, details in reference_ranges.items():
        pattern = rf"{param}[:\s]*([0-9]*\.?[0-9]+)"
        match = re.search(pattern, text)
        if match:
            value = float(match.group(1))
            if value < details['min']:
                status = 'Abnormal'
                explanation = f"Low {param}: may indicate {details['explanation'].split('High')[-1].strip()}"
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

@app.route('/upload-report', methods=['POST'])
def upload_report():
    if 'report-file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['report-file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    extracted_text = extract_text_from_file(filepath)
    analysis = analyze_blood_report(extracted_text)

    # Determine abnormal parameters
    abnormal_params = [item['parameter'] for item in analysis if item['status'] == 'Abnormal']

    # Suggest doctors based on abnormal parameters
    recommended_doctors = set()
    for doctor, params in doctor_mapping.items():
        for param in abnormal_params:
            if param in params:
                recommended_doctors.add(doctor)
    if recommended_doctors:
        doctor_suggestion = "Consult: " + ", ".join(recommended_doctors) + "."
    else:
        doctor_suggestion = "All parameters are within normal ranges."

    return jsonify({
        'analysis': analysis,
        'doctor_recommendation': doctor_suggestion
    })

if __name__ == '__main__':
    app.run(debug=True)
