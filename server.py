"""
AI File Organizer v3.0 — Python Backend
Run: python server.py  (or double-click START.bat)
Opens: http://localhost:8765

ALL AI calls are made server-side — no CORS issues, no browser restrictions.
"""
import os, sys, json, time, shutil, sqlite3, logging, threading, re
from pathlib import Path
from datetime import datetime

# ── Auto-install deps ───────────────────────────────────────────
def pip_install(*pkgs):
    for p in pkgs:
        try: __import__(p.replace("-","_"))
        except ImportError:
            os.system(f'"{sys.executable}" -m pip install {p} --quiet')

pip_install("flask","flask-cors","requests")

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests as http

# ── Paths ───────────────────────────────────────────────────────
APP_DIR  = Path(os.environ.get("APPDATA", Path.home())) / "AIFileOrganizer"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH     = APP_DIR / "metadata.db"
CONFIG_PATH = APP_DIR / "config.json"
FRONTEND    = Path(__file__).parent

# ── Logging ─────────────────────────────────────────────────────
DEFAULT_LOG = str(APP_DIR / "organizer.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DEFAULT_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("AIFileOrg")

# ── Default Config ──────────────────────────────────────────────
DEFAULT_CFG = {
    "provider": "anthropic",
    "api_key": "",
    "model": "claude-sonnet-4-20250514",
    "ollama_url": "http://localhost:11434",
    "temperature": 0.3,
    "max_tokens": 1000,
    "batch_size": 5,
    "timeout": 30,
    "max_preview_bytes": 4096,
    "watch_dirs": [],
    "dest_root": str(Path.home() / "Organized"),
    "exclude": ["*.tmp","~$*","Thumbs.db","desktop.ini",".DS_Store","*.lnk"],
    "port": 8765,
    "log_path": DEFAULT_LOG,
    "log_level": "INFO",
    "auto_browser": True,
    "fallback_heuristic": True,
    "read_content": True,
    "providers": [
        {"id":"anthropic","name":"Anthropic (Claude)","type":"anthropic",
         "endpoint":"https://api.anthropic.com/v1/messages","api_key":"","enabled":True,
         "models":["claude-sonnet-4-20250514","claude-opus-4-5","claude-haiku-4-5-20251001"]},
        {"id":"openai","name":"OpenAI (GPT)","type":"openai",
         "endpoint":"https://api.openai.com/v1/chat/completions","api_key":"","enabled":True,
         "models":["gpt-4o","gpt-4-turbo","gpt-3.5-turbo"]},
        {"id":"ollama","name":"Ollama (Local)","type":"ollama",
         "endpoint":"http://localhost:11434","api_key":"","enabled":True,"models":[]},
    ],
    "file_types": {
        "Documents":    {"extensions":["pdf","doc","docx","txt","md","rtf","odt","pages"],"color":"#3b82f6"},
        "Spreadsheets": {"extensions":["xls","xlsx","csv","ods","numbers"],"color":"#10b981"},
        "Presentations":{"extensions":["ppt","pptx","odp","key"],"color":"#f59e0b"},
        "Images":       {"extensions":["jpg","jpeg","png","gif","bmp","svg","webp","tiff","raw"],"color":"#ec4899"},
        "Videos":       {"extensions":["mp4","avi","mov","mkv","wmv","flv","m4v","webm"],"color":"#8b5cf6"},
        "Audio":        {"extensions":["mp3","wav","flac","aac","ogg","m4a","wma"],"color":"#06b6d4"},
        "Code":         {"extensions":["py","js","ts","jsx","tsx","html","css","json","sql","sh","bat","cs","cpp","java","go","rs","rb","php","swift","kt"],"color":"#84cc16"},
        "Archives":     {"extensions":["zip","tar","gz","7z","rar","bz2"],"color":"#64748b"},
        "Data":         {"extensions":["json","xml","yaml","yml","toml","ini","cfg"],"color":"#f97316"},
    },
    "tags": ["invoice","report","contract","personal","work","finance","archive","draft","final","template"],
    "system_prompt": """You are an expert file organizer. Analyze the file information and classify it.
Respond with ONLY valid JSON, no markdown, no explanation:
{"category":"<n>","subcategory":"<name or empty>","tags":["<tag1>","<tag2>","<tag3>"],"suggested_path":"<Category/Sub>","confidence":<0-1>}
- tags: exactly 3 short lowercase descriptive keywords
- suggested_path: relative path using forward slashes, no leading slash
- confidence: 0.0 to 1.0""",
}

def load_cfg():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**DEFAULT_CFG, **saved}
            if "providers" not in saved: merged["providers"] = DEFAULT_CFG["providers"]
            if "file_types" not in saved: merged["file_types"] = DEFAULT_CFG["file_types"]
            if "tags" not in saved: merged["tags"] = DEFAULT_CFG["tags"]
            return merged
        except Exception as e:
            log.warning(f"Config load error: {e}")
    return dict(DEFAULT_CFG)

