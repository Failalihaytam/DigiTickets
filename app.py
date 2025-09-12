from flask import Flask, render_template, request, redirect, url_for, flash, session
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
import time
from supabase_db import db
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

def get_role_id_by_name(role_name: str):
    return db.get_role_by_name(role_name)

def current_role_name():
    return session.get('user_role')

def ensure_ticket_columns():
    # No longer needed with Supabase - schema is already defined
    pass

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
                # Get status IDs
                in_progress_id = db.get_status_by_name('Incident en cours de résolution')
                resolved_id = db.get_status_by_name('Incident résolu')
                
                if in_progress_id and resolved_id:
                    # Find tickets due for resolution
                    due_tickets = db.get_tickets_due_for_resolution()
                    if due_tickets:
                        for ticket in due_tickets:
                            db.update_ticket_status(ticket['id'], resolved_id)
            except Exception as e:
                print(f"Resolution watcher error: {e}")
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
        
        user = db.get_user_by_credentials(username, password)
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
    tickets_data = db.get_user_tickets(user_id)
    tickets = [(t['id'], t['titre'], t['description'], t['date_creation'], t['statut']['nom']) 
               for t in tickets_data]
    
    # Get all statuses
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    return render_template('dashboard_initial.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/ajouter-ticket', methods=['GET', 'POST'])
def ajouter_ticket():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get categories and types
    categories_data = db.get_all_categories()
    categories = [(c['id'], c['nom']) for c in categories_data]
    types_data = db.get_all_types()
    types = [(t['id'], t['nom']) for t in types_data]
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        user_id = session['user_id']
        
        # Handle file upload
        file = request.files.get('fichier')
        fichier_id = None
        if file and file.filename:
            file_data = file.read()
            file_record = db.create_file({'fichier': file_data.hex()})  # Convert to hex for storage
            fichier_id = file_record['id'] if file_record else None
        
        # Get status ID for 'Incident déclaré'
        statut_id = db.get_status_by_name('Incident déclaré')
        if not statut_id:
            flash('Statut "Incident déclaré" non trouvé dans la base de données.', 'error')
            return redirect(url_for('ajouter_ticket'))
        
        # Create ticket data
        ticket_data = {
            'titre': titre,
            'description': description,
            'date_creation': datetime.now().isoformat(),
            'idutilisateur': user_id,
            'categorie_id': int(categorie_id) if categorie_id else None,
            'type_id': int(type_id) if type_id else None,
            'statut_id': statut_id
        }
        
        # Create ticket
        ticket = db.create_ticket(ticket_data)
        
        if ticket:
            # Assign to N1 by default
            n1_id = get_role_id_by_name('N1')
            if n1_id:
                db.update_ticket(ticket['id'], {'assigned_role_id': n1_id})
            
            flash('Ticket créé avec succès !', 'success')
        else:
            flash('Erreur lors de la création du ticket', 'error')
        
        # Redirect to the correct dashboard by role
        role = session.get('user_role')
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
        
        # Check if user exists with matching username and email
        users = db.get_all_users()
        user = None
        for u in users:
            if u['nom_utilisateur'] == username and u['email'] == email:
                user = u
                break
        
        if user:
            password = user['mot_de_passe']
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
    tickets_data = db.get_user_tickets(user_id)
    tickets = [(t['id'], t['titre'], t['description'], t['date_creation'], t['statut']['nom']) 
               for t in tickets_data]
    
    return render_template('dashboard_admin.html', nom=nom, tickets=tickets)

# Role-specific dashboards (same first page: create ticket, list own tickets)
@app.route('/dashboard-n1')
def dashboard_n1():
    if 'user_id' not in session or session.get('user_role') != 'N1':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
    
    tickets_data = db.get_user_tickets(user_id)
    tickets = [(t['id'], t['titre'], t['description'], t['date_creation'], t['statut']['nom']) 
               for t in tickets_data]
    
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    return render_template('dashboard_n1.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/dashboard-n3')
def dashboard_n3():
    if 'user_id' not in session or session.get('user_role') != 'N3':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
    
    tickets_data = db.get_user_tickets(user_id)
    tickets = [(t['id'], t['titre'], t['description'], t['date_creation'], t['statut']['nom']) 
               for t in tickets_data]
    
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    return render_template('dashboard_n3.html', nom=nom, tickets=tickets, statuts=statuts)

