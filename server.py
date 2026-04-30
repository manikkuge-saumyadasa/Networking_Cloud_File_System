"""
CSC474/574 Cloud File System - Flask Web Server
Provides a REST API for per-user file storage with directory operations.
"""

import shutil                  # High-level file operations: copy, move, delete entire directory trees
from pathlib import Path       # Object-oriented filesystem paths: replaces os.path string manipulation
from datetime import datetime  # Timestamps for file metadata, upload records, logs
from flask import (
    Flask,                     # Core WSGI app: owns the TCP socket, routes HTTP requests
    request,                   # Incoming HTTP request: headers, body, form data, uploaded files
    jsonify,                   # Serializes Python dicts → JSON HTTP responses with correct Content-Type
    render_template,           # Renders Jinja2 HTML templates from the /templates directory
    send_from_directory        # Safely serves a file from a directory as a download/static response
)
import json                    # Serializes/deserializes JSON for reading and writing config or metadata files

# ── Configuration ──────────────────────────────────────────────────────────

BASE_STORAGE = Path("storage")       # root folder holding all user directories
BASE_STORAGE.mkdir(exist_ok=True)    # create it if it doesn't exist yet

USERS_FILE = Path("users.json")      # flat-file "database" of registered users
MAX_FILE_SIZE = 100 * 1024 * 1024    # 100 MB upload limit

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE  # Flask enforces this before hitting route handlers


# ── User persistence helpers ───────────────────────────────────────────────

def load_users():
    """Return the users dict from disk, or {} if the file doesn't exist yet."""
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    """Persist the users dict to disk as formatted JSON."""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


# ── Path helpers ───────────────────────────────────────────────────────────

def user_root(username):
    """Return (and create if needed) the storage directory for this user."""

    # Build a directory path for the user under the base storage path
    path = BASE_STORAGE / username

    # Ensure the directory exists (creates parent folders if needed)
    path.mkdir(parents=True, exist_ok=True)

    # Return the user root directory
    return path


def resolve_path(username, rel_path):
    """
    Resolve a user-supplied relative path inside their storage root.
    Joins the user's root directory with the given relative path.

    Returns:
      (Path, None) on success
      (None, error_str) on failure
    """

    # Get the root directory for this user (creates it if missing)
    root = user_root(username)

    # Join root with the relative path, stripping any leading slash
    resolved = root / rel_path.lstrip("/")

    # Return the resolved path
    return resolved, None


# ── Formatting helpers ─────────────────────────────────────────────────────

