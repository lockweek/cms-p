import os
import uuid
import shutil
import sqlite3
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

DATA_DIR = "/data"
DB_PATH = os.path.join(DATA_DIR, "cms.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        position TEXT NOT NULL,
        birth_date TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_name TEXT,
        date_from TEXT NOT NULL,
        date_to TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_name TEXT,
        uploaded_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_name TEXT,
        uploaded_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # --- Миграция: колонка design_json для конструктора ---
    c.execute("PRAGMA table_info(announcements)")
    cols = {row[1] for row in c.fetchall()}
    if "design_json" not in cols:
        c.execute("ALTER TABLE announcements ADD COLUMN design_json TEXT")

    defaults = {
        "slide_duration": "8",
        "image_slide_duration": "8",
        "birthday_bg_color": "#0f172a",
        "birthday_bg_gradient": "linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%)",
        "birthday_bg_image": "",
        "video_muted": "1",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


init_db()

app = FastAPI(title="CMS Display")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ------------------- PAGES -------------------
@app.get("/")
def root():
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/display">')


@app.get("/display")
def display_page():
    return FileResponse(os.path.join(STATIC_DIR, "display.html"))


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


# ------------------- FILE TYPES & MIME -------------------
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ALLOWED_VIDEO_EXT = {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v"}
ALLOWED_ANN_EXT = ALLOWED_EXT | ALLOWED_VIDEO_EXT

MIME_MAP = {
    ".mp4": "video/mp4", ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg", ".ogg": "video/ogg",
    ".mov": "video/quicktime",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


def _ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()


def _save(file: UploadFile, fname: str):
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        shutil.copyfileobj(file.file, f)


def _media_type(filename: str) -> str:
    return "video" if _ext(filename) in ALLOWED_VIDEO_EXT else "image"


# ------------------- MEDIA STREAMING (Range) -------------------
@app.get("/media/{filename}")
def serve_media(filename: str, request: Request):
    safe = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(404, "Not found")

    ext = _ext(safe)
    mime = MIME_MAP.get(ext, "application/octet-stream")
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range") or request.headers.get("Range")

    common = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime,
        "Cache-Control": "public, max-age=86400",
    }

    if range_header:
        try:
            _, rng = range_header.split("=", 1)
            start_s, end_s = rng.split("-", 1)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
            if start < 0 or start > end:
                raise ValueError
        except ValueError:
            raise HTTPException(416, "Invalid range")

        length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk = 512 * 1024
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = dict(common)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(iter_range(), status_code=206, headers=headers)

    def iter_full():
        with open(path, "rb") as f:
            while True:
                data = f.read(512 * 1024)
                if not data:
                    break
                yield data

    headers = dict(common)
    headers["Content-Length"] = str(file_size)
    return StreamingResponse(iter_full(), media_type=mime, headers=headers)


# ------------------- EMPLOYEES -------------------
@app.get("/api/employees")
def list_employees():
    conn = get_db()
    rows = conn.execute("SELECT * FROM employees ORDER BY full_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/employees")
def create_employee(data: dict):
    full_name = (data.get("full_name") or "").strip()
    position = (data.get("position") or "").strip()
    birth_date = (data.get("birth_date") or "").strip()
    if not (full_name and position and birth_date):
        raise HTTPException(400, "Все поля обязательны")
    try:
        datetime.strptime(birth_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Неверный формат даты")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO employees (full_name, position, birth_date) VALUES (?, ?, ?)",
        (full_name, position, birth_date),
    )
    conn.commit()
    emp_id = cur.lastrowid
    conn.close()
    return {"id": emp_id, "full_name": full_name, "position": position, "birth_date": birth_date}


@app.put("/api/employees/{emp_id}")
def update_employee(emp_id: int, data: dict):
    conn = get_db()
    conn.execute(
        "UPDATE employees SET full_name=?, position=?, birth_date=? WHERE id=?",
        (data["full_name"], data["position"], data["birth_date"], emp_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/employees/{emp_id}")
def delete_employee(emp_id: int):
    conn = get_db()
    conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ------------------- ANNOUNCEMENTS -------------------
@app.get("/api/announcements")
def list_announcements():
    """Список без design_json — чтобы не грузить мегабайты base64 в браузер."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, filename, original_name, date_from, date_to FROM announcements ORDER BY date_from DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/announcements/{ann_id}/design")
def get_announcement_design(ann_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT design_json FROM announcements WHERE id=?", (ann_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return {"design_json": row["design_json"]}


@app.post("/api/announcements")
async def create_announcement(
    file: UploadFile = File(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    design_json: Optional[str] = Form(None),
):
    ext = _ext(file.filename)
    if ext not in ALLOWED_ANN_EXT:
        raise HTTPException(400, "Неподдерживаемый формат (картинки и видео)")
    fname = f"{uuid.uuid4().hex}{ext}"
    _save(file, fname)

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO announcements (filename, original_name, date_from, date_to, design_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (fname, file.filename, date_from, date_to, design_json),
    )
    conn.commit()
    ann_id = cur.lastrowid
    conn.close()
    return {
        "id": ann_id,
        "filename": fname,
        "media_type": _media_type(fname),
        "date_from": date_from,
        "date_to": date_to,
    }


@app.put("/api/announcements/{ann_id}")
async def update_announcement(
    ann_id: int,
    file: Optional[UploadFile] = File(None),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    design_json: Optional[str] = Form(None),
):
    conn = get_db()
    row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Not found")

    old_fname = row["filename"]
    new_fname = old_fname
    original = row["original_name"]

    if file is not None and file.filename:
        ext = _ext(file.filename)
        if ext not in ALLOWED_ANN_EXT:
            conn.close()
            raise HTTPException(400, "Неподдерживаемый формат")
        new_fname = f"{uuid.uuid4().hex}{ext}"
        _save(file, new_fname)
        try:
            os.remove(os.path.join(UPLOAD_DIR, old_fname))
        except OSError:
            pass
        original = file.filename

    new_from = date_from or row["date_from"]
    new_to = date_to or row["date_to"]
    new_design = design_json if design_json is not None else row["design_json"]

    conn.execute(
        "UPDATE announcements SET filename=?, original_name=?, date_from=?, date_to=?, design_json=? WHERE id=?",
        (new_fname, original, new_from, new_to, new_design, ann_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": ann_id, "filename": new_fname}


@app.delete("/api/announcements/{ann_id}")
def delete_announcement(ann_id: int):
    conn = get_db()
    row = conn.execute("SELECT filename FROM announcements WHERE id=?", (ann_id,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ------------------- IMAGES -------------------
@app.get("/api/images")
def list_images():
    conn = get_db()
    rows = conn.execute("SELECT * FROM images ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/images")
async def create_images(files: list[UploadFile] = File(...)):
    created = []
    conn = get_db()
    for file in files:
        ext = _ext(file.filename)
        if ext not in ALLOWED_EXT:
            continue
        fname = f"{uuid.uuid4().hex}{ext}"
        _save(file, fname)
        cur = conn.execute(
            "INSERT INTO images (filename, original_name, uploaded_at) VALUES (?, ?, ?)",
            (fname, file.filename, datetime.utcnow().isoformat()),
        )
        created.append({"id": cur.lastrowid, "filename": fname, "original_name": file.filename})
    conn.commit()
    conn.close()
    if not created:
        raise HTTPException(400, "Не удалось загрузить ни одного изображения")
    return created


@app.delete("/api/images/{img_id}")
def delete_image(img_id: int):
    conn = get_db()
    row = conn.execute("SELECT filename FROM images WHERE id=?", (img_id,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
    conn.execute("DELETE FROM images WHERE id=?", (img_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ------------------- VIDEOS -------------------
@app.get("/api/videos")
def list_videos():
    conn = get_db()
    rows = conn.execute("SELECT * FROM videos ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/videos")
async def create_videos(files: list[UploadFile] = File(...)):
    created = []
    conn = get_db()
    for file in files:
        ext = _ext(file.filename)
        if ext not in ALLOWED_VIDEO_EXT:
            continue
        fname = f"{uuid.uuid4().hex}{ext}"
        _save(file, fname)
        cur = conn.execute(
            "INSERT INTO videos (filename, original_name, uploaded_at) VALUES (?, ?, ?)",
            (fname, file.filename, datetime.utcnow().isoformat()),
        )
        created.append({"id": cur.lastrowid, "filename": fname, "original_name": file.filename})
    conn.commit()
    conn.close()
    if not created:
        raise HTTPException(400, "Не удалось загрузить ни одного видео")
    return created


@app.delete("/api/videos/{vid_id}")
def delete_video(vid_id: int):
    conn = get_db()
    row = conn.execute("SELECT filename FROM videos WHERE id=?", (vid_id,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
    conn.execute("DELETE FROM videos WHERE id=?", (vid_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ------------------- SETTINGS -------------------
@app.get("/api/settings")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


@app.put("/api/settings")
def update_settings(data: dict):
    conn = get_db()
    for k, v in data.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v))
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/settings/upload-bg")
async def upload_bg(file: UploadFile = File(...)):
    ext = _ext(file.filename)
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Неподдерживаемый формат")
    fname = f"bg_{uuid.uuid4().hex}{ext}"
    _save(file, fname)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('birthday_bg_image', ?)",
        (fname,),
    )
    conn.commit()
    conn.close()
    return {"filename": fname}


# ------------------- DISPLAY DATA -------------------
@app.get("/api/display-data")
def display_data():
    today = date.today()
    conn = get_db()
    settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings").fetchall()}

    employees = [dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()]
    bday_people = []
    for e in employees:
        try:
            bd = datetime.strptime(e["birth_date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if bd.month == today.month and bd.day == today.day:
            bday_people.append(e)

    birthday_slides = [bday_people[i : i + 3] for i in range(0, len(bday_people), 3)]

    anns = []
    for a in conn.execute("SELECT * FROM announcements").fetchall():
        try:
            df = datetime.strptime(a["date_from"], "%Y-%m-%d").date()
            dt = datetime.strptime(a["date_to"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if df <= today <= dt:
            anns.append(dict(a))

    has_birthdays = len(bday_people) > 0
    has_announcements = len(anns) > 0

    images, videos = [], []
    if not has_birthdays and not has_announcements:
        images = [dict(r) for r in conn.execute(
            "SELECT * FROM images ORDER BY uploaded_at DESC"
        ).fetchall()]
        videos = [dict(r) for r in conn.execute(
            "SELECT * FROM videos ORDER BY uploaded_at DESC"
        ).fetchall()]

    conn.close()

    slides = []
    for grp in birthday_slides:
        slides.append({"type": "birthday", "people": grp})

    for a in anns:
        slides.append({
            "type": "announcement",
            "media_type": _media_type(a["filename"]),
            "src": f"/media/{a['filename']}",
        })

    if images or videos:
        media = []
        i = j = 0
        while i < len(images) or j < len(videos):
            if i < len(images):
                media.append({"type": "image", "image": f"/media/{images[i]['filename']}"})
                i += 1
            if j < len(videos):
                media.append({"type": "video", "video": f"/media/{videos[j]['filename']}"})
                j += 1
        slides.extend(media)

    return {
        "date": today.strftime("%d.%m.%Y"),
        "settings": settings,
        "slides": slides,
        "has_announcements": has_announcements,
        "has_birthdays": has_birthdays,
        "has_images": len(images) > 0,
        "has_videos": len(videos) > 0,
    }