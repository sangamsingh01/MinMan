import json
import shutil
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from minman import __version__, storage
from minman.curl import parse_curl
from minman.http_client import RequestError, send
from minman.storage import (
    NAME_PATTERN, clean_variables, collection_path, copy_name, load_variables,
    read_environments, read_json, request_path, response_versions, safe_name, write_json,
)

__author__ = "Sangam Singh"


PACKAGE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
# Room for file uploads, which arrive base64-encoded inside the JSON body.
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def error(message, status=400):
    return jsonify(error=str(message)), status


@app.before_request
def local_only():
    # Blocks DNS-rebinding: other sites must not reach this API through a hostname pointing at 127.0.0.1.
    if request.host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
        return error("Forbidden host.", 403)
    # Blocks other websites open in the browser from calling this API (CSRF).
    origin = request.headers.get("Origin")
    if origin is not None and origin != f"{request.scheme}://{request.host}":
        return error("Forbidden origin.", 403)


@app.errorhandler(413)
def too_large(_):
    return error("Request is too large (limit 50 MB).", 413)


@app.get("/")
def home():
    return send_from_directory(PACKAGE_DIR / "static", "index.html")


@app.get("/api/about")
def about():
    return jsonify(version=__version__)


@app.get("/api/tree")
def get_tree():
    tree = {}
    for folder in sorted(storage.COLLECTIONS.rglob("*"), key=lambda item: item.as_posix().lower()):
        if folder.is_dir():
            folder_name = folder.relative_to(storage.COLLECTIONS).as_posix()
            requests_in_folder = []
            for path in sorted(folder.glob("*.json"), key=lambda item: item.stem.lower()):
                method = "REQ"
                try:
                    method = read_json(path).get("method", method)
                except (OSError, ValueError, AttributeError):
                    pass
                requests_in_folder.append({"name": path.stem, "method": method})
            tree[folder_name] = requests_in_folder
    return jsonify(tree)


@app.post("/api/folders")
def create_folder():
    data = request.get_json(silent=True) or {}
    try:
        name = safe_name(data.get("name"))
        parent = data.get("parent", "")
        parent_path = storage.COLLECTIONS if not parent else collection_path(parent)
    except ValueError as exc:
        return error(exc)
    if not parent_path.is_dir():
        return error("Parent folder not found.", 404)
    path = parent_path / name
    if path.exists():
        return error("That folder already exists.", 400)
    path.mkdir()
    return jsonify(name=name), 201


@app.delete("/api/folders/<path:folder>")
def delete_folder(folder):
    try:
        path = collection_path(folder)
    except ValueError as exc:
        return error(exc)
    if not path.is_dir():
        return error("Folder not found.", 404)
    shutil.rmtree(path)
    shutil.rmtree(collection_path(folder, storage.RESPONSES), ignore_errors=True)
    return jsonify(ok=True)


@app.get("/api/requests/<path:item>")
def get_request(item):
    try:
        folder, name = item.rsplit("/", 1)
        path = request_path(folder, name)
    except (ValueError, TypeError) as exc:
        return error(exc)
    if not path.is_file():
        return error("Request not found.", 404)
    try:
        return jsonify(read_json(path))
    except (OSError, ValueError) as exc:
        return error(f"Could not read request: {exc}", 500)


@app.put("/api/requests/<path:item>")
def save_request(item):
    try:
        folder, name = item.rsplit("/", 1)
        path = request_path(folder, name)
    except (ValueError, TypeError) as exc:
        return error(exc)
    if not path.parent.is_dir():
        return error("Folder not found.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Request data must be a JSON object.")
    form = data.get("form") if isinstance(data.get("form"), list) else []
    saved = {
        "name": name,
        "method": data.get("method", "GET"),
        "url": data.get("url", ""),
        "params": data.get("params", []),
        "headers": data.get("headers", []),
        "auth": data.get("auth", {"type": "tokenbox"}),
        "body_type": data.get("body_type", "none"),
        "body": data.get("body", ""),
        # File contents are never saved; only the file name is kept.
        "form": [{key: row.get(key) for key in ("key", "value", "enabled", "type", "filename") if key in row}
                 for row in form if isinstance(row, dict)],
    }
    write_json(path, saved)
    return jsonify(saved)


@app.delete("/api/requests/<path:item>")
def delete_request(item):
    try:
        folder, name = item.rsplit("/", 1)
        path = request_path(folder, name)
    except (ValueError, TypeError) as exc:
        return error(exc)
    if not path.is_file():
        return error("Request not found.", 404)
    path.unlink()
    for _, version_path in response_versions(folder, name):
        version_path.unlink()
    return jsonify(ok=True)


@app.post("/api/move")
def move_request():
    data = request.get_json(silent=True) or {}
    try:
        folder, name, target = data.get("folder"), data.get("name"), data.get("target")
        source = request_path(folder, name)
        destination = request_path(target, name)
    except ValueError as exc:
        return error(exc)
    if not source.is_file():
        return error("Request not found.", 404)
    if not destination.parent.is_dir():
        return error("Target folder not found.", 404)
    if destination.exists():
        return error("A request with that name already exists in the target folder.")
    source.rename(destination)
    versions = response_versions(folder, name)
    if versions:
        target_dir = collection_path(target, storage.RESPONSES)
        target_dir.mkdir(parents=True, exist_ok=True)
        for _, version_path in versions:
            version_path.rename(target_dir / version_path.name)
    return jsonify(folder=target, name=name)


