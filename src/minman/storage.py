import json
import re
from pathlib import Path

# Set by configure() from --data-dir / MINMAN_HOME / ~/.minman.
COLLECTIONS = RESPONSES = VARIABLES_FILE = None
NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _.-]{1,60}$")


def configure(data_dir):
    global COLLECTIONS, RESPONSES, VARIABLES_FILE
    data_dir = Path(data_dir).expanduser().resolve()
    COLLECTIONS, RESPONSES, VARIABLES_FILE = data_dir / "collections", data_dir / "responses", data_dir / "variables.json"
    COLLECTIONS.mkdir(parents=True, exist_ok=True)
    RESPONSES.mkdir(exist_ok=True)
    return data_dir


def read_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def safe_name(value):
    if not isinstance(value, str) or value == "." or not NAME_PATTERN.fullmatch(value) or ".." in value:
        raise ValueError("Names may use letters, numbers, spaces, dots, underscores and hyphens.")
    return value


def collection_path(folder, root=None):
    if not isinstance(folder, str) or not folder:
        raise ValueError("Folder name is required.")
    return (root or COLLECTIONS).joinpath(*(safe_name(part) for part in folder.split("/")))


def request_path(folder, name):
    return collection_path(folder) / f"{safe_name(name)}.json"


def response_versions(folder, name):
    directory = collection_path(folder, RESPONSES)
    pattern = re.compile(re.escape(safe_name(name)) + r"_v(\d+)\.json")
    found = []
    if directory.is_dir():
        for path in directory.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                found.append((int(match.group(1)), path))
    return sorted(found)


def copy_name(base, exists):
    for number in range(1, 100):
        candidate = f"{base} copy" if number == 1 else f"{base} copy {number}"
        if not exists(candidate):
            return safe_name(candidate)
    raise ValueError("Too many copies with this name.")


def variable_key(key):
    return re.sub(r"^\{\{\s*|\s*\}\}$", "", str(key).strip())


def clean_variables(values):
    return {variable_key(key): value for key, value in values.items() if variable_key(key)}


def read_environments():
    data = read_json(VARIABLES_FILE) if VARIABLES_FILE.exists() else {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("environments"), dict):
        data = {"active": "Default", "environments": {"Default": data}}  # old flat format
    environments = {
        str(name): clean_variables(values)
        for name, values in data["environments"].items()
        if isinstance(values, dict)
    } or {"Default": {}}
    active = data.get("active") if data.get("active") in environments else next(iter(environments))
    return {"active": active, "environments": environments}


def load_variables():
    environments = read_environments()
    return environments["environments"][environments["active"]]
