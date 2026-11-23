import base64
import json
import re
import time
from urllib.parse import urlsplit

import requests

VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class RequestError(ValueError):
    """A problem with the request that the user can fix."""


def clean_token(token):
    token = str(token or "").strip().strip("\"'").strip()
    return re.sub(r"^bearer\s+", "", token, flags=re.IGNORECASE)


def without_header(headers, name):
    return {key: value for key, value in headers.items() if key.lower() != name.lower()}


def replace_variables(value, variables):
    if isinstance(value, str):
        return VARIABLE_PATTERN.sub(lambda match: str(variables.get(match.group(1), match.group(0))), value)
    if isinstance(value, list):
        return [replace_variables(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: replace_variables(item, variables) for key, item in value.items()}
    return value


def rows_to_pairs(rows):
    return [
        (str(row.get("key", "")), str(row.get("value", "")))
        for row in rows
        if isinstance(row, dict) and row.get("enabled", True) is not False and str(row.get("key", "")).strip()
    ]


def send(data, variables):
    method = str(data.get("method", "GET")).upper()
    if method not in METHODS:
        raise RequestError("Unsupported method.")
    resolved = replace_variables(data, variables)
    url = str(resolved.get("url", "")).strip()
    if "{{" in url:
        names = ", ".join(sorted(set(re.findall(r"\{\{([^}]*)\}\}", url)))) or url
        raise RequestError(f"The URL contains an unknown variable: {names}. Add it in Environment variables.")
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise RequestError("Enter a valid http or https URL.")
    headers = dict(rows_to_pairs(resolved.get("headers", [])))
    params = rows_to_pairs(resolved.get("params", []))
    auth = resolved.get("auth") if isinstance(resolved.get("auth"), dict) else {"type": "tokenbox"}
    auth_type = auth.get("type", "tokenbox")
    if auth_type == "tokenbox":
        token = clean_token(data.get("token"))
        if token:
            headers = without_header(headers, "Authorization_token")
            headers["Authorization_token"] = token
    elif auth_type == "bearer" and clean_token(auth.get("token")):
        headers = without_header(headers, "Authorization")
        headers["Authorization"] = f"Bearer {clean_token(auth.get('token'))}"
    elif auth_type == "basic":
        credentials = f"{auth.get('username', '')}:{auth.get('password', '')}".encode("utf-8")
        headers = without_header(headers, "Authorization")
        headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode('ascii')}"
    elif auth_type == "apikey" and str(auth.get("key", "")).strip():
        key, value = str(auth["key"]).strip(), str(auth.get("value", ""))
        if auth.get("in") == "query":
            params.append((key, value))
        else:
            headers = without_header(headers, key)
            headers[key] = value
    unknown = sorted({name for value in [*headers.values(), *(value for _, value in params)] for name in re.findall(r"\{\{\s*([^}]*?)\s*\}\}", value)})
    if unknown:
        raise RequestError(f"Unknown variable in headers, params or auth: {', '.join(unknown)}. Add it in Environment variables or untick that row.")
    body_type = resolved.get("body_type") or ("text" if resolved.get("body") else "none")
    body, files = None, None
    if body_type in ("json", "text"):
        body = str(resolved.get("body") or "").encode("utf-8") or None
        if body and not any(key.lower() == "content-type" for key in headers):
            headers["Content-Type"] = "application/json" if body_type == "json" else "text/plain; charset=utf-8"
    elif body_type == "urlencoded":
        body = rows_to_pairs([row for row in resolved.get("form", []) if isinstance(row, dict) and row.get("type") != "file"])
    elif body_type == "formdata":
        rows = [row for row in resolved.get("form", []) if isinstance(row, dict)
                and row.get("enabled", True) is not False and str(row.get("key", "")).strip()]
        body = [(row["key"], str(row.get("value", ""))) for row in rows if row.get("type") != "file"]
        files = []
        for row in (row for row in rows if row.get("type") == "file"):
            if not row.get("content"):
                raise RequestError(f"Choose the file again for form field \"{row['key']}\".")
            files.append((row["key"], (row.get("filename") or "file", base64.b64decode(row["content"]))))
    started = time.perf_counter()
    response = requests.request(
        method, url, params=params, headers=headers, data=body, files=files or None, timeout=60
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    content_type = response.headers.get("Content-Type", "")
    body_base64 = None
    if content_type.lower().startswith("image/"):
        body_base64 = base64.b64encode(response.content).decode("ascii")
        response_body = f"[{content_type} image, {len(response.content)} bytes. Open Preview to view it.]"
        is_json = False
    else:
        try:
            response_body = json.dumps(response.json(), indent=2, ensure_ascii=False)
            is_json = True
        except ValueError:
            response_body = response.text
            is_json = False
    return {
        "status": response.status_code,
        "reason": response.reason,
        "elapsed_ms": elapsed_ms,
        "size_bytes": len(response.content),
        "headers": dict(response.headers),
        "body": response_body,
        "is_json": is_json,
        "body_base64": body_base64,
    }
