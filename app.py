from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

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

@app.route('/success')
def success():
    return 'Login successful!'

if __name__ == '__main__':
    app.run(debug=True) 