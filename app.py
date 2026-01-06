from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
import os
from datetime import timedelta

app = Flask(__name__)

# --- PERBAIKAN: SECRET KEY TETAP AGAR SESSION TIDAK RESET DI AZURE ---
app.secret_key = 'maju_jaya_key_permanen_123' 

# --- PERBAIKAN: PROXYFIX UNTUK NANGANIN HTTPS DI AZURE ---
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# --- PERBAIKAN: KONFIGURASI SESSION UNTUK AZURE (B1 TIER) ---
app.config.update(
    SESSION_COOKIE_SECURE=True,    
    SESSION_COOKIE_HTTPONLY=True,  
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=60)
)

# --- KONFIGURASI DATABASE ---
app.config['MYSQL_HOST'] = 'tokobangunan.mysql.database.azure.com'
app.config['MYSQL_USER'] = 'admintoko'
app.config['MYSQL_PASSWORD'] = 'Tokobanguninaja04'
app.config['MYSQL_DB'] = 'toko_bangunan'
app.config['MYSQL_PORT'] = 3306
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# --- KONFIGURASI UPLOAD GAMBAR ---
UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

mysql = MySQL(app)

# --- MIDDLEWARE SEDERHANA (Pengecekan Login) ---
def is_admin():
    return session.get('admin_ok')

def is_logged_in():
    return 'user_id' in session

# --- ROUTE PELANGGAN ---
@app.route('/debug-session')
def debug_session():
    return {
        "session_data": dict(session),
        "is_logged_in": 'user_id' in session,
        "cookie_name": app.config['SESSION_COOKIE_NAME'],
        "permanent": session.permanent
    }
    
@app.route('/')
def index():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM produk WHERE status = 'aktif'")
    produk = cur.fetchall()
    cur.close()
    return render_template('index.html', produk=produk)

@app.route('/login', methods=['GET', 'POST'])
def login_pelanggan():
    if request.method == 'POST':
        hp = request.form['hp']
        pw = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM pelanggan WHERE nomor_hp = %s", [hp])
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user['password'], pw):
            session.permanent = True 
            session['user_id'] = user['id']
            session['user_name'] = user['nama_lengkap']
            session.modified = True 
            return redirect(url_for('index'))
        else:
            flash("Nomor HP atau Password salah!", "danger")
    return render_template('login_pelanggan.html')

@app.route('/daftar', methods=['GET', 'POST'])
def daftar_pelanggan():
    if request.method == 'POST':
        nama = request.form['nama']
        hp = request.form['hp']
        alamat = request.form['alamat']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        
        try:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO pelanggan (nama_lengkap, nomor_hp, alamat, password) VALUES (%s, %s, %s, %s)", 
                        (nama, hp, alamat, hashed_pw))
            mysql.connection.commit()
            cur.close()
            flash("Pendaftaran berhasil, silakan login.", "success")
            return redirect(url_for('login_pelanggan'))
        except Exception as e:
            return f"Error: {str(e)}"
    return render_template('daftar_pelanggan.html')
    
@app.route('/checkout', methods=['POST'])
def checkout():
    if not is_logged_in():
        return jsonify({'status': 'error', 'message': 'Anda harus login dahulu'})
    
    data = request.json
    total = data['total']
    keranjang = data['keranjang'] 
    user_id = session['user_id']

    try:
        cur = mysql.connection.cursor()
        for item in keranjang:
            cur.execute("SELECT nama_produk, status FROM produk WHERE id_produk = %s", [item['id_produk']])
            produk = cur.fetchone()
            if not produk:
                return jsonify({'status': 'error', 'message': f"Produk tidak ditemukan."})
            if produk['status'] == 'dihapus':
                return jsonify({
                    'status': 'error', 
                    'message': f"Maaf, produk '{produk['nama_produk']}' sedang tidak tersedia. Mohon hapus dari keranjang."
                })

        cur.execute("INSERT INTO pesanan (id_pelanggan, total_bayar, status, notif_viewed) VALUES (%s, %s, 'Diproses', 0)", 
                    (user_id, total))
        order_id = cur.lastrowid
        for item in keranjang:
            cur.execute("INSERT INTO detail_pesanan (id_pesanan, id_produk, jumlah, harga_satuan) VALUES (%s, %s, %s, %s)", (order_id, item['id_produk'], item['jumlah'], item['harga']))
            cur.execute("UPDATE produk SET stok = stok - %s WHERE id_produk = %s", (item['jumlah'], item['id_produk']))

        mysql.connection.commit()
        cur.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/histori_pesanan')
