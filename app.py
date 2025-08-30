# app.py
import os
import sqlite3
from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from werkzeug.security import generate_password_hash, check_password_hash
import requests

app = Flask(__name__)
app.secret_key = "roszCmDpQe5vmoXVq9Fj2qUmlPI2ni1rZLabHGgSEEM"

UNSPLASH_ACCESS_KEY = "mQe-BaNozRiF2x1x43bvrRIAOAZAPuHW57bZyAz-5xE"

DB_PATH = "app.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS likes (
                user_id INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                PRIMARY KEY(user_id, image_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()

init_db()

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE id=?", (uid,))
        user = c.fetchone()
        return user

@app.route("/")
def index():
    user = current_user()
    return render_template("index.html", user=user)

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    password_hash = generate_password_hash(password)
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400

    return jsonify({"message": "User registered successfully"})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, password_hash FROM users WHERE username=?", (username,))
        user = c.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid username or password"}), 401

        session["user_id"] = user["id"]
    return jsonify({"message": "Logged in successfully", "username": username})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/api/search")
def search_images():
    query = request.args.get("query", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    headers = {
        "Accept-Version": "v1",
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"
    }
    params = {
        "query": query or "random",
        "page": page,
        "per_page": per_page,
    }
    url = "https://api.unsplash.com/search/photos"
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch images"}), 500
    data = response.json()

    image_ids = [img["id"] for img in data.get("results", [])]

    with get_db() as conn:
        c = conn.cursor()
        user = current_user()
        user_liked_ids = set()
        if user and image_ids:
            format_ids = ",".join("?" for _ in image_ids)
            c.execute(f"SELECT image_id FROM likes WHERE user_id=? AND image_id IN ({format_ids})", (user["id"], *image_ids))
            user_liked_ids = {row["image_id"] for row in c.fetchall()}

    results = []
    for image in data.get("results", []):
        iid = image["id"]
        results.append({
            "id": iid,
            "description": image["description"] or image["alt_description"] or "",
            "thumb_url": image["urls"]["small"],
            "full_url": image["urls"]["full"],
            "download_url": image["links"]["download"],
            "liked_by_user": iid in user_liked_ids
        })

    return jsonify({
        "results": results,
        "total": data.get("total", 0),
        "total_pages": data.get("total_pages", 1),
        "page": page
    })

@app.route("/api/like", methods=["POST"])
def like_image():
    user = current_user()
    if not user:
        return jsonify({"error": "User not logged in"}), 401

    data = request.json
    image_id = data.get("image_id")
    if not image_id:
        return jsonify({"error": "image_id required"}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM likes WHERE user_id=? AND image_id=?", (user["id"], image_id))
        if c.fetchone():
            return jsonify({"error": "Already liked"}), 400
        c.execute("INSERT INTO likes (user_id, image_id) VALUES (?, ?)", (user["id"], image_id))
        conn.commit()

    return jsonify({"image_id": image_id, "liked_by_user": True})

@app.route("/api/unlike", methods=["POST"])
def unlike_image():
    user = current_user()
    if not user:
        return jsonify({"error": "User not logged in"}), 401

    data = request.json
    image_id = data.get("image_id")
    if not image_id:
        return jsonify({"error": "image_id required"}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM likes WHERE user_id=? AND image_id=?", (user["id"], image_id))
        conn.commit()

    return jsonify({"image_id": image_id, "liked_by_user": False})

@app.route("/api/liked")
def liked_images():
    user = current_user()
    if not user:
        return jsonify({"error": "User not logged in"}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT image_id FROM likes WHERE user_id=?", (user["id"],))
        liked_ids = [row["image_id"] for row in c.fetchall()]

    if not liked_ids:
        return jsonify({"results": [], "total": 0})

    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    results = []
    for image_id in liked_ids:
        url = f"https://api.unsplash.com/photos/{image_id}"
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            image = resp.json()
            results.append({
                "id": image["id"],
                "description": image["description"] or image["alt_description"] or "",
                "thumb_url": image["urls"]["small"],
                "full_url": image["urls"]["full"],
                "download_url": image["links"]["download"],
                "liked_by_user": True
            })

    return jsonify({"results": results, "total": len(results)})

@app.route("/api/download")
def download_image():
    image_url = request.args.get("url")
    if not image_url:
        return jsonify({"error": "url param required"}), 400
    return redirect(image_url)

if __name__ == "__main__":
    app.run(debug=True)