@app.post("/api/rename")
def rename_item():
    data = request.get_json(silent=True) or {}
    kind, folder, name = data.get("kind"), data.get("folder"), data.get("name")
    try:
        new_name = safe_name(str(data.get("new_name", "")).strip())
        if kind == "folder":
            source = collection_path(folder)
            target = source.parent / new_name
        else:
            source = request_path(folder, name)
            target = request_path(folder, new_name)
    except ValueError as exc:
        return error(exc)
    if not source.exists():
        return error("Item not found.", 404)
    if target.exists():
        return error("That name is already used here.")
    if kind == "folder":
        source.rename(target)
        old_responses = collection_path(folder, storage.RESPONSES)
        if old_responses.is_dir():
            old_responses.rename(old_responses.parent / new_name)
        return jsonify(folder=target.relative_to(storage.COLLECTIONS).as_posix())
    versions = response_versions(folder, name)
    saved = read_json(source)
    saved["name"] = new_name
    write_json(target, saved)
    source.unlink()
    for number, path in versions:
        path.rename(path.with_name(f"{new_name}_v{number}.json"))
    return jsonify(folder=folder, name=new_name)


@app.post("/api/duplicate")
def duplicate_item():
    data = request.get_json(silent=True) or {}
    kind, folder, name = data.get("kind"), data.get("folder"), data.get("name")
    try:
        if kind == "folder":
            source = collection_path(folder)
            if not source.is_dir():
                return error("Folder not found.", 404)
            new_name = copy_name(source.name, lambda candidate: (source.parent / candidate).exists())
            target = source.parent / new_name
            shutil.copytree(source, target)
            return jsonify(folder=target.relative_to(storage.COLLECTIONS).as_posix()), 201
        source = request_path(folder, name)
        if not source.is_file():
            return error("Request not found.", 404)
        new_name = copy_name(name, lambda candidate: request_path(folder, candidate).exists())
    except ValueError as exc:
        return error(exc)
    saved = read_json(source)
    saved["name"] = new_name
    write_json(request_path(folder, new_name), saved)
    return jsonify(folder=folder, name=new_name), 201


@app.get("/api/responses/<path:item>")
def get_responses(item):
    try:
        folder, name = item.rsplit("/", 1)
        versions = response_versions(folder, name)
    except (ValueError, TypeError) as exc:
        return error(exc)
    wanted = request.args.get("version", type=int)
    if wanted is None:
        return jsonify([{"version": number, "file": path.name} for number, path in versions])
    for number, path in versions:
        if number == wanted:
            return jsonify(read_json(path))
    return error("Response version not found.", 404)


@app.post("/api/responses/<path:item>")
def save_response(item):
    try:
        folder, name = item.rsplit("/", 1)
        source = request_path(folder, name)
        versions = response_versions(folder, name)
    except (ValueError, TypeError) as exc:
        return error(exc)
    if not source.is_file():
        return error("Save the request before saving its response.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Response data must be a JSON object.")
    version = (versions[-1][0] if versions else 0) + 1
    directory = collection_path(folder, storage.RESPONSES)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}_v{version}.json"
    write_json(path, {
        "version": version,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "request": read_json(source),
        "response": {key: data.get(key) for key in ("status", "reason", "elapsed_ms", "size_bytes", "headers", "body", "is_json", "body_base64")},
    })
    return jsonify(version=version, file=path.name), 201


@app.route("/api/variables", methods=["GET", "PUT"])
def variables():
    if request.method == "GET":
        try:
            return jsonify(read_environments())
        except (OSError, ValueError) as exc:
            return error(f"Could not read variables: {exc}", 500)
    data = request.get_json(silent=True)
    environments = data.get("environments") if isinstance(data, dict) else None
    if not isinstance(environments, dict) or not environments or not all(
        isinstance(name, str) and NAME_PATTERN.fullmatch(name) and isinstance(values, dict)
        and all(isinstance(key, str) and isinstance(value, (str, int, float, bool)) for key, value in values.items())
        for name, values in environments.items()
    ):
        return error("Environments must have valid names and simple key/value variables.")
    if data.get("active") not in environments:
        return error("The active environment does not exist.")
    saved = {
        "active": data["active"],
        "environments": {name: clean_variables(values) for name, values in environments.items()},
    }
    write_json(storage.VARIABLES_FILE, saved)
    return jsonify(saved)


@app.post("/api/parse-curl")
def parse_curl_route():
    command = (request.get_json(silent=True) or {}).get("curl", "")
    try:
        return jsonify(parse_curl(command))
    except (ValueError, TypeError) as exc:
        return error(exc)


@app.post("/api/send")
def send_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Request data must be a JSON object.")
    try:
        return jsonify(send(data, load_variables()))
    # RequestException subclasses OSError, so it must be caught first.
    except requests.RequestException as exc:
        if isinstance(exc, requests.exceptions.SSLError) or "ssl" in str(exc).lower():
            return error(
                "SSL error: if you are using Zscaler, please authenticate yourself "
                f"(sign in to Zscaler) and try again.\n\nActual error: {exc}",
                502,
            )
        return error(f"Request failed: {exc}", 502)
    except RequestError as exc:
        return error(exc)
    except (OSError, json.JSONDecodeError) as exc:
        return error(f"Could not load variables: {exc}")
    except ValueError as exc:
        return error(f"Invalid request data: {exc}")