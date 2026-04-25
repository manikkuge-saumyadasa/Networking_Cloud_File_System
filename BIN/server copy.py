"""
CSC474/574 Cloud File System - TCP Socket + Web Server
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

BASE_STORAGE = Path("storage")
BASE_STORAGE.mkdir(exist_ok=True)
USERS_FILE = Path("users.json")
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE


# ── Helpers ────────────────────────────────────────────────────────────────

def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def user_root(username):
    path = BASE_STORAGE / secure_filename(username)
    path.mkdir(parents=True, exist_ok=True)
    return path

def resolve_path(username, rel_path):
    """
    Safely resolve a relative path inside the user's root.
    Returns (Path, error_string). Prevents directory traversal.
    """
    root = user_root(username)  # get user's root directory

    parts = [p for p in rel_path.replace("\\", "/").split("/") if p and p != "."]  # normalize and split path
    safe_parts = []  # sanitized path components

    for p in parts:
        if p == "..":  # handle parent directory navigation
            if safe_parts:
                safe_parts.pop()  # move one level up safely
        else:
            safe_parts.append(secure_filename(p))  # sanitize each segment

    resolved = root  # start from root directory

    for p in safe_parts:
        if p:
            resolved = resolved / p  # build final path

    try:
        resolved.relative_to(root)  # ensure path stays within root
    except ValueError:
        return None, "Access denied"  # block directory traversal attempt

    return resolved, None  # return safe resolved path

def format_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def build_tree_lines(directory, prefix=""):
    """Return a simple ASCII tree view for directory contents."""
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = []

    for idx, entry in enumerate(entries):
        is_last = idx == len(entries) - 1
        branch = "\\-- " if is_last else "+-- "
        child_prefix = prefix + ("    " if is_last else "|   ")

        if entry.is_dir():
            lines.append(f"{prefix}{branch}[D] {entry.name}/")
            lines.extend(build_tree_lines(entry, child_prefix))
        else:
            lines.append(f"{prefix}{branch}[F] {entry.name}")

    return lines


# ── User routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/users", methods=["GET"])
def list_users():
    return jsonify({"users": list(load_users().keys())})

@app.route("/api/users", methods=["POST"])
def create_or_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    if not username or len(username) < 2:
        return jsonify({"error": "Username must be at least 2 characters"}), 400
    if len(username) > 32:
        return jsonify({"error": "Username too long (max 32 chars)"}), 400
    if not username.replace("_", "").replace("-", "").isalnum():
        return jsonify({"error": "Only letters, numbers, - and _ allowed"}), 400

    users = load_users()
    if username in users:
        return jsonify({"message": f"Welcome back, {username}!", "username": username})

    users[username] = {"created": datetime.now().isoformat()}
    save_users(users)
    user_root(username)
    return jsonify({"message": f"Account created!", "username": username}), 201


# ── List directory ─────────────────────────────────────────────────────────

@app.route("/api/list/<username>")
def list_directory(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    rel = request.args.get("path", "/")
    target, err = resolve_path(username, rel)
    if err:
        return jsonify({"error": err}), 403
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "Directory not found"}), 404

    dirs, files, total_size = [], [], 0

    for item in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        stat = item.stat()
        ts = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M")
        if item.is_dir():
            dirs.append({"name": item.name, "type": "dir", "modified": ts})
        else:
            sz = stat.st_size
            total_size += sz
            files.append({
                "name": item.name, "type": "file",
                "size": sz, "size_fmt": format_size(sz),
                "ext": item.suffix.lstrip(".").upper() or "FILE",
                "modified": ts
            })

    # Breadcrumbs
    root = user_root(username)
    try:
        rel_parts = target.relative_to(root).parts
        crumbs = [{"name": "Home", "path": "/"}]
        cur = Path("/")
        for part in rel_parts:
            cur = cur / part
            crumbs.append({"name": part, "path": str(cur).replace("\\", "/")})
    except ValueError:
        crumbs = [{"name": "Home", "path": "/"}]

    # All user dirs for move target picker
    all_dirs = ["/"]
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            try:
                rp = "/" + str(p.relative_to(root)).replace("\\", "/")
                all_dirs.append(rp)
            except ValueError:
                pass

    return jsonify({
        "path": rel,
        "breadcrumbs": crumbs,
        "dirs": dirs,
        "files": files,
        "total_files": len(files),
        "total_size": format_size(total_size),
        "all_dirs": all_dirs
    })


# ── Text tree diagram ─────────────────────────────────────────────────────

@app.route("/api/tree/<username>")
def directory_tree(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    rel = request.args.get("path", "/")
    target, err = resolve_path(username, rel)
    if err:
        return jsonify({"error": err}), 403
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "Directory not found"}), 404

    root_label = target.name or secure_filename(username)
    lines = [f"[D] {root_label}/"]
    lines.extend(build_tree_lines(target))

    return jsonify({"path": rel, "diagram": "\n".join(lines)})


# ── Create directory ───────────────────────────────────────────────────────

@app.route("/api/mkdir/<username>", methods=["POST"])
def make_directory(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    parent = data.get("path", "/")
    name = secure_filename(data.get("name", "").strip())
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400

    parent_path, err = resolve_path(username, parent)
    if err:
        return jsonify({"error": err}), 403
    if not parent_path.is_dir():
        return jsonify({"error": "Parent not found"}), 404

    new_dir = parent_path / name
    if new_dir.exists():
        return jsonify({"error": "Folder already exists"}), 409

    new_dir.mkdir()
    return jsonify({"message": f'Folder "{name}" created'})


# ── Upload ─────────────────────────────────────────────────────────────────

@app.route("/api/upload/<username>", methods=["POST"])
def upload_file(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    rel = request.form.get("path", "/")
    target, err = resolve_path(username, rel)
    if err:
        return jsonify({"error": err}), 403
    if not target.is_dir():
        return jsonify({"error": "Target directory not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    saved = []
    for file in request.files.getlist("file"):
        if not file.filename:
            continue
        filename = secure_filename(file.filename)
        if filename:
            file.save(target / filename)
            saved.append(filename)

    if not saved:
        return jsonify({"error": "No valid files"}), 400
    return jsonify({"message": f"Uploaded {len(saved)} file(s)", "files": saved})


# ── Download ───────────────────────────────────────────────────────────────

@app.route("/api/download/<username>")
def download_file(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    rel = request.args.get("path", "")
    if not rel:
        return jsonify({"error": "No path specified"}), 400

    file_path, err = resolve_path(username, rel)
    if err:
        return jsonify({"error": err}), 403
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "File not found"}), 404

    return send_from_directory(file_path.parent.resolve(), file_path.name, as_attachment=True)


# ── Delete ─────────────────────────────────────────────────────────────────

@app.route("/api/delete/<username>", methods=["DELETE"])
def delete_item(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    rel = data.get("path", "")
    if not rel or rel == "/":
        return jsonify({"error": "Cannot delete root"}), 400

    item_path, err = resolve_path(username, rel)
    if err:
        return jsonify({"error": err}), 403
    if not item_path.exists():
        return jsonify({"error": "Not found"}), 404
    if item_path == user_root(username):
        return jsonify({"error": "Cannot delete root"}), 400

    if item_path.is_dir():
        shutil.rmtree(item_path)
    else:
        item_path.unlink()

    return jsonify({"message": f'"{item_path.name}" deleted'})


# ── Move ───────────────────────────────────────────────────────────────────

@app.route("/api/move/<username>", methods=["POST"])
def move_item(username):
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    src_rel = data.get("src", "")
    dst_rel = data.get("dst", "")
    if not src_rel or not dst_rel:
        return jsonify({"error": "src and dst required"}), 400

    src, err = resolve_path(username, src_rel)
    if err or not src.exists():
        return jsonify({"error": "Source not found"}), 404

    dst_dir, err = resolve_path(username, dst_rel)
    if err or not dst_dir.is_dir():
        return jsonify({"error": "Destination directory not found"}), 404

    dest = dst_dir / src.name
    if dest.exists():
        return jsonify({"error": f'"{src.name}" already exists in destination'}), 409

    shutil.move(str(src), str(dest))
    return jsonify({"message": f'"{src.name}" moved'})


# ── Rename ─────────────────────────────────────────────────────────────────

@app.route("/api/rename/<username>", methods=["POST"])  # API endpoint to rename a file/folder for a user
def rename_item(username):
    if username not in load_users():  # check if user exists
        return jsonify({"error": "User not found"}), 404  # return 404 if invalid user

    data = request.json or {}  # get JSON payload safely
    src_rel = data.get("path", "")  # original relative path
    new_name = secure_filename(data.get("name", "").strip())  # sanitize new name

    if not src_rel or not new_name:  # validate required fields
        return jsonify({"error": "path and name required"}), 400  # bad request

    src, err = resolve_path(username, src_rel)  # resolve absolute source path
    if err or not src.exists():  # check resolution and existence
        return jsonify({"error": "Not found"}), 404  # file/folder missing

    dest = src.parent / new_name  # build destination path
    if dest.exists():  # prevent overwriting existing item
        return jsonify({"error": "Name already taken"}), 409  # conflict error

    src.rename(dest)  # perform rename operation
    return jsonify({"message": f'Renamed to "{new_name}"'})  # success response


# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  CSC474/574 Cloud File System")
    print("  http://0.0.0.0:8080")
    print("=" * 50)
    # Start the Flask web server
    # ─────────────────────────────────────────────────────────────────────
    # SOCKET:
    #   When this runs, Flask (via Werkzeug) creates a TCP socket in the OS.
    #   The socket is what actually sends/receives data between client and server.
    #
    # TCP:
    #   All HTTP communication from browsers happens over TCP.
    #   TCP ensures reliable, ordered delivery of requests/responses.
    #
    # PORT (8080):
    #   The socket is "bound" to port 8080.
    #   This means any request sent to this machine on port 8080 will be
    #   delivered to this server process.
    #
    # HOST = "0.0.0.0":
    #   Listen on ALL network interfaces (localhost, LAN, Tailscale, etc.)
    #   So the server is accessible from:
    #     - http://127.0.0.1:8080 (local machine)
    #     - http://<LAN-IP>:8080 (same Wi-Fi network)
    #     - https://<device>.ts.net (via Tailscale routing/proxy)
    #
    # TAILSCALE:
    #   If Tailscale Serve/Funnel is enabled, requests to the .ts.net domain
    #   are forwarded over the Tailscale network and then proxied into this
    #   local socket at 127.0.0.1:8080 (or directly via the same port if exposed).

    app.run(host="0.0.0.0", port=8080, debug=False)