def save_cfg(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

CFG = load_cfg()

# ── Database ─────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL, name TEXT, size INTEGER,
        modified REAL, file_type TEXT, hash TEXT,
        scanned_at REAL DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        model TEXT, provider TEXT, category TEXT, subcategory TEXT,
        tags TEXT, suggested_path TEXT, confidence REAL, method TEXT,
        analyzed_at REAL DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        operation TEXT, source TEXT, destination TEXT,
        status TEXT, dry_run INTEGER DEFAULT 1, error_msg TEXT,
        executed_at REAL DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#3b82f6',
        keywords TEXT DEFAULT '[]', path_template TEXT,
        created_at REAL DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#3b82f6',
        created_at REAL DEFAULT (strftime('%s','now'))
    );
    """)
    conn.commit(); conn.close()
    log.info(f"Database ready: {DB_PATH}")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── File helpers ─────────────────────────────────────────────────
ICONS = {
    "pdf":"📄","doc":"📃","docx":"📃","txt":"📝","md":"📋","rtf":"📄",
    "xls":"📊","xlsx":"📊","csv":"📊","ppt":"📊","pptx":"📊",
    "jpg":"🖼","jpeg":"🖼","png":"🖼","gif":"🖼","svg":"🖼","bmp":"🖼","webp":"🖼",
    "mp4":"🎬","avi":"🎬","mov":"🎬","mkv":"🎬",
    "mp3":"🎵","wav":"🎵","flac":"🎵","m4a":"🎵",
    "zip":"📦","tar":"📦","gz":"📦","7z":"📦","rar":"📦",
    "py":"🐍","js":"📜","ts":"📜","html":"🌐","css":"🎨",
    "json":"⚙","xml":"⚙","sql":"🗄","sh":"⚙","bat":"⚙",
}
def get_icon(ext): return ICONS.get(ext.lower().lstrip("."), "📄")

TEXT_EXT = {".txt",".md",".py",".js",".ts",".html",".css",".json",".xml",
            ".yaml",".yml",".csv",".sql",".sh",".bat",".ini",".cfg",".log",
            ".java",".cpp",".c",".h",".cs",".go",".rs",".rb",".php",".swift",".kt",".r"}

def ext_to_category(ext):
    ext = ext.lower().lstrip(".")
    for cat, info in CFG.get("file_types", DEFAULT_CFG["file_types"]).items():
        if ext in info.get("extensions", []):
            return cat
    return "Other"

def read_preview(path):
    p = Path(path)
    if p.suffix.lower() not in TEXT_EXT: return ""
    if not CFG.get("read_content", True): return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(CFG.get("max_preview_bytes", 4096))
    except OSError: return ""

# ── Heuristic fallback classifier ───────────────────────────────
def classify_heuristic(file_info):
    name = file_info.get("name","").lower()
    ext  = file_info.get("type","").lower()
    cat  = ext_to_category(ext) or "Other"
    sub  = ""
    kw_map = [
        ("invoice", "Finance","Invoices"), ("receipt","Finance","Receipts"),
        ("tax","Finance","Tax"), ("budget","Finance","Budgets"),
        ("report","Work Documents","Reports"), ("contract","Work Documents","Contracts"),
        ("proposal","Work Documents","Proposals"), ("meeting","Work Documents","Meetings"),
        ("notes","Work Documents","Notes"), ("resume","Personal","Resume"),
        ("photo","Images","Photos"), ("backup","Archives","Backups"),
        ("schema","Code","Database"), ("readme","Code","Documentation"),
    ]
    kw1 = ext or "file"
    for kw, kcat, ksub in kw_map:
        if kw in name:
            cat, sub, kw1 = kcat, ksub, kw
            break
    ym = re.search(r"(20\d{2})", name)
    year = ym.group(1) if ym else ""
    tags = list(dict.fromkeys([kw1, cat.lower().split()[0], year or ext or "other"]))[:3]
    while len(tags) < 3: tags.append(ext or "file")
    sp = f"{cat}/{sub}" if sub else cat
    if year: sp += f"/{year}"
    return {"category":cat,"subcategory":sub,"tags":tags,"suggested_path":sp,
            "confidence":0.45,"method":"heuristic"}

# ── AI callers ───────────────────────────────────────────────────
def build_user_msg(fi, preview=""):
    dt = datetime.fromtimestamp(fi["modified"]).strftime("%Y-%m-%d") if fi.get("modified") else ""
return (
    f"Filename: {fi.get('name','')}\n"
    f"Extension: .{fi.get('type','')}\n"
    f"Size: {fi.get('size',0)} bytes\n"
    f"Modified: {dt}\n"
    f"Path: {fi.get('path','')}\n"
    + (
        f"\nContent snippet:\n{preview[:1500]}"
        if preview else ""
    )
    + "\n\nReturn JSON only."
)


def parse_ai_json(text):
    clean = re.sub(r"```[a-z]*","",text or "").replace("```","").strip()
    obj = json.loads(clean)
    tags = obj.get("tags") or obj.get("keywords") or []
    while len(tags) < 3: tags.append(obj.get("category","file").lower().split()[0])
    obj["tags"] = [str(t).lower() for t in tags[:3]]
    if not obj.get("suggested_path"): obj["suggested_path"] = obj.get("category","Unsorted")
    obj["method"] = "ai"
    return obj

def find_provider(provider_id):
    for p in CFG.get("providers", DEFAULT_CFG["providers"]):
        if p["id"] == provider_id:
            return p
    return {}

def call_anthropic(fi, prov, model):
    key = prov.get("api_key") or CFG.get("api_key","")
    if not key: raise ValueError("No API key configured for Anthropic")
    preview = read_preview(fi.get("path",""))
    r = http.post(
        prov.get("endpoint","https://api.anthropic.com/v1/messages"),
        headers={"x-api-key":key,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
        json={"model":model,"max_tokens":CFG.get("max_tokens",1000),
              "system":CFG.get("system_prompt",DEFAULT_CFG["system_prompt"]),
              "messages":[{"role":"user","content":build_user_msg(fi,preview)}]},
        timeout=CFG.get("timeout",30))
    r.raise_for_status()
    return parse_ai_json(r.json()["content"][0]["text"])

def call_openai(fi, prov, model):
    key = prov.get("api_key") or CFG.get("api_key","")
    if not key: raise ValueError("No API key configured for OpenAI")
    preview = read_preview(fi.get("path",""))
    system = CFG.get("system_prompt", DEFAULT_CFG["system_prompt"])
    r = http.post(
        prov.get("endpoint","https://api.openai.com/v1/chat/completions"),
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":model,"max_tokens":CFG.get("max_tokens",1000),
              "temperature":CFG.get("temperature",0.3),
              "response_format":{"type":"json_object"},
              "messages":[{"role":"system","content":system},
                          {"role":"user","content":build_user_msg(fi,preview)}]},
        timeout=CFG.get("timeout",30))
    r.raise_for_status()
    return parse_ai_json(r.json()["choices"][0]["message"]["content"])

def call_ollama(fi, prov, model):
    """ONLY contacts local Ollama — never ollama.com"""
    base = (prov.get("endpoint") or CFG.get("ollama_url","http://localhost:11434")).rstrip("/")
    from urllib.parse import urlparse
    host = urlparse(base).hostname or ""
    if not (host in ("localhost","127.0.0.1") or
            any(host.startswith(p) for p in ("192.168.","10.","172."))):
        base = "http://localhost:11434"
        log.warning(f"Ollama URL blocked (not local) — using {base}")
    preview = read_preview(fi.get("path",""))
    system  = CFG.get("system_prompt", DEFAULT_CFG["system_prompt"])
    r = http.post(f"{base}/api/generate",
        headers={"Content-Type":"application/json"},


json={
    "model": model,
    "prompt": f"{system}\n\n{build_user_msg(fi, preview)}",
    "stream": False,
    "format": "json"
}

{build_user_msg(fi,preview)}",
              "stream":False,"format":"json"},
        timeout=CFG.get("timeout",90))
    r.raise_for_status()
    return parse_ai_json(r.json()["response"])

def analyze_file(fi, provider_id, model, system_override=None):
    if system_override:
        old = CFG.get("system_prompt","")
        CFG["system_prompt"] = system_override
    prov  = find_provider(provider_id)
    ptype = prov.get("type", provider_id)
    try:
        if ptype == "anthropic": result = call_anthropic(fi, prov, model)
        elif ptype == "openai":  result = call_openai(fi, prov, model)
        elif ptype == "ollama":  result = call_ollama(fi, prov, model)
        else:                    result = call_openai(fi, prov, model)
        return result
    except Exception as e:
        log.warning(f"AI failed for {fi.get('name','?')} [{e}] — using heuristic")
        if not CFG.get("fallback_heuristic", True):
            raise
        res = classify_heuristic(fi)
        res["ai_error"] = str(e)
        return res
    finally:
        if system_override:
            CFG["system_prompt"] = old

# ── File operations ──────────────────────────────────────────────
def do_file_op(src, dst, operation, dry_run, conflict="rename"):
    s, d = Path(src), Path(dst)
    if not s.exists():
        return {"status":"error","error":f"Source not found: {src}","destination":str(d)}
    if dry_run:
        return {"status":"dry_run","destination":str(d)}
    d.parent.mkdir(parents=True, exist_ok=True)  # create full directory tree
    if d.exists():
        if conflict == "skip":
            return {"status":"skipped","destination":str(d)}
        elif conflict == "overwrite":
            pass
        else:
            stem, sfx, n = d.stem, d.suffix, 1
            while d.exists():
                d = d.parent / f"{stem}_{n}{sfx}"
                n += 1
    try:
        if operation == "copy": shutil.copy2(str(s), str(d))
        else:                   shutil.move(str(s), str(d))
        return {"status":"success","destination":str(d)}
    except Exception as e:
        return {"status":"error","error":str(e),"destination":str(d)}

# ── Flask app ────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND))
CORS(app)

@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

# Config
@app.route("/api/config", methods=["GET"])
def api_get_config():
    safe = dict(CFG)
    safe["api_key"] = "***" if CFG.get("api_key") else ""
    safe["db_path"] = str(DB_PATH)
    return jsonify(safe)

@app.route("/api/config", methods=["POST"])
def api_set_config():
    global CFG
    for k, v in (request.json or {}).items():
        if v != "***": CFG[k] = v
    save_cfg(CFG)
    return jsonify({"status":"saved"})

@app.route("/api/config/provider", methods=["POST"])
def api_save_provider():
    global CFG
    data = request.json or {}
    providers = CFG.get("providers",[])
    pid = data.get("id")
    existing = next((p for p in providers if p["id"]==pid), None)
    if existing:
        for k,v in data.items():
            if v != "***": existing[k] = v
    else:
        providers.append(data)
    CFG["providers"] = providers
    save_cfg(CFG)
    return jsonify({"status":"saved"})

@app.route("/api/config/provider/<pid>", methods=["DELETE"])
def api_del_provider(pid):
    global CFG
    CFG["providers"] = [p for p in CFG.get("providers",[]) if p["id"]!=pid]
    save_cfg(CFG)
    return jsonify({"status":"deleted"})

# Browse directories
@app.route("/api/browse", methods=["GET"])
def api_browse():
    path = request.args.get("path", str(Path.home()))
    p = Path(path)
    if not p.exists(): p = Path.home()
    try:
        dirs = sorted([
            {"name":d.name,"path":str(d)}
            for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")
        ], key=lambda x: x["name"].lower())
    except PermissionError:
        dirs = []
    drives = []
    if sys.platform == "win32":
        import string
        drives = [{"name":f"{l}:\\","path":f"{l}:\\"}
                  for l in string.ascii_uppercase if Path(f"{l}:\\").exists()]
    return jsonify({"current":str(p),"parent":str(p.parent) if p.parent!=p else "","dirs":dirs,"drives":drives})

# Scan
@app.route("/api/scan", methods=["POST"])
def api_scan():
    import fnmatch
    data = request.json or {}
    dirs   = data.get("directories", CFG.get("watch_dirs",[]))
    excl   = data.get("exclude", CFG.get("exclude",[]))
    ftypes = data.get("file_types","")
    allowed = [x.strip().lower() for x in ftypes.split(",") if x.strip()] if ftypes else []
    files = []
    for d in dirs:
        root = Path(d)
        if not root.exists(): continue
        def walk(p):
            try:
                for item in p.iterdir():
                    if item.name.startswith("."): continue
                    if any(fnmatch.fnmatch(item.name,pat) for pat in excl): continue
                    if item.is_file():
                        ext = item.suffix.lstrip(".").lower()
                        if allowed and ext not in allowed: continue
                        try:
                            st = item.stat()
                            files.append({"path":str(item),"name":item.name,
                                "size":st.st_size,"modified":st.st_mtime,
                                "type":ext or "unknown","icon":get_icon(ext)})
                        except OSError: pass
                    elif item.is_dir(): walk(item)
            except (PermissionError,OSError): pass
        walk(root)
    conn = get_db()
    for f in files:
        conn.execute("INSERT OR REPLACE INTO files (path,name,size,modified,file_type) VALUES (?,?,?,?,?)",
                     (f["path"],f["name"],f["size"],f["modified"],f["type"]))
    conn.commit(); conn.close()
    return jsonify({"files":files,"count":len(files)})

# Analyze — ALL AI calls happen here server-side
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data     = request.json or {}
    files    = data.get("files",[])
    provider = data.get("provider", CFG.get("provider","anthropic"))
    model    = data.get("model", CFG.get("model",""))
    system   = data.get("system_prompt")
    api_key  = data.get("api_key")
    # Temporarily apply per-request key/system if provided
    old_key, old_sys = CFG.get("api_key"), CFG.get("system_prompt")
    if api_key and api_key != "***": CFG["api_key"] = api_key
    # Also update per-provider key
    if api_key and api_key != "***":
        prov = find_provider(provider)
        if prov: prov["api_key"] = api_key
    results = []
    conn = get_db()
    for fi in files:
        res = analyze_file(fi, provider, model, system)
        row = conn.execute("SELECT id FROM files WHERE path=?",(fi.get("path"),)).fetchone()
        fid = row["id"] if row else None
        conn.execute("""INSERT INTO analysis
            (file_id,model,provider,category,subcategory,tags,suggested_path,confidence,method)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (fid, model, provider, res.get("category"), res.get("subcategory"),
             json.dumps(res.get("tags",[])), res.get("suggested_path"),
             res.get("confidence",0.5), res.get("method","ai")))
        conn.commit()
        results.append({"file":fi,"analysis":res,"status":"success",
                        "fallback":res.get("method")=="heuristic"})
        log.info(f"[{res.get('method','ai')}] {fi.get('name')} → {res.get('category')}")
    conn.close()
    CFG["api_key"] = old_key  # restore
    return jsonify({"results":results})

