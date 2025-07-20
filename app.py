from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for flash messages
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

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
        c.execute('SELECT id, nom, role FROM utilisateur WHERE nom_utilisateur=? AND mot_de_passe=?', (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            user_id, nom, role = user
            if role == 'initial':
                session['user_id'] = user_id
                session['user_nom'] = nom
                return redirect(url_for('dashboard_initial'))
            else:
                message = "Votre rôle n'est pas autorisé à accéder à ce tableau de bord."
        else:
            message = 'Nom d\'utilisateur ou mot de passe incorrect.'
    return render_template('login.html', message=message)

@app.route('/dashboard-initial')
def dashboard_initial():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
    
    # Get user's tickets
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        SELECT t.id, t.titre, t.description, t.date_creation, s.nom
        FROM ticket t
        LEFT JOIN statut s ON t.statut_id = s.id
        WHERE t.idutilisateur = ?
        ORDER BY t.date_creation DESC
    ''', (user_id,))
    tickets = c.fetchall()
    # Get all statuts for dropdowns or display
    c.execute('SELECT id, nom FROM statut')
    statuts = c.fetchall()
    conn.close()
    
    return render_template('dashboard_initial.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/ajouter-ticket', methods=['GET', 'POST'])
def ajouter_ticket():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, nom FROM categorie')
    categories = c.fetchall()
    c.execute('SELECT id, nom FROM type')
    types = c.fetchall()
    conn.close()
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        user_id = session['user_id']
        fichier_id = None
        # Handle file upload
        file = request.files.get('fichier')
        if file and file.filename:
            file_data = file.read()
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute('INSERT INTO fichier (fichier) VALUES (?)', (file_data,))
            fichier_id = c.lastrowid
            conn.commit()
            conn.close()
        # Insert ticket
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO ticket (titre, description, date_creation, idutilisateur, categorie_id, type_id, statut_id)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (titre, description, datetime.now(), user_id, categorie_id, type_id))
        ticket_id = c.lastrowid
        # Optionally link the file to the ticket (if you want a ticket_id in fichier, you can update the schema)
        # For now, just store the file in fichier and ticket in ticket
        conn.commit()
        conn.close()
        flash('Ticket créé avec succès !', 'success')
        return redirect(url_for('dashboard_initial'))
    
    return render_template('ajouter_ticket.html', categories=categories, types=types)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
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
            try:
                sender = os.environ.get('GMAIL_USER')
                app_password = os.environ.get('GMAIL_APP_PASSWORD')
                receiver = email
                msg = MIMEText(f'Votre mot de passe est : {password}')
                msg['Subject'] = 'Votre mot de passe'
                msg['From'] = sender
                msg['To'] = receiver
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(sender, app_password)
                    server.sendmail(sender, [receiver], msg.as_string())
                flash('Votre mot de passe a été envoyé à votre adresse e-mail.', 'success')
            except Exception as e:
                flash('Échec de l\'envoi de l\'e-mail : ' + str(e), 'error')
        else:
            message = 'Le nom d\'utilisateur et l\'e-mail ne correspondent pas à nos enregistrements.'
    return render_template('forgot_password.html', message=message)

@app.route('/success')
def success():
    return 'Connexion réussie !'

if __name__ == '__main__':
    app.run(debug=True) 