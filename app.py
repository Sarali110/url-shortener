﻿import string
from flask import Flask, request, redirect, jsonify, render_template
import sqlite3
import time
import redis
import traceback

# --- Short ID Encoder ---
class IDEncoder:
    def __init__(self):
        self.alphabet = ['a','1','c','2','e'] #string.ascii_letters + string.digits  # a-zA-Z0-9
        self.base = len(self.alphabet)

    def encode(self, num):
        s = []
        while num > 0:
            s.append(self.alphabet[num % self.base])
            num //= self.base
        return ''.join(reversed(s)) or '0'

    def decode(self, short_id):
        num = 0
        for char in short_id:
            num = num * self.base + self.alphabet.index(char)
        return num

# --- App Setup ---
app = Flask(__name__)
encoder = IDEncoder()

# --- SQLite Setup ---
conn = sqlite3.connect('urls.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS urls
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              short_id TEXT UNIQUE,
              long_url TEXT,
              created_at INTEGER,
              click_count INTEGER DEFAULT 0)''')
conn.commit()

# --- Redis Setup ---
r = redis.from_url(
    "rediss://default:AX-CAAIjcDExMjk5ODFlODVmMGE0YjdmYWJhYWIyMmE5MTk4M2FiMXAxMA@known-anemone-32642.upstash.io:6379",
    decode_responses=True
)

# --- Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/shorten', methods=['POST'])
def shorten():
    try:
        data = request.get_json(force=True)
        if not data or 'url' not in data:
            return jsonify({'error': 'Missing "url" in request'}), 400

        long_url = data['url']
        if not long_url.startswith(('http://', 'https://')):
            long_url = 'http://' + long_url
        created_at = int(time.time())

        c.execute("INSERT INTO urls (long_url, created_at) VALUES (?, ?)", (long_url, created_at))
        new_id = c.lastrowid
        short_id = encoder.encode(new_id)
        c.execute("UPDATE urls SET short_id = ? WHERE id = ?", (short_id, new_id))
        conn.commit()

        r.set(short_id, long_url)

        host_url = request.host_url.rstrip('/')  # Ensure no trailing slash
        return jsonify({'short_url': f"{host_url}/{short_id}"})

    except Exception as e:
        print("---- ERROR ----")
        print(f"Exception occurred: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/<short_id>')
def redirect_url(short_id):
    long_url = r.get(short_id)
    if not long_url:
        c.execute("SELECT long_url FROM urls WHERE short_id = ?", (short_id,))
        row = c.fetchone()
        if row:
            long_url = row[0]
            r.set(short_id, long_url)
        else:
            return "Not Found", 404

    c.execute("UPDATE urls SET click_count = click_count + 1 WHERE short_id = ?", (short_id,))
    conn.commit()
    return redirect(long_url)

@app.route('/top')
def top_urls():
    c.execute("SELECT short_id, long_url, click_count FROM urls ORDER BY click_count DESC LIMIT 10")
    rows = c.fetchall()
    top_data = [
        {
            'short_url': f"{request.host_url}{row[0]}",
            'long_url': row[1],
            'click_count': row[2]
        }
        for row in rows
    ]
    return jsonify(top_data)

@app.route('/stats/<short_id>')
def stats(short_id):
    c.execute("SELECT long_url, created_at, click_count FROM urls WHERE short_id = ?", (short_id,))
    row = c.fetchone()
    if row:
        return jsonify({
            'short_id': short_id,
            'long_url': row[0],
            'created_at': row[1],
            'click_count': row[2]
        })
    else:
        return jsonify({'error': 'Short ID not found'}), 404