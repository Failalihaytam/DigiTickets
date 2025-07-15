from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for flash messages

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    message = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT * FROM utilisateur WHERE nom_utilisateur=? AND mot_de_passe=?', (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            return redirect(url_for('success'))
        else:
            message = 'Incorrect username or password.'
    return render_template('login.html', message=message)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    message = ''
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT mot_de_passe FROM utilisateur WHERE nom_utilisateur=? AND email=?', (username, email))
        result = c.fetchone()
        conn.close()
        if result:
            password = result[0]
            # Send email using Gmail SMTP
            try:
                sender = os.environ.get('GMAIL_USER')
                app_password = os.environ.get('GMAIL_APP_PASSWORD')
                receiver = email
                msg = MIMEText(f'Your password is: {password}')
                msg['Subject'] = 'Your Password'
                msg['From'] = sender
                msg['To'] = receiver
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(sender, app_password)
                    server.sendmail(sender, [receiver], msg.as_string())
                flash('Your password has been sent to your email.', 'success')
            except Exception as e:
                flash('Failed to send email: ' + str(e), 'error')
        else:
            message = 'Username and email do not match our records.'
    return render_template('forgot_password.html', message=message)

@app.route('/success')
def success():
    return 'Login successful!'

if __name__ == '__main__':
    app.run(debug=True) 