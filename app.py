from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
import time
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for flash messages
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# ---- Helpers ----
ROLE_ORDER = ['N1', 'N2', 'N3', 'N4']
RESOLUTION_MINUTES_BY_ROLE = {
    'N1': 1,
    'N2': 2,
    'N3': 3,
    'N4': 4,
}

def get_db_connection():
    return sqlite3.connect('database.db')

def get_role_id_by_name(role_name: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id FROM role WHERE nom = ?', (role_name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def current_role_name():
    return session.get('user_role')

def ensure_ticket_columns():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('PRAGMA table_info(ticket)')
    cols = {row[1] for row in c.fetchall()}
    to_add = []
    if 'assigned_role_id' not in cols:
        to_add.append('ALTER TABLE ticket ADD COLUMN assigned_role_id INTEGER')
    if 'required_habilitation_id' not in cols:
        to_add.append('ALTER TABLE ticket ADD COLUMN required_habilitation_id INTEGER')
    if 'resolution_due_at' not in cols:
        to_add.append('ALTER TABLE ticket ADD COLUMN resolution_due_at DATETIME')
    if 'resolution_attempts' not in cols:
        to_add.append('ALTER TABLE ticket ADD COLUMN resolution_attempts INTEGER DEFAULT 0')
    for sql in to_add:
        try:
            c.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()

# Background watcher to auto-mark tickets as resolved when due
_watcher_started = False

def start_resolution_watcher():
    global _watcher_started
    if _watcher_started:
        return
    _watcher_started = True

    def _loop():
        while True:
            try:
                conn = get_db_connection()
                c = conn.cursor()
                # Get statut IDs
                c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident en cours de résolution',))
                row_in_progress = c.fetchone()
                c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident résolu',))
                row_resolu = c.fetchone()
                if row_in_progress and row_resolu:
                    in_progress_id = row_in_progress[0]
                    resolu_id = row_resolu[0]
                    now = datetime.now()
                    # Find tickets due
                    c.execute('''
                        SELECT id FROM ticket
                        WHERE statut_id = ? AND resolution_due_at IS NOT NULL AND resolution_due_at <= ?
                    ''', (in_progress_id, now))
                    due_ids = [r[0] for r in c.fetchall()]
                    if due_ids:
                        for tid in due_ids:
                            c.execute('UPDATE ticket SET statut_id = ? WHERE id = ?', (resolu_id, tid))
                        conn.commit()
                conn.close()
            except Exception:
                # Avoid crashing the loop
                pass
            time.sleep(5)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

# Ensure columns and start watcher when module loads
ensure_ticket_columns()
start_resolution_watcher()

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
            session['user_id'] = user_id
            session['user_nom'] = nom
            session['user_role'] = role
            if role == 'initial':
                return redirect(url_for('dashboard_initial'))
            elif role == 'N2':
                return redirect(url_for('dashboard_admin'))
            elif role == 'N1':
                return redirect(url_for('dashboard_n1'))
            elif role == 'N3':
                return redirect(url_for('dashboard_n3'))
            elif role == 'N4':
                return redirect(url_for('dashboard_n4'))
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
        # Assign to N1 by default if assigned_role_id column exists
        try:
            n1_id = get_role_id_by_name('N1')
            if n1_id is not None:
                c.execute('PRAGMA table_info(ticket)')
                cols = [row[1] for row in c.fetchall()]
                if 'assigned_role_id' in cols:
                    c.execute('UPDATE ticket SET assigned_role_id = ? WHERE id = ?', (n1_id, ticket_id))
        except Exception:
            pass
        conn.commit()
        conn.close()
        flash('Ticket créé avec succès !', 'success')
        # Redirect to the correct dashboard by role
        role = session.get('user_role')
        if role == 'initial':
            return redirect(url_for('dashboard_initial'))
        if role == 'N2':
            return redirect(url_for('dashboard_admin'))
        if role == 'N1':
            return redirect(url_for('dashboard_n1'))
        if role == 'N3':
            return redirect(url_for('dashboard_n3'))
        if role == 'N4':
            return redirect(url_for('dashboard_n4'))
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
    if 'user_id' not in session or session.get('user_role') not in ['N2']:
        return redirect(url_for('login'))
    nom = session.get('user_nom', '')
    user_id = session['user_id']
    # Show only admin's own tickets (Mes tickets)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        SELECT t.id, t.titre, t.description, t.date_creation, s.nom as statut
        FROM ticket t
        LEFT JOIN statut s ON t.statut_id = s.id
        WHERE t.idutilisateur = ?
        ORDER BY t.date_creation DESC
    ''', (user_id,))
    tickets = c.fetchall()
    conn.close()
    return render_template('dashboard_admin.html', nom=nom, tickets=tickets)

# Role-specific dashboards (same first page: create ticket, list own tickets)
@app.route('/dashboard-n1')
def dashboard_n1():
    if 'user_id' not in session or session.get('user_role') != 'N1':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
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
    c.execute('SELECT id, nom FROM statut')
    statuts = c.fetchall()
    conn.close()
    return render_template('dashboard_n1.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/dashboard-n3')
def dashboard_n3():
    if 'user_id' not in session or session.get('user_role') != 'N3':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
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
    c.execute('SELECT id, nom FROM statut')
    statuts = c.fetchall()
    conn.close()
    return render_template('dashboard_n3.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/dashboard-n4')
def dashboard_n4():
    if 'user_id' not in session or session.get('user_role') != 'N4':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
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
    c.execute('SELECT id, nom FROM statut')
    statuts = c.fetchall()
    conn.close()
    return render_template('dashboard_n4.html', nom=nom, tickets=tickets, statuts=statuts)

# ---- Gestion des tickets (N1, N2, N3, N4) ----
@app.route('/resoudre-tickets')
def resoudre_tickets():
    if 'user_id' not in session or session.get('user_role') not in ROLE_ORDER + ['N2']:
        return redirect(url_for('login'))
    user_id = session['user_id']
    role_name = current_role_name()
    conn = get_db_connection()
    c = conn.cursor()

    # Get current role id
    c.execute('SELECT id FROM role WHERE nom = ?', (role_name,))
    role_row = c.fetchone()
    current_role_id = role_row[0] if role_row else None

    # Ensure columns exist (assigned_role_id, required_habilitation_id)
    c.execute('PRAGMA table_info(ticket)')
    cols = [row[1] for row in c.fetchall()]
    has_assigned = 'assigned_role_id' in cols
    has_required = 'required_habilitation_id' in cols

    # Base select
    base_select = '''
        SELECT t.id, t.titre, u.nom_utilisateur as auteur, t.description, t.date_creation,
               s.nom as statut, t.required_habilitation_id, t.assigned_role_id
        FROM ticket t
        JOIN utilisateur u ON u.id = t.idutilisateur
        LEFT JOIN statut s ON t.statut_id = s.id
        WHERE 1=1
    '''
    params = []
    
    # Scope to assigned role if column exists
    if has_assigned and current_role_id is not None:
        # N1 sees tickets assigned to N1 or unassigned; others see only tickets assigned to their role
        if role_name == 'N1':
            base_select += ' AND (t.assigned_role_id = ? OR t.assigned_role_id IS NULL)'
            params.append(current_role_id)
        else:
            base_select += ' AND t.assigned_role_id = ?'
            params.append(current_role_id)

    base_select += ' ORDER BY t.date_creation DESC'

    c.execute(base_select, tuple(params))
    tickets = c.fetchall()

    # Habilitations list for qualification
    c.execute('SELECT id, nom, categorie FROM habilitation ORDER BY categorie, nom')
    habilitations = c.fetchall()

    # Current role habilitations for resolve permission
    role_hab_ids = set()
    if role_name in ROLE_ORDER + ['N2']:
        c.execute('SELECT id FROM role WHERE nom = ?', (role_name,))
        r = c.fetchone()
        if r:
            c.execute('SELECT habilitation_id FROM role_habilitation WHERE role_id = ?', (r[0],))
            role_hab_ids = {row[0] for row in c.fetchall()}

    conn.close()
    return render_template('resoudre_tickets.html', tickets=tickets, habilitations=habilitations, role_name=role_name, role_hab_ids=role_hab_ids)

# ---- Gestion des tickets (Admin only) ----
@app.route('/gestion-tickets')
def gestion_tickets():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get all tickets with user and status information
    c.execute('''
        SELECT t.id, t.titre, u.nom_utilisateur as auteur, t.description, t.date_creation,
               s.nom as statut, t.required_habilitation_id, t.assigned_role_id,
               u.prenom, u.nom as nom_utilisateur_complet
        FROM ticket t
        JOIN utilisateur u ON u.id = t.idutilisateur
        LEFT JOIN statut s ON t.statut_id = s.id
        ORDER BY t.date_creation DESC
    ''')
    tickets = c.fetchall()
    
    # Get all statuts for dropdown
    c.execute('SELECT id, nom FROM statut ORDER BY nom')
    statuts = c.fetchall()
    
    # Get all users for dropdown
    c.execute('SELECT id, nom_utilisateur, prenom, nom FROM utilisateur ORDER BY nom')
    users = c.fetchall()
    
    # Get all categories and types for dropdown
    c.execute('SELECT id, nom FROM categorie ORDER BY nom')
    categories = c.fetchall()
    c.execute('SELECT id, nom FROM type ORDER BY nom')
    types = c.fetchall()
    
    conn.close()
    
    return render_template('gestion_tickets.html', tickets=tickets, statuts=statuts, users=users, categories=categories, types=types)

@app.route('/ajouter-ticket-admin', methods=['GET', 'POST'])
def ajouter_ticket_admin():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get data for dropdowns
    c.execute('SELECT id, nom FROM categorie ORDER BY nom')
    categories = c.fetchall()
    c.execute('SELECT id, nom FROM type ORDER BY nom')
    types = c.fetchall()
    c.execute('SELECT id, nom FROM statut ORDER BY nom')
    statuts = c.fetchall()
    c.execute('SELECT id, nom_utilisateur, prenom, nom FROM utilisateur ORDER BY nom')
    users = c.fetchall()
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        statut_id = request.form.get('statut')
        user_id = request.form.get('user_id')
        
        # Insert ticket
        c.execute('''
            INSERT INTO ticket (titre, description, date_creation, idutilisateur, categorie_id, type_id, statut_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (titre, description, datetime.now(), user_id, categorie_id, type_id, statut_id))
        
        conn.commit()
        conn.close()
        
        flash('Ticket créé avec succès !', 'success')
        return redirect(url_for('gestion_tickets'))
    
    conn.close()
    return render_template('ajouter_ticket_admin.html', categories=categories, types=types, statuts=statuts, users=users)

@app.route('/modifier-ticket/<int:ticket_id>', methods=['GET', 'POST'])
def modifier_ticket(ticket_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get data for dropdowns
    c.execute('SELECT id, nom FROM categorie ORDER BY nom')
    categories = c.fetchall()
    c.execute('SELECT id, nom FROM type ORDER BY nom')
    types = c.fetchall()
    c.execute('SELECT id, nom FROM statut ORDER BY nom')
    statuts = c.fetchall()
    c.execute('SELECT id, nom_utilisateur, prenom, nom FROM utilisateur ORDER BY nom')
    users = c.fetchall()
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        statut_id = request.form.get('statut')
        user_id = request.form.get('user_id')
        
        # Update ticket
        c.execute('''
            UPDATE ticket 
            SET titre = ?, description = ?, categorie_id = ?, type_id = ?, statut_id = ?, idutilisateur = ?
            WHERE id = ?
        ''', (titre, description, categorie_id, type_id, statut_id, user_id, ticket_id))
        
        conn.commit()
        conn.close()
        
        flash('Ticket modifié avec succès !', 'success')
        return redirect(url_for('gestion_tickets'))
    
    # Get current ticket data
    c.execute('''
        SELECT t.id, t.titre, t.description, t.categorie_id, t.type_id, t.statut_id, t.idutilisateur,
               u.nom_utilisateur, u.prenom, u.nom
        FROM ticket t
        JOIN utilisateur u ON u.id = t.idutilisateur
        WHERE t.id = ?
    ''', (ticket_id,))
    ticket = c.fetchone()
    
    if not ticket:
        conn.close()
        flash('Ticket non trouvé.', 'error')
        return redirect(url_for('gestion_tickets'))
    
    conn.close()
    return render_template('modifier_ticket.html', ticket=ticket, categories=categories, types=types, statuts=statuts, users=users)

@app.route('/supprimer-ticket/<int:ticket_id>', methods=['POST'])
def supprimer_ticket(ticket_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Delete ticket
    c.execute('DELETE FROM ticket WHERE id = ?', (ticket_id,))
    conn.commit()
    conn.close()
    
    flash('Ticket supprimé avec succès !', 'success')
    return redirect(url_for('gestion_tickets'))

@app.route('/tickets/<int:ticket_id>/qualifier', methods=['POST'])
def qualifier_ticket(ticket_id: int):
    if 'user_id' not in session or session.get('user_role') != 'N1':
        return redirect(url_for('login'))
    required_hab_id = request.form.get('habilitation_id')
    if not required_hab_id:
        flash('Veuillez sélectionner une habilitation.', 'error')
        return redirect(url_for('resoudre_tickets'))
    conn = get_db_connection()
    c = conn.cursor()
    # Ensure column exists
    c.execute('PRAGMA table_info(ticket)')
    cols = [row[1] for row in c.fetchall()]
    if 'required_habilitation_id' not in cols:
        flash("Champ 'required_habilitation_id' manquant dans ticket.", 'error')
        conn.close()
        return redirect(url_for('resoudre_tickets'))
    # Set required habilitation and status to 'Incident pris en charge'
    c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident pris en charge',))
    statut_row = c.fetchone()
    statut_id = statut_row[0] if statut_row else None
    c.execute('UPDATE ticket SET required_habilitation_id = ?, statut_id = ? WHERE id = ?', (required_hab_id, statut_id, ticket_id))
    conn.commit()
    conn.close()
    flash('Qualification enregistrée.', 'success')
    return redirect(url_for('resoudre_tickets'))

@app.route('/tickets/<int:ticket_id>/escalader', methods=['POST'])
def escalader_ticket(ticket_id: int):
    if 'user_id' not in session or session.get('user_role') not in ROLE_ORDER + ['N2']:
        return redirect(url_for('login'))
    role_name = current_role_name()
    if role_name == 'N4':
        flash('Impossible d\'escalader au-delà de N4.', 'error')
        return redirect(url_for('resoudre_tickets'))
    # Determine next role
    next_role = None
    if role_name in ROLE_ORDER:
        idx = ROLE_ORDER.index(role_name)
        if idx < len(ROLE_ORDER) - 1:
            next_role = ROLE_ORDER[idx + 1]
    elif role_name == 'N2':
        next_role = 'N3'  # admin can push towards N3 if acting as dispatcher
    if not next_role:
        flash('Rôle suivant introuvable.', 'error')
        return redirect(url_for('resoudre_tickets'))
    next_role_id = get_role_id_by_name(next_role)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('PRAGMA table_info(ticket)')
    cols = [row[1] for row in c.fetchall()]
    if 'assigned_role_id' not in cols:
        flash("Champ 'assigned_role_id' manquant dans ticket.", 'error')
        conn.close()
        return redirect(url_for('resoudre_tickets'))
    # Keep status as pris en charge
    c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident pris en charge',))
    statut_row = c.fetchone()
    statut_id = statut_row[0] if statut_row else None
    c.execute('UPDATE ticket SET assigned_role_id = ?, statut_id = ? WHERE id = ?', (next_role_id, statut_id, ticket_id))
    conn.commit()
    conn.close()
    flash(f'Ticket escaladé vers {next_role}.', 'success')
    return redirect(url_for('resoudre_tickets'))

@app.route('/tickets/<int:ticket_id>/resoudre', methods=['POST'])
def resoudre_ticket(ticket_id: int):
    if 'user_id' not in session or session.get('user_role') not in ROLE_ORDER + ['N2']:
        return redirect(url_for('login'))
    role_name = current_role_name()
    # Allow N4 always; others only if they have the required habilitation
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('PRAGMA table_info(ticket)')
    cols = [row[1] for row in c.fetchall()]
    if 'required_habilitation_id' not in cols or 'resolution_due_at' not in cols or 'resolution_attempts' not in cols:
        flash("Champs de support de résolution manquants dans ticket.", 'error')
        conn.close()
        return redirect(url_for('resoudre_tickets'))
    c.execute('SELECT required_habilitation_id, resolution_attempts FROM ticket WHERE id = ?', (ticket_id,))
    row = c.fetchone()
    required_hab_id = row[0] if row else None
    attempts = row[1] or 0
    allowed = False
    if role_name == 'N4':
        allowed = True
    elif required_hab_id is not None:
        # Check role has habilitation
        role_id = get_role_id_by_name(role_name)
        c.execute('SELECT 1 FROM role_habilitation WHERE role_id = ? AND habilitation_id = ?', (role_id, required_hab_id))
        if c.fetchone():
            allowed = True
    if not allowed:
        conn.close()
        flash("Vous n'avez pas l'habilitation requise pour résoudre ce ticket.", 'error')
        return redirect(url_for('resoudre_tickets'))
    # Set status to 'Incident en cours de résolution' and due time
    c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident en cours de résolution',))
    statut_row = c.fetchone()
    statut_id = statut_row[0] if statut_row else None
    minutes = RESOLUTION_MINUTES_BY_ROLE.get(role_name, 2)
    due_at = datetime.now() + timedelta(minutes=minutes)
    c.execute('UPDATE ticket SET statut_id = ?, date_mise_a_jour = ?, resolution_due_at = ?, resolution_attempts = ? WHERE id = ?', (statut_id, datetime.now(), due_at, attempts + 1, ticket_id))
    conn.commit()
    conn.close()
    flash(f'Ticket en résolution ({minutes} min).', 'success')
    return redirect(url_for('resoudre_tickets'))

# Endpoints for requester validation
@app.route('/tickets/<int:ticket_id>/valider', methods=['POST'])
def valider_ticket(ticket_id: int):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Only the creator can validate/refuse
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT idutilisateur FROM ticket WHERE id = ?', (ticket_id,))
    row = c.fetchone()
    if not row or row[0] != session['user_id']:
        conn.close()
        flash("Vous ne pouvez valider que vos propres tickets.", 'error')
        # Redirect to appropriate dashboard based on user role
        user_role = session.get('user_role')
        if user_role == 'N2':
            return redirect(url_for('dashboard_admin'))
        elif user_role == 'N1':
            return redirect(url_for('dashboard_n1'))
        elif user_role == 'N3':
            return redirect(url_for('dashboard_n3'))
        elif user_role == 'N4':
            return redirect(url_for('dashboard_n4'))
        else:
            return redirect(url_for('dashboard_initial'))
    # Set status to 'Incident clos'
    c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident clos',))
    srow = c.fetchone()
    if srow:
        c.execute('UPDATE ticket SET statut_id = ?, date_cloture = ? WHERE id = ?', (srow[0], datetime.now(), ticket_id))
        conn.commit()
    conn.close()
    flash('Ticket clôturé avec succès.', 'success')
    # Redirect to appropriate dashboard based on user role
    user_role = session.get('user_role')
    if user_role == 'N2':
        return redirect(url_for('dashboard_admin'))
    elif user_role == 'N1':
        return redirect(url_for('dashboard_n1'))
    elif user_role == 'N3':
        return redirect(url_for('dashboard_n3'))
    elif user_role == 'N4':
        return redirect(url_for('dashboard_n4'))
    else:
        return redirect(url_for('dashboard_initial'))

@app.route('/tickets/<int:ticket_id>/refuser', methods=['POST'])
def refuser_ticket(ticket_id: int):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Only the creator can refuse
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT idutilisateur, titre FROM ticket WHERE id = ?', (ticket_id,))
    row = c.fetchone()
    if not row or row[0] != session['user_id']:
        conn.close()
        flash("Vous ne pouvez refuser que vos propres tickets.", 'error')
        # Redirect to appropriate dashboard based on user role
        user_role = session.get('user_role')
        if user_role == 'N2':
            return redirect(url_for('dashboard_admin'))
        elif user_role == 'N1':
            return redirect(url_for('dashboard_n1'))
        elif user_role == 'N3':
            return redirect(url_for('dashboard_n3'))
        elif user_role == 'N4':
            return redirect(url_for('dashboard_n4'))
        else:
            return redirect(url_for('dashboard_initial'))
    titre = row[1] or ''
    # Reset status to first step and append note to title
    c.execute('SELECT id FROM statut WHERE nom = ?', ('Incident déclaré',))
    srow = c.fetchone()
    new_title = (titre + ' [Retour - solution non concluante]').strip()
    if srow:
        # Reset ticket to initial state: clear habilitation and reassign to N1
        n1_role_id = get_role_id_by_name('N1')
        c.execute('UPDATE ticket SET statut_id = ?, titre = ?, resolution_due_at = NULL, required_habilitation_id = NULL, assigned_role_id = ? WHERE id = ?', (srow[0], new_title, n1_role_id, ticket_id))
        conn.commit()
    conn.close()
    flash('Ticket renvoyé pour nouveau traitement.', 'success')
    # Redirect to appropriate dashboard based on user role
    user_role = session.get('user_role')
    if user_role == 'N2':
        return redirect(url_for('dashboard_admin'))
    elif user_role == 'N1':
        return redirect(url_for('dashboard_n1'))
    elif user_role == 'N3':
        return redirect(url_for('dashboard_n3'))
    elif user_role == 'N4':
        return redirect(url_for('dashboard_n4'))
    else:
        return redirect(url_for('dashboard_initial'))

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