# Organize — actual file copy/move with directory creation
@app.route("/api/organize", methods=["POST"])
def api_organize():
    data     = request.json or {}
    ops      = data.get("operations",[])
    mode     = data.get("operation","copy")
    dry_run  = data.get("dry_run",True)
    dest     = data.get("dest_root", CFG.get("dest_root", str(Path.home()/"Organized")))
    conflict = data.get("conflict","rename")
    struct   = data.get("struct_mode","ai")
    results  = []
    conn = get_db()
    for op in ops:
        fi   = op.get("file",{})
        src  = fi.get("path","")
        sp   = op.get("suggested_path", op.get("category","Unsorted"))
        if struct == "type":
            sp = ext_to_category(fi.get("type",""))
        elif struct == "date":
            mt = fi.get("modified")
            sp = datetime.fromtimestamp(mt).strftime("%Y/%m") if mt else "Unknown"
        elif struct == "category":
            sp = op.get("category","Unsorted")
        dst = str(Path(dest) / sp / fi.get("name", Path(src).name if src else "unknown"))
        res = do_file_op(src, dst, mode, dry_run, conflict)
        row = conn.execute("SELECT id FROM files WHERE path=?",(src,)).fetchone()
        conn.execute("""INSERT INTO operations
            (file_id,operation,source,destination,status,dry_run,error_msg)
            VALUES (?,?,?,?,?,?,?)""",
            (row["id"] if row else None, mode, src, dst,
             res["status"], int(dry_run), res.get("error","")))
        conn.commit()
        results.append({"source":src,"destination":dst,**res})
    conn.close()
    return jsonify({"results":results,"dry_run":dry_run})