def format_size(size_bytes):
    """Convert a byte count to a human-readable string (e.g. '3.2 MB')."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def build_tree_lines(directory, prefix=""):
    """Recursively build ASCII tree lines for a directory."""
    # Sort: directories first, then files, both alphabetically
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = []
    for idx, entry in enumerate(entries):
        is_last = idx == len(entries) - 1
        branch       = "\\-- " if is_last else "+-- "
        child_prefix = prefix + ("    " if is_last else "|   ")
        if entry.is_dir():
            lines.append(f"{prefix}{branch}[D] {entry.name}/")
            lines.extend(build_tree_lines(entry, child_prefix))   # recurse
        else:
            lines.append(f"{prefix}{branch}[F] {entry.name}")
    return lines


# ── User routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Serve the main frontend page
    return render_template("index.html")


@app.route("/api/users", methods=["GET"])
def list_users():
    """Return a list of all registered usernames."""

    # Load stored users and return only their usernames
    return jsonify({"users": list(load_users().keys())})


@app.route("/api/users", methods=["POST"])
def create_or_login():
    """
    Register a new user or log in an existing one.
    Accepts JSON: { "username": "alice" }
    """

    # Parse request JSON safely
    data = request.json or {}
    username = data.get("username", "").strip()

    # Ensure a username was provided
    if not username:
        return jsonify({"error": "Username required"}), 400

    # Load existing users from storage
    users = load_users()

    # If user already exists, treat as login
    if username in users:
        return jsonify({
            "message": f"Welcome back, {username}!",
            "username": username
        })

    # ---- New user creation flow ----

    # Store basic metadata for new user
    users[username] = {
        "created": datetime.now().isoformat()
    }

    # Persist updated user database
    save_users(users)

    # Create user storage directory (if needed)
    user_root(username)

    # Return success response for account creation
    return jsonify({
        "message": "Account created!",
        "username": username
    }), 201


# ── Directory listing ──────────────────────────────────────────────────────

@app.route("/api/list/<username>")
def list_directory(username):
    """
    List the contents of a directory.
    Query param: ?path=/some/folder  (defaults to root "/")
    Returns dirs, files, breadcrumbs, and all known dirs for move picker.
    """

    # Check if the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Resolve requested directory (default to root "/")
    target, err = resolve_path(username, request.args.get("path", "/"))

    # Block access if path resolution fails
    if err:
        return jsonify({"error": err}), 403

    # Ensure target exists and is a directory
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "Directory not found"}), 404

    # Containers for directory listing results
    dirs, files, total_size = [], [], 0

    # Iterate through directory contents
    # Sort: directories first, then files; alphabetically within each group
    for item in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):

        # Get filesystem metadata
        stat = item.stat()

        # Format modification timestamp for display
        ts = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M")

        # Handle directories
        if item.is_dir():
            dirs.append({
                "name": item.name,
                "type": "dir",
                "modified": ts
            })

        # Handle files
        else:
            sz = stat.st_size
            total_size += sz  # accumulate total size of files

            files.append({
                "name": item.name,
                "type": "file",
                "size": sz,
                "size_fmt": format_size(sz),  # human-readable size
                "ext": item.suffix.lstrip(".").upper() or "FILE",
                "modified": ts,
            })

    # ---- Breadcrumb generation ----

    # Get user's root directory
    root = user_root(username)

    try:
        # Get path segments relative to root
        rel_parts = target.relative_to(root).parts

        # Start breadcrumb trail at Home
        crumbs = [{"name": "Home", "path": "/"}]

        # Build incremental path for navigation
        cur = Path("/")
        for part in rel_parts:
            cur = cur / part
            crumbs.append({
                "name": part,
                "path": str(cur).replace("\\", "/")
            })

    except ValueError:
        # Fallback if something goes wrong
        crumbs = [{"name": "Home", "path": "/"}]

    # ---- Build full directory list for "move to" UI ----

    # Include root plus all discovered subdirectories
    all_dirs = ["/"] + [
        "/" + str(p.relative_to(root)).replace("\\", "/")
        for p in sorted(root.rglob("*"))
        if p.is_dir()
    ]

    # Return structured directory listing response
    return jsonify({
        "path": request.args.get("path", "/"),
        "breadcrumbs": crumbs,
        "dirs": dirs,
        "files": files,
        "total_files": len(files),
        "total_size": format_size(total_size),
        "all_dirs": all_dirs,
    })


# ── ASCII directory tree ───────────────────────────────────────────────────

@app.route("/api/tree/<username>")
def directory_tree(username):
    """
    Return an ASCII tree diagram of a directory.
    Query param: ?path=/folder
    """

    # Verify the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Resolve the target directory from query parameter (default to root)
    target, err = resolve_path(username, request.args.get("path", "/"))

    # Block access if path resolution fails
    if err:
        return jsonify({"error": err}), 403

    # Ensure the target exists and is actually a directory
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "Directory not found"}), 404

    # Use directory name if available, otherwise fallback to username
    root_label = target.name or username

    # Build ASCII tree structure:
    # - Root directory line
    # - Recursive child structure from helper function
    lines = [f"[D] {root_label}/"] + build_tree_lines(target)

    # Return JSON response containing the path and formatted ASCII tree
    return jsonify({
        "path": request.args.get("path", "/"),
        "diagram": "\n".join(lines)
    })


# ── Create directory ───────────────────────────────────────────────────────

@app.route("/api/mkdir/<username>", methods=["POST"])
def make_directory(username):
    """
    Create a new sub-directory.
    Body: { "path": "/parent", "name": "new_folder" }
    """

    # Verify the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Parse request JSON safely
    data = request.json or {}

    # Get folder name from request
    name = data.get("name", "").strip()

    # Ensure folder name is valid
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400

    # Resolve parent directory path
    parent, err = resolve_path(username, data.get("path", "/"))

    # Block access if path resolution fails
    if err:
        return jsonify({"error": err}), 403

    # Ensure parent exists and is a directory
    if not parent.is_dir():
        return jsonify({"error": "Parent not found"}), 404

    # Construct full path for new directory
    new_dir = parent / name

    # Prevent overwriting existing directory/file
    if new_dir.exists():
        return jsonify({"error": "Folder already exists"}), 409

    # Create the directory
    new_dir.mkdir()

    # Return success response
    return jsonify({"message": f'Folder "{name}" created'})


# ── Upload ─────────────────────────────────────────────────────────────────

@app.route("/api/upload/<username>", methods=["POST"])
def upload_file(username):
    """
    Upload one or more files into a directory.
    Form fields: path (destination dir), file (one or more file parts)
    """

    # Check if the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Resolve destination directory from form input (default to root "/")
    target, err = resolve_path(username, request.form.get("path", "/"))

    # Block if path resolution fails
    if err:
        return jsonify({"error": err}), 403

    # Ensure target is a valid directory
    if not target.is_dir():
        return jsonify({"error": "Target directory not found"}), 404

    # Ensure at least one file was included in request
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    saved = []  # Track successfully saved filenames

    # Loop through all uploaded files (supports multi-file upload)
    for file in request.files.getlist("file"):

        # Get the original filename as provided by the client
        filename = file.filename or ""

        # Only process valid filenames
        if filename:
            # Save file into target directory
            file.save(target / filename)
            saved.append(filename)

    # If nothing was actually saved, return error
    if not saved:
        return jsonify({"error": "No valid files"}), 400

    # Return success response with list of uploaded files
    return jsonify({
        "message": f"Uploaded {len(saved)} file(s)",
        "files": saved
    })


# ── Download ───────────────────────────────────────────────────────────────

@app.route("/api/download/<username>")
def download_file(username):
    """Serve a file as an attachment. Query param: ?path=/folder/file.txt"""

    # Verify the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Get file path from query parameter
    rel = request.args.get("path", "")

    # Ensure a path was provided
    if not rel:
        return jsonify({"error": "No path specified"}), 400

    # Resolve the requested path within the user's directory
    file_path, err = resolve_path(username, rel)

    # Block access if path resolution fails
    if err:
        return jsonify({"error": err}), 403

    # Ensure the path exists and is a file (not a directory)
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "File not found"}), 404

    # Serve the file as a downloadable attachment
    # send_from_directory requires:
    # - directory (absolute path)
    # - filename
    return send_from_directory(
        file_path.parent.resolve(),
        file_path.name,
        as_attachment=True
    )


# ── Delete ─────────────────────────────────────────────────────────────────

@app.route("/api/delete/<username>", methods=["DELETE"])
def delete_item(username):
    """
    Delete a file or directory (directories are removed recursively).
    Body: { "path": "/folder/file.txt" }
    """

    # Check if the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Parse request JSON safely
    data = request.json or {}

    # Get relative path of item to delete
    rel = data.get("path", "")

    # Prevent deletion of root path
    if not rel or rel == "/":
        return jsonify({"error": "Cannot delete root"}), 400

    # Resolve the path within user's directory
    item, err = resolve_path(username, rel)

    # Block access if path resolution failed
    if err:
        return jsonify({"error": err}), 403

    # Ensure the item actually exists
    if not item.exists():
        return jsonify({"error": "Not found"}), 404

    # Extra safety check: prevent deleting the user's root directory
    if item == user_root(username):
        return jsonify({"error": "Cannot delete root"}), 400

    # Delete directory recursively OR delete single file
    shutil.rmtree(item) if item.is_dir() else item.unlink()

    # Return success message
    return jsonify({"message": f'"{item.name}" deleted'})


# ── Move ───────────────────────────────────────────────────────────────────

@app.route("/api/move/<username>", methods=["POST"])
def move_item(username):
    """
    Move a file or directory to a new parent directory.
    Body: { "src": "/old/path/item", "dst": "/new/parent" }
    """

    # Verify the user exists
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Parse JSON request body safely
    data = request.json or {}

    # Extract source item path and destination directory path
    src_rel, dst_rel = data.get("src", ""), data.get("dst", "")

    # Ensure both fields are provided
    if not src_rel or not dst_rel:
        return jsonify({"error": "src and dst required"}), 400

    # Resolve and validate source path
    src, err = resolve_path(username, src_rel)
    if err or not src.exists():
        return jsonify({"error": "Source not found"}), 404

    # Resolve and validate destination directory path
    dst_dir, err = resolve_path(username, dst_rel)
    if err or not dst_dir.is_dir():
        return jsonify({"error": "Destination directory not found"}), 404

    # Build final destination path (keep original filename)
    dest = dst_dir / src.name

    # Prevent overwriting an existing file/folder
    if dest.exists():
        return jsonify({"error": f'"{src.name}" already exists in destination'}), 409

    # Move the file or directory
    shutil.move(str(src), str(dest))

    # Return success response
    return jsonify({"message": f'"{src.name}" moved'})


# ── Rename ─────────────────────────────────────────────────────────────────

@app.route("/api/rename/<username>", methods=["POST"])
def rename_item(username):
    """
    Rename a file or directory in-place.
    Body: { "path": "/folder/old_name.txt", "name": "new_name.txt" }
    """

    # Check if the user exists in the system
    if username not in load_users():
        return jsonify({"error": "User not found"}), 404

    # Parse JSON request body (fallback to empty dict if missing)
    data = request.json or {}

    # Original file path (relative) and new desired name
    src_rel  = data.get("path", "")
    new_name = data.get("name", "").strip()

    # Validate required inputs
    if not src_rel or not new_name:
        return jsonify({"error": "path and name required"}), 400

    # Resolve the path for the user
    src, err = resolve_path(username, src_rel)

    # If path resolution failed or file doesn't exist, return error
    if err or not src.exists():
        return jsonify({"error": "Not found"}), 404

    # Construct destination path in same directory with new filename
    dest = src.parent / new_name

    # Prevent overwriting an existing file/directory
    if dest.exists():
        return jsonify({"error": "Name already taken"}), 409

    # Perform the rename operation
    src.rename(dest)

    # Return success response with new name
    return jsonify({"message": f'Renamed to "{new_name}"'})


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  CSC474/574 Cloud File System")
    print("  http://0.0.0.0:8080")
    print("=" * 50)

    # Werkzeug internally does:
    #   sock = socket.socket(AF_INET, SOCK_STREAM)
    #   sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    #   sock.bind(("0.0.0.0", 8080))
    #   sock.listen(LISTEN_QUEUE)
    # host="0.0.0.0" → INADDR_ANY, accept on all NICs
    # port=8080
    app.run(host="0.0.0.0", port=8080, debug=False)