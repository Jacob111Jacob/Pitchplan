# app.py

from flask import Flask, request, render_template_string, send_file, redirect, url_for, jsonify
import pandas as pd
from fpdf import FPDF
import os
import stripe
import smtplib
from email.message import EmailMessage
import firebase_admin
from firebase_admin import credentials, firestore

# === INIT ===
app = Flask(__name__)

# === STRIPE SETUP ===
stripe.api_key = os.getenv('STRIPE_API_KEY')

# === FIREBASE SETUP ===
cred = credentials.Certificate("firebase_service_account.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

pdf_path = "practice_plan.pdf"

# === BASE HTML ===
HTML_FORM = '''
<!doctype html>
<title>PitchPlan.ai - AI Practice Plans</title>
<h2>Upload Stats or Enter Player Info</h2>
<form method=post enctype=multipart/form-data>
  CSV File: <input type=file name=file><br><br>
  Manual Entry:<br>
  Name: <input type=text name=name><br>
  Strikeout Rate: <input type=text name=strikeout_rate><br>
  First Pitch Swing Rate: <input type=text name=first_pitch_swing_rate><br>
  Contact Rate: <input type=text name=contact_rate><br>
  BB/9: <input type=text name=bb9><br>
  First Pitch Strike Rate: <input type=text name=first_pitch_strike_rate><br>
  Velocity: <input type=text name=velocity><br><br>
  Email (to receive PDF): <input type=text name=email><br><br>
  <input type=submit value="Generate Plan">
</form>
''' + '''<br><a href="/pricing">Pricing Page</a> | <a href="/download">Download PDF</a>'''

# === ANALYSIS LOGIC ===
def analyze_player(row):
    hitting_plan = []
    pitching_plan = []
    if row['strikeout_rate'] > 0.3:
        hitting_plan.append("2-strike approach drills")
    if row['first_pitch_swing_rate'] < 0.2:
        hitting_plan.append("early count aggression reps")
    if row['contact_rate'] < 0.7:
        hitting_plan.append("short bat/soft toss drills")
    if row.get('bb9', 0) > 4:
        pitching_plan.append("command-focused bullpen")
    if row.get('first_pitch_strike_rate', 1) < 0.5:
        pitching_plan.append("first-pitch strike simulation game")
    if row.get('velocity', 0) < 75:
        pitching_plan.append("long toss & weighted ball program")
    return hitting_plan, pitching_plan

# === PLAN GENERATOR ===
def generate_plans(df):
    plans = []
    for _, row in df.iterrows():
        hitter, pitcher = analyze_player(row)
        plans.append({
            'name': row['name'],
            'hitting_plan': hitter,
            'pitching_plan': pitcher
        })
    return plans

# === PDF CREATOR ===
def create_pdf(plans):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Baseball Practice Plan Report", ln=True, align="C")
    pdf.ln(10)
    for plan in plans:
        pdf.set_font("Arial", style='B', size=12)
        pdf.cell(200, 10, txt=f"Player: {plan['name']}", ln=True)
        pdf.set_font("Arial", size=12)
        if plan['hitting_plan']:
            pdf.cell(200, 10, txt="Hitting Plan:", ln=True)
            for drill in plan['hitting_plan']:
                pdf.cell(200, 10, txt=f"✓ {drill}", ln=True)
        if plan['pitching_plan']:
            pdf.cell(200, 10, txt="Pitching Plan:", ln=True)
            for drill in plan['pitching_plan']:
                pdf.cell(200, 10, txt=f"✓ {drill}", ln=True)
        pdf.ln(5)
    pdf.output(pdf_path)

# === EMAIL PDF ===
def send_pdf(email):
    try:
        msg = EmailMessage()
        msg['Subject'] = 'PitchPlan Report'
        msg['From'] = 'your_email@example.com'
        msg['To'] = email
        msg.set_content('Attached is your PitchPlan PDF.')
        with open(pdf_path, 'rb') as f:
            msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename='PitchPlan.pdf')
        with smtplib.SMTP('smtp.example.com', 587) as smtp:
            smtp.starttls()
            smtp.login('your_email@example.com', 'your_password')
            smtp.send_message(msg)
    except Exception as e:
        print(f"Email failed: {e}")

# === ROUTES ===
@app.route('/', methods=['GET', 'POST'])
def upload_file():
    plans = []
    if request.method == 'POST':
        email = request.form.get('email')
        file = request.files.get('file')
        if file and file.filename != '':
            df = pd.read_csv(file)
        else:
            manual = {
                'name': request.form.get('name', 'Player'),
                'strikeout_rate': float(request.form.get('strikeout_rate', 0)),
                'first_pitch_swing_rate': float(request.form.get('first_pitch_swing_rate', 0)),
                'contact_rate': float(request.form.get('contact_rate', 0)),
                'bb9': float(request.form.get('bb9', 0)),
                'first_pitch_strike_rate': float(request.form.get('first_pitch_strike_rate', 0)),
                'velocity': float(request.form.get('velocity', 0))
            }
            df = pd.DataFrame([manual])
        plans = generate_plans(df)
        create_pdf(plans)
        if email:
            send_pdf(email)
    return render_template_string(HTML_FORM)

@app.route('/download')
def download_pdf():
    return send_file(pdf_path, as_attachment=True)

@app.route('/pricing')
def pricing():
    return open("pricing.html").read()

@app.route('/create-checkout-session', methods=['GET'])
def create_checkout_session():
    email = request.args.get('email')
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'unit_amount': 500,
                'product_data': {'name': 'PitchPlan Pro'},
            },
            'quantity': 1,
        }],
        mode='subscription',
        customer_email=email,
        success_url='https://pitchplan.onrender.com',
        cancel_url='https://pitchplan.onrender.com',
    )
    return redirect(session.url, code=303)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig = request.headers.get('stripe-signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    try:
        event = stripe.Webhook.construct_event(payload, sig, endpoint_secret)
    except Exception as e:
        return str(e), 400
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        db.collection('subscribers').document(session['customer_email']).set({
            'active': True,
            'stripe_id': session['customer']
        })
    return '', 200

# === RUN ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)