# Tags
@app.route("/api/tags", methods=["GET"])
def api_get_tags():
    return jsonify({"tags": CFG.get("tags",[])})

@app.route("/api/tags", methods=["POST"])
def api_set_tags():
    global CFG
    CFG["tags"] = request.json.get("tags",[])
    save_cfg(CFG)
    return jsonify({"status":"saved","tags":CFG["tags"]})

# Categories
@app.route("/api/categories", methods=["GET"])
def api_get_cats():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/categories", methods=["POST"])
def api_add_cat():
    d = request.json or {}
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO categories (name,color,keywords,path_template) VALUES (?,?,?,?)",
                 (d["name"],d.get("color","#3b82f6"),json.dumps(d.get("keywords",[])),d.get("path","")))
    conn.commit(); conn.close()
    return jsonify({"status":"created"})

@app.route("/api/categories/<int:cid>", methods=["DELETE"])
def api_del_cat(cid):
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?",(cid,))
    conn.commit(); conn.close()
    return jsonify({"status":"deleted"})

# Ollama proxy — routes through server, NEVER contacts ollama.com
@app.route("/api/ollama/tags", methods=["GET"])
def api_ollama_tags():
    from urllib.parse import urlparse
    raw = request.args.get("url", CFG.get("ollama_url","http://localhost:11434"))
    url = raw.rstrip("/")
    host = urlparse(url).hostname or ""
    if not (host in ("localhost","127.0.0.1") or
            any(host.startswith(p) for p in ("192.168.","10.","172."))):
        return jsonify({"error":"Only local Ollama addresses are supported","models":[]}), 400
    try:
        r = http.get(f"{url}/api/tags", timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error":str(e),"models":[]}), 502

@app.route("/api/ollama/pull", methods=["POST"])
def api_ollama_pull():
    d    = request.json or {}
    url  = (d.get("url") or CFG.get("ollama_url","http://localhost:11434")).rstrip("/")
    name = d.get("model","")
    log.info(f"Pulling Ollama model {name} from {url}")
    def _pull():
        try:
            r = http.post(f"{url}/api/pull", json={"name":name}, stream=True, timeout=600)
            for ln in r.iter_lines():
                if ln: log.info(f"  pull {name}: {ln.decode()[:120]}")
        except Exception as e:
            log.error(f"pull failed: {e}")
    threading.Thread(target=_pull, daemon=True).start()
    return jsonify({"status":"pulling","model":name})

@app.route("/api/ollama/delete", methods=["POST"])
def api_ollama_del():
    d   = request.json or {}
    url = (d.get("url") or CFG.get("ollama_url","http://localhost:11434")).rstrip("/")
    try:
        r = http.delete(f"{url}/api/delete", json={"name":d.get("model","")}, timeout=10)
        return jsonify(r.json() if r.ok else {"status":"error"})
    except Exception as e:
        return jsonify({"error":str(e)}), 502

# Stats
@app.route("/api/stats", methods=["GET"])
def api_stats():
    conn = get_db()
    s = {
        "total":      conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "analyzed":   conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0],
        "operations": conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0],
        "categories": conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
        "size":       conn.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0],
        "cat_dist":   [dict(r) for r in conn.execute("SELECT category,COUNT(*) cnt FROM analysis GROUP BY category ORDER BY cnt DESC").fetchall()],
        "type_dist":  [dict(r) for r in conn.execute("SELECT file_type,COUNT(*) cnt FROM files GROUP BY file_type ORDER BY cnt DESC").fetchall()],
        "recent_ops": [dict(r) for r in conn.execute("SELECT * FROM operations ORDER BY executed_at DESC LIMIT 30").fetchall()],
    }
    conn.close()
    return jsonify(s)

