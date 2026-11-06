"""Arayuzdeki api("...") cagrilarini FastAPI rotalariyla karsilastirir.

Sunucu baslatilmaz; `backend.main` yalnizca rota tablosunu okumak icin iceri aktarilir
(gecici DATABASE_URL ve DATA_DIR ile). Uyumsuzluk varsa cikis kodu 1 olur.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"\b(api|rawApi)\s*(?:<[^()]*?>)?\s*\(\s*")
FETCH = re.compile(r"\bfetch\s*\(\s*(?=[`\"']/api/)")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def read_string(src: str, i: int):
    """src[i] bir tirnak ise (metin, bitis_indeksi) doner; sablon ifadeleri {} olur."""
    quote = src[i]
    i += 1
    out = []
    while i < len(src) and src[i] != quote:
        ch = src[i]
        if ch == "\\":
            out.append(src[i + 1])
            i += 2
        elif quote == "`" and src.startswith("${", i):
            depth, i = 1, i + 2
            while i < len(src) and depth:
                depth += {"{": 1, "}": -1}.get(src[i], 0)
                i += 1
            out.append("{}")
        else:
            out.append(ch)
            i += 1
    return "".join(out), i + 1


def skip_expr(src: str, i: int):
    """Dize olmayan bir ifadeyi ust duzey ',', ')' veya '+' gorene kadar atlar."""
    depth = 0
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            _, i = read_string(src, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch in ",+" and depth == 0:
            break
        i += 1
    return i


def parse_path(src: str, i: int):
    """`"a/" + id + "/b"` bicimli birlesimi okur; (yol, indeks) doner."""
    parts = []
    while True:
        while src[i].isspace():
            i += 1
        if src[i] in "\"'`":
            text, i = read_string(src, i)
            parts.append(text)
        else:
            parts.append("{}")
            i = skip_expr(src, i)
        while src[i].isspace():
            i += 1
        if src[i] == "+":
            i += 1
            continue
        return "".join(parts), i


def frontend_calls():
    calls = []
    for file in sorted((ROOT / "frontend" / "src").rglob("*.ts*")):
        src = file.read_text(encoding="utf8")
        for match in CALL.finditer(src):
            i = match.end()
            if i >= len(src) or src[i] in ")":
                continue
            try:
                path, i = parse_path(src, i)
            except IndexError:
                continue
            method = "GET"
            rest = src[i:i + 40]
            m = re.match(r"\s*,\s*[\"'](\w+)[\"']", rest)
            if m and m.group(1).upper() in METHODS:
                method = m.group(1).upper()
            line = src.count("\n", 0, match.start()) + 1
            calls.append((file.relative_to(ROOT).as_posix(), line, method, path))
        for match in FETCH.finditer(src):
            path, _ = parse_path(src, match.end())
            line = src.count("\n", 0, match.start()) + 1
            calls.append((file.relative_to(ROOT).as_posix(), line, "?", path.removeprefix("/api/")))
    return calls


def normalize(path: str):
    path = path.split("?", 1)[0].strip("/")
    return ["{}" if (s.startswith("{") and s.endswith("}")) or s == "{}" else s
            for s in re.sub(r"\{[^}]*\}", "{}", path).split("/") if s != ""]


def backend_routes():
    tmp = tempfile.mkdtemp(prefix="freya-routes-")
    os.environ["DATABASE_URL"] = "sqlite:///" + Path(tmp, "routes.db").as_posix()
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from backend.main import app

    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if path.startswith("/api/"):
            routes.append((normalize(path[len("/api/"):]), set(methods), path))
    return routes


def segs_match(call, route):
    return len(call) == len(route) and all(a == b or a == "{}" or b == "{}" for a, b in zip(call, route))


def main():
    routes = backend_routes()
    specific = [r for r in routes if r[0] and r[0][0] != "{}"]
    generic = [r for r in routes if not r[0] or r[0][0] == "{}"]
    problems, generic_only = [], []
    calls = frontend_calls()
    for file, line, method, path in calls:
        segs = normalize(path)
        hits = [r for r in specific if segs_match(segs, r[0])]
        ok = [r for r in hits if method == "?" or method in r[1]]
        if ok:
            continue
        generic_ok = [r for r in generic if segs_match(segs, r[0]) and (method == "?" or method in r[1])]
        if generic_ok:
            generic_only.append((file, line, method, path))
        elif hits:
            allowed = sorted(set().union(*(r[1] for r in hits)) - {"HEAD", "OPTIONS"})
            problems.append((file, line, method, path, "yontem uyumsuz, rota yontemleri: " + ",".join(allowed)))
        else:
            problems.append((file, line, method, path, "rota yok"))
    print(f"Arayuz cagrisi: {len(calls)}, API rotasi: {len(routes)}")
    for file, line, method, path in generic_only:
        print(f"UYARI {file}:{line} {method} {path} yalnizca genel /api/{{...}} rotasina eslesti")
    for file, line, method, path, why in problems:
        print(f"UYUMSUZ {file}:{line} {method} /api/{path} -> {why}")
    if problems:
        print(f"{len(problems)} uyumsuzluk bulundu")
        return 1
    print("Tum arayuz cagrilari bir backend rotasina eslesiyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