@app.route('/dashboard-n4')
def dashboard_n4():
    if 'user_id' not in session or session.get('user_role') != 'N4':
        return redirect(url_for('login'))
    user_id = session['user_id']
    nom = session.get('user_nom', '')
    
    tickets_data = db.get_user_tickets(user_id)
    tickets = [(t['id'], t['titre'], t['description'], t['date_creation'], t['statut']['nom']) 
               for t in tickets_data]
    
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    return render_template('dashboard_n4.html', nom=nom, tickets=tickets, statuts=statuts)

# ---- Gestion des tickets (N1, N2, N3, N4) ----
@app.route('/resoudre-tickets')
def resoudre_tickets():
    if 'user_id' not in session or session.get('user_role') not in ROLE_ORDER + ['N2']:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    role_name = current_role_name()
    current_role_id = get_role_id_by_name(role_name)

    # Get tickets based on role
    if role_name == 'N1':
        # N1 sees tickets assigned to N1 or unassigned
        tickets_data = db.get_tickets_by_role(current_role_id) if current_role_id else []
        # Also get unassigned tickets
        unassigned_tickets = db._make_request("GET", "ticket?assigned_role_id=is.null&select=id,titre,description,date_creation,statut_id,statut(nom),idutilisateur,utilisateur(nom_utilisateur),required_habilitation_id,assigned_role_id&order=date_creation.desc")
        tickets_data.extend(unassigned_tickets)
    else:
        # Others see only tickets assigned to their role
        tickets_data = db.get_tickets_by_role(current_role_id) if current_role_id else []

    # Format tickets for template
    tickets = []
    for t in tickets_data:
        ticket_tuple = (
            t['id'], 
            t['titre'], 
            t['utilisateur']['nom_utilisateur'], 
            t['description'], 
            t['date_creation'],
            t['statut']['nom'], 
            t.get('required_habilitation_id'), 
            t.get('assigned_role_id')
        )
        tickets.append(ticket_tuple)

    # Get habilitations for qualification
    habilitations_data = db.get_all_habilitations()
    habilitations = [(h['id'], h['nom'], h['categorie']) for h in habilitations_data]

    # Get current role habilitations for resolve permission
    role_hab_ids = set()
    if role_name in ROLE_ORDER + ['N2'] and current_role_id:
        role_habilitations = db.get_role_habilitations(current_role_id)
        role_hab_ids = {h['id'] for h in role_habilitations}
    return render_template('resoudre_tickets.html', tickets=tickets, habilitations=habilitations, role_name=role_name, role_hab_ids=role_hab_ids)

# ---- Gestion des tickets (Admin only) ----
@app.route('/gestion-tickets')
def gestion_tickets():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get all tickets with user and status information
    tickets_data = db.get_all_tickets()
    tickets = []
    for t in tickets_data:
        tickets.append((
            t['id'], 
            t['titre'], 
            t['utilisateur']['nom_utilisateur'], 
            t['description'], 
            t['date_creation'],
            t['statut']['nom'], 
            t.get('required_habilitation_id'), 
            t.get('assigned_role_id'),
            t['utilisateur'].get('prenom', ''), 
            t['utilisateur'].get('nom', '')
        ))
    
    # Get all data for dropdowns
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    users_data = db.get_all_users()
    users = [(u['id'], u['nom_utilisateur'], u.get('prenom', ''), u.get('nom', '')) for u in users_data]
    
    categories_data = db.get_all_categories()
    categories = [(c['id'], c['nom']) for c in categories_data]
    
    types_data = db.get_all_types()
    types = [(t['id'], t['nom']) for t in types_data]
    
    return render_template('gestion_tickets.html', tickets=tickets, statuts=statuts, users=users, categories=categories, types=types)

