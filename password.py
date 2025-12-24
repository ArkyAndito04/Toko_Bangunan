from werkzeug.security import generate_password_hash

# Ini akan menghasilkan kode panjang yang aman
print(generate_password_hash('123'))