# DB management
@app.route("/api/db/stats", methods=["GET"])
def api_db_stats():
    size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    conn = get_db()
    s = {"path":str(DB_PATH),"size":size,
         "files":conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
         "analysis":conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0],
         "operations":conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0],
         "categories":conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]}
    conn.close()
    return jsonify(s)

@app.route("/api/db/clear", methods=["POST"])
def api_db_clear():
    conn = get_db()
    conn.executescript("DELETE FROM operations;DELETE FROM analysis;DELETE FROM files;")
    conn.commit(); conn.close()
    return jsonify({"status":"cleared"})

# Graceful shutdown
@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    log.info("Graceful shutdown requested via API")
    def _stop():
        time.sleep(0.5); os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"status":"shutting_down"})

# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("""
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551        AI FILE ORGANIZER  v3.0            \u2551
\u2560\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2563
\u2551  http://localhost:8765                    \u2551
\u2551  ALL AI calls routed server-side          \u2551
\u2551  Ctrl+C to stop                           \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
""")
    init_db()
    port = CFG.get("port", 8765)
    host = "0.0.0.0"
    log.info(f"Starting on http://localhost:{port}")
    if CFG.get("auto_browser", True):
        try:
            import webbrowser
            threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        except Exception: pass
    app.run(host=host, port=port, debug=False, threaded=True)