@app.route('/ajouter-ticket-admin', methods=['GET', 'POST'])
def ajouter_ticket_admin():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get data for dropdowns
    categories_data = db.get_all_categories()
    categories = [(c['id'], c['nom']) for c in categories_data]
    
    types_data = db.get_all_types()
    types = [(t['id'], t['nom']) for t in types_data]
    
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    users_data = db.get_all_users()
    users = [(u['id'], u['nom_utilisateur'], u.get('prenom', ''), u.get('nom', '')) for u in users_data]
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        statut_id = request.form.get('statut')
        user_id = request.form.get('user_id')
        
        # Get status ID - use provided statut_id or default to 'Incident déclaré'
        if statut_id:
            final_statut_id = int(statut_id)
        else:
            final_statut_id = db.get_status_by_name('Incident déclaré')
            if not final_statut_id:
                flash('Statut "Incident déclaré" non trouvé dans la base de données.', 'error')
                return redirect(url_for('ajouter_ticket_admin'))
        
        # Create ticket data
        ticket_data = {
            'titre': titre,
            'description': description,
            'date_creation': datetime.now().isoformat(),
            'idutilisateur': int(user_id) if user_id else None,
            'categorie_id': int(categorie_id) if categorie_id else None,
            'type_id': int(type_id) if type_id else None,
            'statut_id': final_statut_id
        }
        
        # Create ticket
        ticket = db.create_ticket(ticket_data)
        if ticket:
            flash('Ticket créé avec succès !', 'success')
        else:
            flash('Erreur lors de la création du ticket', 'error')
        
        return redirect(url_for('gestion_tickets'))
    
    return render_template('ajouter_ticket_admin.html', categories=categories, types=types, statuts=statuts, users=users)

