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
        c.execute('''
            SELECT u.id, u.nom, r.nom as role_nom 
            FROM utilisateur u 
            JOIN role r ON u.role_id = r.id 
            WHERE u.nom_utilisateur=? AND u.mot_de_passe=?
        ''', (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            user_id, nom, role = user
            if role == 'initial':
                session['user_id'] = user_id
                session['user_nom'] = nom
                session['user_role'] = role
                return redirect(url_for('dashboard_initial'))
            elif role in ['N1', 'N2', 'N3', 'N4']:
                session['user_id'] = user_id
                session['user_nom'] = nom
                session['user_role'] = role
                return redirect(url_for('dashboard_admin'))
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

@app.route('/dashboard-admin')
def dashboard_admin():
    if 'user_id' not in session or session.get('user_role') not in ['N1', 'N2', 'N3', 'N4']:
        return redirect(url_for('login'))
    nom = session.get('user_nom', '')
    # Show all tickets for admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        SELECT t.id, t.titre, t.description, t.date_creation, s.nom as statut
        FROM ticket t
        LEFT JOIN statut s ON t.statut_id = s.id
        ORDER BY t.date_creation DESC
    ''')
    tickets = c.fetchall()
    conn.close()
    return render_template('dashboard_admin.html', nom=nom, tickets=tickets)

# User Management Routes
@app.route('/gestion-utilisateurs')
def gestion_utilisateurs():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        SELECT u.id, u.nom_utilisateur, u.email, u.prenom, u.nom, r.nom as role_nom
        FROM utilisateur u
        JOIN role r ON u.role_id = r.id
        ORDER BY u.nom
    ''')
    users = c.fetchall()
    conn.close()
    
    return render_template('gestion_utilisateurs.html', users=users)

@app.route('/ajouter-utilisateur', methods=['GET', 'POST'])
def ajouter_utilisateur():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, nom, description FROM role ORDER BY nom')
    roles = c.fetchall()
    conn.close()
    
    if request.method == 'POST':
        nom_utilisateur = request.form['nom_utilisateur']
        email = request.form['email']
        mot_de_passe = request.form['mot_de_passe']
        prenom = request.form['prenom']
        nom = request.form['nom']
        role_id = request.form['role_id']
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # Check if username already exists
        c.execute('SELECT id FROM utilisateur WHERE nom_utilisateur = ?', (nom_utilisateur,))
        if c.fetchone():
            flash('Ce nom d\'utilisateur existe déjà.', 'error')
            conn.close()
            return render_template('ajouter_utilisateur.html', roles=roles)
        
        # Check if email already exists
        c.execute('SELECT id FROM utilisateur WHERE email = ?', (email,))
        if c.fetchone():
            flash('Cette adresse e-mail existe déjà.', 'error')
            conn.close()
            return render_template('ajouter_utilisateur.html', roles=roles)
        
        # Insert new user
        c.execute('''
            INSERT INTO utilisateur (nom_utilisateur, email, mot_de_passe, prenom, nom, role_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nom_utilisateur, email, mot_de_passe, prenom, nom, role_id))
        
        conn.commit()
        conn.close()
        
        flash('Utilisateur ajouté avec succès !', 'success')
        return redirect(url_for('gestion_utilisateurs'))
    
    return render_template('ajouter_utilisateur.html', roles=roles)

@app.route('/modifier-utilisateur/<int:user_id>', methods=['GET', 'POST'])
def modifier_utilisateur(user_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Get roles for dropdown
    c.execute('SELECT id, nom, description FROM role ORDER BY nom')
    roles = c.fetchall()
    
    if request.method == 'POST':
        nom_utilisateur = request.form['nom_utilisateur']
        email = request.form['email']
        prenom = request.form['prenom']
        nom = request.form['nom']
        role_id = request.form['role_id']
        mot_de_passe = request.form.get('mot_de_passe', '')
        
        # Check if username already exists (excluding current user)
        c.execute('SELECT id FROM utilisateur WHERE nom_utilisateur = ? AND id != ?', (nom_utilisateur, user_id))
        if c.fetchone():
            flash('Ce nom d\'utilisateur existe déjà.', 'error')
            conn.close()
            return redirect(url_for('modifier_utilisateur', user_id=user_id))
        
        # Check if email already exists (excluding current user)
        c.execute('SELECT id FROM utilisateur WHERE email = ? AND id != ?', (email, user_id))
        if c.fetchone():
            flash('Cette adresse e-mail existe déjà.', 'error')
            conn.close()
            return redirect(url_for('modifier_utilisateur', user_id=user_id))
        
        # Update user
        if mot_de_passe:
            c.execute('''
                UPDATE utilisateur 
                SET nom_utilisateur = ?, email = ?, mot_de_passe = ?, prenom = ?, nom = ?, role_id = ?
                WHERE id = ?
            ''', (nom_utilisateur, email, mot_de_passe, prenom, nom, role_id, user_id))
        else:
            c.execute('''
                UPDATE utilisateur 
                SET nom_utilisateur = ?, email = ?, prenom = ?, nom = ?, role_id = ?
                WHERE id = ?
            ''', (nom_utilisateur, email, prenom, nom, role_id, user_id))
        
        conn.commit()
        conn.close()
        
        flash('Utilisateur modifié avec succès !', 'success')
        return redirect(url_for('gestion_utilisateurs'))
    
    # Get user data for editing
    c.execute('''
        SELECT u.id, u.nom_utilisateur, u.email, u.prenom, u.nom, u.role_id, r.nom as role_nom
        FROM utilisateur u
        JOIN role r ON u.role_id = r.id
        WHERE u.id = ?
    ''', (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        flash('Utilisateur non trouvé.', 'error')
        return redirect(url_for('gestion_utilisateurs'))
    
    return render_template('modifier_utilisateur.html', user=user, roles=roles)

@app.route('/supprimer-utilisateur/<int:user_id>', methods=['POST'])
def supprimer_utilisateur(user_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Prevent admin from deleting themselves
    if user_id == session['user_id']:
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'error')
        return redirect(url_for('gestion_utilisateurs'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Check if user has any tickets
    c.execute('SELECT COUNT(*) FROM ticket WHERE idutilisateur = ?', (user_id,))
    ticket_count = c.fetchone()[0]
    
    if ticket_count > 0:
        flash('Impossible de supprimer cet utilisateur car il a des tickets associés.', 'error')
        conn.close()
        return redirect(url_for('gestion_utilisateurs'))
    
    # Delete user
    c.execute('DELETE FROM utilisateur WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    flash('Utilisateur supprimé avec succès !', 'success')
    return redirect(url_for('gestion_utilisateurs'))

# Habilitation Management Routes
@app.route('/gestion-habilitations')
def gestion_habilitations():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, nom, description FROM role ORDER BY nom')
    roles = c.fetchall()
    conn.close()
    
    return render_template('gestion_habilitations.html', roles=roles)

@app.route('/gestion-habilitations/<int:role_id>')
def gestion_habilitations_role(role_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Get role info
    c.execute('SELECT id, nom, description FROM role WHERE id = ?', (role_id,))
    role = c.fetchone()
    
    if not role:
        flash('Rôle non trouvé.', 'error')
        return redirect(url_for('gestion_habilitations'))
    
    # Get current habilitations for this role
    c.execute('''
        SELECT h.id, h.nom, h.description, h.categorie
        FROM habilitation h
        JOIN role_habilitation rh ON h.id = rh.habilitation_id
        WHERE rh.role_id = ?
        ORDER BY h.categorie, h.nom
    ''', (role_id,))
    current_habilitations = c.fetchall()
    
    # Get all available habilitations
    c.execute('''
        SELECT h.id, h.nom, h.description, h.categorie
        FROM habilitation h
        ORDER BY h.categorie, h.nom
    ''')
    all_habilitations = c.fetchall()
    
    conn.close()
    
    return render_template('gestion_habilitations_role.html', 
                         role=role, 
                         current_habilitations=current_habilitations,
                         all_habilitations=all_habilitations)

@app.route('/ajouter-habilitation-role/<int:role_id>', methods=['POST'])
def ajouter_habilitation_role(role_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    habilitation_id = request.form.get('habilitation_id')
    
    if not habilitation_id:
        flash('Veuillez sélectionner une habilitation.', 'error')
        return redirect(url_for('gestion_habilitations_role', role_id=role_id))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute('''
            INSERT INTO role_habilitation (role_id, habilitation_id)
            VALUES (?, ?)
        ''', (role_id, habilitation_id))
        conn.commit()
        flash('Habilitation ajoutée au rôle avec succès !', 'success')
    except sqlite3.IntegrityError:
        flash('Cette habilitation est déjà assignée à ce rôle.', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('gestion_habilitations_role', role_id=role_id))

@app.route('/supprimer-habilitation-role/<int:role_id>/<int:habilitation_id>', methods=['POST'])
def supprimer_habilitation_role(role_id, habilitation_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute('''
        DELETE FROM role_habilitation 
        WHERE role_id = ? AND habilitation_id = ?
    ''', (role_id, habilitation_id))
    
    conn.commit()
    conn.close()
    
    flash('Habilitation supprimée du rôle avec succès !', 'success')
    return redirect(url_for('gestion_habilitations_role', role_id=role_id))

if __name__ == '__main__':
    app.run(debug=True) 