def histori_pesanan():
    if not is_logged_in():
        return redirect(url_for('login_pelanggan'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM pesanan WHERE id_pelanggan = %s ORDER BY tanggal_pesanan DESC", [session['user_id']])
    orders = cur.fetchall()
    cur.close()
    return render_template('histori_pesanan.html', orders=orders)

@app.route('/pesanan/detail/<int:id>')
def detail_pesanan_pelanggan(id):
    if not is_logged_in():
        return redirect(url_for('login_pelanggan'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT p.*, c.nama_lengkap FROM pesanan p JOIN pelanggan c ON p.id_pelanggan = c.id WHERE p.id_pesanan = %s AND p.id_pelanggan = %s", (id, session['user_id']))
    pesanan = cur.fetchone()
    if not pesanan:
        cur.close()
        flash("Detail pesanan tidak ditemukan.", "danger")
        return redirect(url_for('histori_pesanan'))
    cur.execute("SELECT d.*, pr.nama_produk FROM detail_pesanan d JOIN produk pr ON d.id_produk = pr.id_produk WHERE d.id_pesanan = %s", [id])
    rincian = cur.fetchall()
    cur.close()
    return render_template('lihat_detail_pelanggan.html', pesanan=pesanan, rincian=rincian)

@app.route('/keranjang')
def keranjang(): return render_template('keranjang.html')

@app.route('/kalkulator')
def kalkulator(): return render_template('kalkulator.html')

@app.route('/profil')
def profil():
    if not is_logged_in(): return redirect(url_for('login_pelanggan'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nama_lengkap, nomor_hp, alamat FROM pelanggan WHERE id = %s", [session['user_id']])
    user = cur.fetchone()
    cur.close()
    return render_template('profil.html', user=user)

@app.route('/profil/update', methods=['POST'])
def update_profil():
    if not is_logged_in(): return redirect(url_for('login_pelanggan'))
    nama, hp, alamat = request.form.get('nama'), request.form.get('hp'), request.form.get('alamat')
    pw_baru = request.form.get('password_baru')
    cur = mysql.connection.cursor()
    if pw_baru and pw_baru.strip() != "":
        cur.execute("UPDATE pelanggan SET nama_lengkap=%s, nomor_hp=%s, alamat=%s, password=%s WHERE id=%s", (nama, hp, alamat, generate_password_hash(pw_baru), session['user_id']))
    else:
        cur.execute("UPDATE pelanggan SET nama_lengkap=%s, nomor_hp=%s, alamat=%s WHERE id=%s", (nama, hp, alamat, session['user_id']))
    mysql.connection.commit()
    cur.close()
    session['user_name'] = nama
    flash("Profil diperbarui!", "success")
    return redirect(url_for('profil'))

# --- AUTH ADMIN ---
@app.route('/admin/login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        user, pw = request.form['user'], request.form['pass']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM admin WHERE username = %s", [user])
        adm = cur.fetchone()
        cur.close()

        if adm and check_password_hash(adm['password'], pw):
            session.permanent = True
            session['admin_ok'] = True
            session['admin_id'] = adm['id_admin'] # Penting untuk identitas admin
            return redirect(url_for('admin'))
        else:
            flash("Username atau Password Admin salah!", "danger")
    return render_template('login_admin.html')

# --- DASHBOARD & MANAJEMEN ADMIN ---
@app.route('/admin')
def admin():
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT p.*, c.nama_lengkap FROM pesanan p JOIN pelanggan c ON p.id_pelanggan = c.id ORDER BY p.tanggal_pesanan DESC")
    orders = cur.fetchall()
    cur.execute("SELECT DATE(tanggal_pesanan) as tgl, SUM(total_bayar) as total FROM pesanan GROUP BY tgl ORDER BY tgl DESC LIMIT 7")
    graph_data = cur.fetchall()
    cur.close()
    return render_template('admin.html', orders=orders, graph_data=graph_data)

# --- PERBAIKAN: KELOLA ADMIN (TAMBAH, UPDATE, HAPUS) ---
@app.route('/admin/kelola_admin')
def kelola_admin():
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT id_admin, username FROM admin")
    admins = cur.fetchall()
    cur.close()
    return render_template('kelola_admin.html', admins=admins)

@app.route('/admin/simpan_admin', methods=['POST'])
def simpan_admin():
    if not is_admin(): return redirect(url_for('login_admin'))
    id_admin, user, pw = request.form.get('id_admin'), request.form.get('username'), request.form.get('password')
    cur = mysql.connection.cursor()
    if id_admin: # Logic Update
        if pw:
            cur.execute("UPDATE admin SET username=%s, password=%s WHERE id_admin=%s", (user, generate_password_hash(pw), id_admin))
        else:
            cur.execute("UPDATE admin SET username=%s WHERE id_admin=%s", (user, id_admin))
    else: # Logic Insert
        cur.execute("INSERT INTO admin (username, password) VALUES (%s, %s)", (user, generate_password_hash(pw)))
    mysql.connection.commit()
    cur.close()
    flash('Data admin berhasil diperbarui!')
    return redirect(url_for('kelola_admin'))

@app.route('/admin/hapus_admin/<int:id>')
def hapus_admin(id):
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM admin WHERE id_admin = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Admin berhasil dihapus!')
    return redirect(url_for('kelola_admin'))

# --- MANAJEMEN PRODUK ---
@app.route('/admin/produk')
def kelola_produk():
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM produk")
    produk = cur.fetchall()
    cur.close()
    return render_template('kelola_produk.html', produk=produk)

@app.route('/tambah_produk', methods=['POST'])
def tambah_produk():
    if not is_admin(): return redirect(url_for('login_admin'))
    nama, harga, stok = request.form['nama_produk'], request.form['harga'], request.form.get('stok', 0)
    file = request.files['gambar']
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO produk (nama_produk, harga, gambar, stok, status) VALUES (%s, %s, %s, %s, 'aktif')", (nama, harga, filename, stok))
        mysql.connection.commit()
        cur.close()
    return redirect(url_for('kelola_produk'))

@app.route('/admin/hapus_produk/<int:id>')
def hapus_produk(id):
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("UPDATE produk SET status = 'dihapus' WHERE id_produk = %s", [id])
    mysql.connection.commit()
    cur.close()
    flash("Produk dinonaktifkan!", "success")
    return redirect(url_for('kelola_produk'))

@app.route('/admin/aktifkan_produk/<int:id>')
def aktifkan_produk(id):
    if not is_admin(): return redirect(url_for('login_admin'))
    cur = mysql.connection.cursor()
    cur.execute("UPDATE produk SET status = 'aktif' WHERE id_produk = %s", [id])
    mysql.connection.commit()
    cur.close()
    flash("Produk diaktifkan kembali!", "success")
    return redirect(url_for('kelola_produk'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