@app.route('/modifier-ticket/<int:ticket_id>', methods=['GET', 'POST'])
def modifier_ticket(ticket_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get data for dropdowns
    categories_data = db.get_all_categories()
    categories = [(c['id'], c['nom']) for c in categories_data]
    
    types_data = db.get_all_types()
    types = [(t['id'], t['nom']) for t in types_data]
    
    statuts_data = db.get_all_statuses()
    statuts = [(s['id'], s['nom']) for s in statuts_data]
    
    users_data = db.get_all_users()
    users = [(u['id'], u['nom_utilisateur'], u.get('prenom', ''), u.get('nom', '')) for u in users_data]
    
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        categorie_id = request.form.get('categorie')
        type_id = request.form.get('type')
        statut_id = request.form.get('statut')
        user_id = request.form.get('user_id')
        
        # Update ticket data
        ticket_data = {
            'titre': titre,
            'description': description,
            'categorie_id': int(categorie_id) if categorie_id else None,
            'type_id': int(type_id) if type_id else None,
            'statut_id': int(statut_id) if statut_id else None,
            'idutilisateur': int(user_id) if user_id else None
        }
        
        # Update ticket
        ticket = db.update_ticket(ticket_id, ticket_data)
        if ticket:
            flash('Ticket modifié avec succès !', 'success')
        else:
            flash('Erreur lors de la modification du ticket', 'error')
        
        return redirect(url_for('gestion_tickets'))
    
    # Get current ticket data
    ticket_data = db.get_ticket_by_id(ticket_id)
    if not ticket_data:
        flash('Ticket non trouvé.', 'error')
        return redirect(url_for('gestion_tickets'))
    
    # Format ticket data for template
    ticket = (
        ticket_data['id'],
        ticket_data['titre'],
        ticket_data['description'],
        ticket_data.get('categorie_id'),
        ticket_data.get('type_id'),
        ticket_data.get('statut_id'),
        ticket_data.get('idutilisateur'),
        ticket_data['utilisateur']['nom_utilisateur'],
        ticket_data['utilisateur'].get('prenom', ''),
        ticket_data['utilisateur'].get('nom', '')
    )
    
    return render_template('modifier_ticket.html', ticket=ticket, categories=categories, types=types, statuts=statuts, users=users)

@app.route('/supprimer-ticket/<int:ticket_id>', methods=['POST'])
def supprimer_ticket(ticket_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Delete ticket
    success = db.delete_ticket(ticket_id)
    if success:
        flash('Ticket supprimé avec succès !', 'success')
    else:
        flash('Erreur lors de la suppression du ticket', 'error')
    
    return redirect(url_for('gestion_tickets'))

@app.route('/tickets/<int:ticket_id>/qualifier', methods=['POST'])
def qualifier_ticket(ticket_id: int):
    if 'user_id' not in session or session.get('user_role') != 'N1':
        return redirect(url_for('login'))
    
    required_hab_id = request.form.get('habilitation_id')
    if not required_hab_id:
        flash('Veuillez sélectionner une habilitation.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Get status ID for 'Incident pris en charge'
    statut_id = db.get_status_by_name('Incident pris en charge')
    if not statut_id:
        flash('Statut non trouvé.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Update ticket with required habilitation and status
    success = db.update_ticket(ticket_id, {
        'required_habilitation_id': int(required_hab_id),
        'statut_id': statut_id
    })
    
    if success:
        flash('Qualification enregistrée.', 'success')
    else:
        flash('Erreur lors de la qualification.', 'error')
    
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
    if not next_role_id:
        flash('Rôle suivant introuvable.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Get status ID for 'Incident pris en charge'
    statut_id = db.get_status_by_name('Incident pris en charge')
    if not statut_id:
        flash('Statut non trouvé.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Update ticket with new assigned role and status
    success = db.update_ticket(ticket_id, {
        'assigned_role_id': next_role_id,
        'statut_id': statut_id
    })
    
    if success:
        flash(f'Ticket escaladé vers {next_role}.', 'success')
    else:
        flash('Erreur lors de l\'escalade.', 'error')
    
    return redirect(url_for('resoudre_tickets'))

@app.route('/tickets/<int:ticket_id>/resoudre', methods=['POST'])
def resoudre_ticket(ticket_id: int):
    if 'user_id' not in session or session.get('user_role') not in ROLE_ORDER + ['N2']:
        return redirect(url_for('login'))
    
    role_name = current_role_name()
    
    # Get ticket data
    ticket_data = db.get_ticket_by_id(ticket_id)
    if not ticket_data:
        flash('Ticket non trouvé.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    required_hab_id = ticket_data.get('required_habilitation_id')
    attempts = ticket_data.get('resolution_attempts', 0)
    
    # Check if user can resolve this ticket
    allowed = False
    if role_name == 'N4':
        allowed = True
    elif required_hab_id is not None:
        # Check if role has the required habilitation
        role_id = get_role_id_by_name(role_name)
        if role_id:
            allowed = db.check_role_has_habilitation(role_id, required_hab_id)
    
    if not allowed:
        flash("Vous n'avez pas l'habilitation requise pour résoudre ce ticket.", 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Get status ID for 'Incident en cours de résolution'
    statut_id = db.get_status_by_name('Incident en cours de résolution')
    if not statut_id:
        flash('Statut non trouvé.', 'error')
        return redirect(url_for('resoudre_tickets'))
    
    # Calculate resolution due time
    minutes = RESOLUTION_MINUTES_BY_ROLE.get(role_name, 2)
    due_at = datetime.now() + timedelta(minutes=minutes)
    
    # Update ticket with resolution status and due time
    success = db.update_ticket(ticket_id, {
        'statut_id': statut_id,
        'date_mise_a_jour': datetime.now().isoformat(),
        'resolution_due_at': due_at.isoformat(),
        'resolution_attempts': attempts + 1
    })
    
    if success:
        flash(f'Ticket en résolution ({minutes} min).', 'success')
    else:
        flash('Erreur lors de la mise en résolution.', 'error')
    
    return redirect(url_for('resoudre_tickets'))

# Endpoints for requester validation
@app.route('/tickets/<int:ticket_id>/valider', methods=['POST'])
def valider_ticket(ticket_id: int):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Only the creator can validate/refuse
    ticket_data = db.get_ticket_by_id(ticket_id)
    if not ticket_data or ticket_data.get('idutilisateur') != session['user_id']:
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
    
    # Get status ID for 'Incident clos'
    statut_id = db.get_status_by_name('Incident clos')
    if not statut_id:
        flash('Statut non trouvé.', 'error')
        return redirect(url_for('dashboard_initial'))
    
    # Update ticket with closed status
    success = db.update_ticket(ticket_id, {
        'statut_id': statut_id,
        'date_cloture': datetime.now().isoformat()
    })
    
    if success:
        flash('Ticket clôturé avec succès.', 'success')
    else:
        flash('Erreur lors de la clôture.', 'error')
    
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
    ticket_data = db.get_ticket_by_id(ticket_id)
    if not ticket_data or ticket_data.get('idutilisateur') != session['user_id']:
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
    
    titre = ticket_data.get('titre', '')
    new_title = (titre + ' [Retour - solution non concluante]').strip()
    
    # Get status ID for 'Incident déclaré'
    statut_id = db.get_status_by_name('Incident déclaré')
    if not statut_id:
        flash('Statut non trouvé.', 'error')
        return redirect(url_for('dashboard_initial'))
    
    # Get N1 role ID for reassignment
    n1_role_id = get_role_id_by_name('N1')
    
    # Reset ticket to initial state
    success = db.update_ticket(ticket_id, {
        'statut_id': statut_id,
        'titre': new_title,
        'resolution_due_at': None,
        'required_habilitation_id': None,
        'assigned_role_id': n1_role_id
    })
    
    if success:
        flash('Ticket renvoyé pour nouveau traitement.', 'success')
    else:
        flash('Erreur lors du renvoi.', 'error')
    
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
    
    # Get all users with role information
    users_data = db.get_all_users()
    users = []
    for u in users_data:
        users.append((
            u['id'],
            u['nom_utilisateur'],
            u['email'],
            u.get('prenom', ''),
            u.get('nom', ''),
            u['role']['nom'] if u.get('role') else 'N/A'
        ))
    
    return render_template('gestion_utilisateurs.html', users=users)

@app.route('/ajouter-utilisateur', methods=['GET', 'POST'])
def ajouter_utilisateur():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get all roles
    roles_data = db.get_all_roles()
    roles = [(r['id'], r['nom'], r.get('description', '')) for r in roles_data]
    
    if request.method == 'POST':
        nom_utilisateur = request.form['nom_utilisateur']
        email = request.form['email']
        mot_de_passe = request.form['mot_de_passe']
        prenom = request.form['prenom']
        nom = request.form['nom']
        role_id = request.form['role_id']
        
        # Check if username already exists
        users = db.get_all_users()
        for user in users:
            if user['nom_utilisateur'] == nom_utilisateur:
                flash('Ce nom d\'utilisateur existe déjà.', 'error')
                return render_template('ajouter_utilisateur.html', roles=roles)
            if user['email'] == email:
                flash('Cette adresse e-mail existe déjà.', 'error')
                return render_template('ajouter_utilisateur.html', roles=roles)
        
        # Create user data
        user_data = {
            'nom_utilisateur': nom_utilisateur,
            'email': email,
            'mot_de_passe': mot_de_passe,
            'prenom': prenom,
            'nom': nom,
            'role_id': int(role_id)
        }
        
        # Create user
        user = db.create_user(user_data)
        if user:
            flash('Utilisateur ajouté avec succès !', 'success')
            return redirect(url_for('gestion_utilisateurs'))
        else:
            flash('Erreur lors de la création de l\'utilisateur', 'error')
    
    return render_template('ajouter_utilisateur.html', roles=roles)

@app.route('/modifier-utilisateur/<int:user_id>', methods=['GET', 'POST'])
def modifier_utilisateur(user_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get roles for dropdown
    roles_data = db.get_all_roles()
    roles = [(r['id'], r['nom'], r.get('description', '')) for r in roles_data]
    
    if request.method == 'POST':
        nom_utilisateur = request.form['nom_utilisateur']
        email = request.form['email']
        prenom = request.form['prenom']
        nom = request.form['nom']
        role_id = request.form['role_id']
        mot_de_passe = request.form.get('mot_de_passe', '')
        
        # Check if username already exists (excluding current user)
        users = db.get_all_users()
        for user in users:
            if user['id'] != user_id:
                if user['nom_utilisateur'] == nom_utilisateur:
                    flash('Ce nom d\'utilisateur existe déjà.', 'error')
                    return redirect(url_for('modifier_utilisateur', user_id=user_id))
                if user['email'] == email:
                    flash('Cette adresse e-mail existe déjà.', 'error')
                    return redirect(url_for('modifier_utilisateur', user_id=user_id))
        
        # Prepare update data
        user_data = {
            'nom_utilisateur': nom_utilisateur,
            'email': email,
            'prenom': prenom,
            'nom': nom,
            'role_id': int(role_id)
        }
        
        # Include password if provided
        if mot_de_passe:
            user_data['mot_de_passe'] = mot_de_passe
        
        # Update user
        user = db.update_user(user_id, user_data)
        if user:
            flash('Utilisateur modifié avec succès !', 'success')
        else:
            flash('Erreur lors de la modification de l\'utilisateur', 'error')
        
        return redirect(url_for('gestion_utilisateurs'))
    
    # Get user data for editing
    user_data = db.get_user_by_id(user_id)
    if not user_data:
        flash('Utilisateur non trouvé.', 'error')
        return redirect(url_for('gestion_utilisateurs'))
    
    # Format user data for template
    user = (
        user_data['id'],
        user_data['nom_utilisateur'],
        user_data['email'],
        user_data.get('prenom', ''),
        user_data.get('nom', ''),
        user_data.get('role_id'),
        user_data['role']['nom'] if user_data.get('role') else 'N/A'
    )
    
    return render_template('modifier_utilisateur.html', user=user, roles=roles)

@app.route('/supprimer-utilisateur/<int:user_id>', methods=['POST'])
def supprimer_utilisateur(user_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Prevent admin from deleting themselves
    if user_id == session['user_id']:
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'error')
        return redirect(url_for('gestion_utilisateurs'))
    
    # Check if user has any tickets
    ticket_count = db.get_user_count(user_id)
    if ticket_count > 0:
        flash('Impossible de supprimer cet utilisateur car il a des tickets associés.', 'error')
        return redirect(url_for('gestion_utilisateurs'))
    
    # Delete user
    success = db.delete_user(user_id)
    if success:
        flash('Utilisateur supprimé avec succès !', 'success')
    else:
        flash('Erreur lors de la suppression de l\'utilisateur', 'error')
    
    return redirect(url_for('gestion_utilisateurs'))

# Habilitation Management Routes
@app.route('/gestion-habilitations')
def gestion_habilitations():
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get all roles
    roles_data = db.get_all_roles()
    roles = [(r['id'], r['nom'], r.get('description', '')) for r in roles_data]
    
    return render_template('gestion_habilitations.html', roles=roles)

@app.route('/gestion-habilitations/<int:role_id>')
def gestion_habilitations_role(role_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    # Get role info (fix: query role table, not users)
    role_data = db.get_role_by_id(role_id)
    if not role_data:
        flash('Rôle non trouvé.', 'error')
        return redirect(url_for('gestion_habilitations'))
    
    # Get current habilitations for this role
    current_habilitations_data = db.get_role_habilitations(role_id)
    current_habilitations = [(h['id'], h['nom'], h.get('description', ''), h.get('categorie', '')) 
                            for h in current_habilitations_data]
    
    # Get all available habilitations
    all_habilitations_data = db.get_all_habilitations()
    all_habilitations = [(h['id'], h['nom'], h.get('description', ''), h.get('categorie', '')) 
                        for h in all_habilitations_data]
    
    # Format role data for template
    role = (role_data['id'], role_data['nom'], role_data.get('description', ''))
    
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
    
    # Check if habilitation is already assigned to this role
    if db.check_role_has_habilitation(role_id, int(habilitation_id)):
        flash('Cette habilitation est déjà assignée à ce rôle.', 'error')
        return redirect(url_for('gestion_habilitations_role', role_id=role_id))
    
    # Add habilitation to role
    try:
        result = db._make_request("POST", "role_habilitation", data={
            'role_id': role_id,
            'habilitation_id': int(habilitation_id)
        })
        flash('Habilitation ajoutée au rôle avec succès !', 'success')
    except Exception as e:
        flash('Erreur lors de l\'ajout de l\'habilitation.', 'error')
    
    return redirect(url_for('gestion_habilitations_role', role_id=role_id))

@app.route('/supprimer-habilitation-role/<int:role_id>/<int:habilitation_id>', methods=['POST'])
def supprimer_habilitation_role(role_id, habilitation_id):
    if 'user_id' not in session or session.get('user_role') != 'N2':
        return redirect(url_for('login'))
    
    try:
        db._make_request("DELETE", f"role_habilitation?role_id=eq.{role_id}&habilitation_id=eq.{habilitation_id}")
        flash('Habilitation supprimée du rôle avec succès !', 'success')
    except Exception as e:
        flash('Erreur lors de la suppression de l\'habilitation.', 'error')
    
    return redirect(url_for('gestion_habilitations_role', role_id=role_id))

if __name__ == '__main__':
    app.run(debug=True) 