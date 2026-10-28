from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl

import uvicorn
try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo
    AIROGRAM_AVAILABLE = True
except ImportError:
    # Local browser preview can run without aiogram installed; the Telegram bot itself cannot.
    AIROGRAM_AVAILABLE = False
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
LOCAL_DEV = os.getenv("LOCAL_DEV", "false").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_DEV_USER_ID = int(os.getenv("LOCAL_DEV_USER_ID", "123456789"))
LOCAL_DEV_ADMIN = os.getenv("LOCAL_DEV_ADMIN", "true").strip().lower() in {"1", "true", "yes", "on"}
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "rash_bot.sqlite3"))
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "127.0.0.1" if LOCAL_DEV else "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", "8080")))
INIT_DATA_MAX_AGE_SECONDS = int(os.getenv("INIT_DATA_MAX_AGE_SECONDS", "86400"))
ADMIN_IDS = {
    int(part.strip()) for part in os.getenv("ADMIN_IDS", "").split(",")
    if part.strip().isdigit()
}
# In LOCAL_DEV, create a local-only mock administrator to exercise the UI without Telegram.
if LOCAL_DEV and LOCAL_DEV_ADMIN:
    ADMIN_IDS.add(LOCAL_DEV_USER_ID)

app = FastAPI(title="RASH Telegram Mini App", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def db_session():
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_session() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at INTEGER NOT NULL,
            closed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            kind TEXT NOT NULL,
            options_json TEXT NOT NULL DEFAULT '[]',
            correct_answer TEXT NOT NULL,
            difficulty REAL,
            UNIQUE(test_id, position)
        );
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            submitted_at INTEGER NOT NULL,
            UNIQUE(test_id, question_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            raw_score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            percent REAL NOT NULL,
            theta REAL,
            submitted_at INTEGER NOT NULL,
            UNIQUE(test_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_answers_test ON answers(test_id);
        CREATE INDEX IF NOT EXISTS idx_results_user ON results(user_id);
        """)


def normalize_answer(value: str) -> str:
    value = value.strip().lower().replace("−", "-").replace(",", ".")
    return "".join(value.split())


def user_from_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Serverda BOT_TOKEN sozlanmagan.")
    if not init_data:
        raise HTTPException(status_code=401, detail="Ilovani Telegram ichidan oching.")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        parsed = dict(pairs)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Telegram ma'lumotlari noto'g'ri.") from exc

    received_hash = parsed.get("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram tasdiqlash imzosi topilmadi.")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(parsed.items())
        if key not in {"hash", "signature"}
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram imzosi tekshiruvdan o'tmadi.")

    try:
        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date > int(time.time()) + 60:
            raise ValueError("auth_date kelajakda")
        if int(time.time()) - auth_date > INIT_DATA_MAX_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="Telegram sessiyasi eskirgan. Ilovani qayta oching.")
        user = json.loads(parsed["user"])
        user_id = int(user["id"])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Telegram foydalanuvchi ma'lumoti noto'g'ri.") from exc

    user["id"] = user_id
    with db_session() as conn:
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, last_name, joined_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
        """, (user_id, user.get("username"), user.get("first_name", ""),
              user.get("last_name", ""), int(time.time())))
    return user


async def authenticated_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    if LOCAL_DEV:
        # IMPORTANT: this bypass is safe only for local-only development on 127.0.0.1.
        user = {
            "id": LOCAL_DEV_USER_ID,
            "username": "local_admin" if LOCAL_DEV_ADMIN else "local_user",
            "first_name": "Lokal",
            "last_name": "Administrator" if LOCAL_DEV_ADMIN else "Foydalanuvchi",
        }
        with db_session() as conn:
            conn.execute("""
                INSERT INTO users(user_id, username, first_name, last_name, joined_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name
            """, (user["id"], user["username"], user["first_name"], user["last_name"], int(time.time())))
        return user
    return user_from_init_data(x_telegram_init_data or "")


def require_admin(user: dict) -> None:
    if user["id"] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Bu bo'lim faqat administrator/o'qituvchi uchun. ADMIN_IDS sozlamasini tekshiring.")


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = "mcq"
    options: list[str] = Field(default_factory=list)
    correct_answer: str = Field(min_length=1, max_length=500)
    difficulty: float | None = None


class TestIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    questions: list[QuestionIn] = Field(min_length=1, max_length=200)


class AnswerIn(BaseModel):
    question_id: int
    answer: str = Field(max_length=2000)


class SubmitIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    answers: list[AnswerIn] = Field(min_length=1, max_length=200)


def generate_code(conn: sqlite3.Connection) -> str:
    for _ in range(200):
        code = f"{secrets.randbelow(900) + 100}"
        exists = conn.execute("SELECT 1 FROM tests WHERE code=?", (code,)).fetchone()
        if not exists:
            return code
    return str(secrets.randbelow(9000) + 1000)


def stable_sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def estimate_rasch(response_matrix: list[list[int]]) -> tuple[list[float], list[float]]:
    """Approximate dichotomous Rasch Joint Maximum Likelihood estimates.

    Returns (person theta estimates, item difficulty estimates). These are exploratory
    estimates; operational/exam-grade calibration needs representative samples,
    model-fit checks, anchors/equating and expert validation.
    """
    if not response_matrix or not response_matrix[0]:
        return [], []
    n_people = len(response_matrix)
    n_items = len(response_matrix[0])
    if any(len(row) != n_items for row in response_matrix):
        raise ValueError("Response matrix must be rectangular")

    item_b = []
    for j in range(n_items):
        total = sum(row[j] for row in response_matrix)
        # 0.5 continuity correction avoids infinite initial item estimates.
        item_b.append(math.log((n_people - total + 0.5) / (total + 0.5)))
    shift = sum(item_b) / n_items
    item_b = [b - shift for b in item_b]

    person_theta = []
    for row in response_matrix:
        score = sum(row)
        theta = math.log((score + 0.5) / (n_items - score + 0.5))
        person_theta.append(max(-4.5, min(4.5, theta)))

    for _ in range(100):
        max_delta = 0.0
        for i, row in enumerate(response_matrix):
            gradient = 0.0
            information = 0.05  # mild stabilization, especially for extreme scores
            for j, response in enumerate(row):
                p = stable_sigmoid(person_theta[i] - item_b[j])
                gradient += response - p
                information += p * (1.0 - p)
            delta = max(-0.5, min(0.5, gradient / information))
            person_theta[i] = max(-5.0, min(5.0, person_theta[i] + delta))
            max_delta = max(max_delta, abs(delta))

        for j in range(n_items):
            gradient = 0.0
            information = 0.05
            for i, row in enumerate(response_matrix):
                p = stable_sigmoid(person_theta[i] - item_b[j])
                gradient += p - row[j]
                information += p * (1.0 - p)
            delta = max(-0.5, min(0.5, gradient / information))
            item_b[j] = max(-5.0, min(5.0, item_b[j] + delta))
            max_delta = max(max_delta, abs(delta))

        # Fix scale location so mean item difficulty is zero.
        shift = sum(item_b) / n_items
        item_b = [b - shift for b in item_b]
        person_theta = [max(-5.0, min(5.0, t - shift)) for t in person_theta]
        if max_delta < 1e-4:
            break

    return person_theta, item_b


def close_test_and_calibrate(conn: sqlite3.Connection, test_id: int) -> dict:
    test = conn.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi.")
    if test["status"] == "closed":
        return {"participants": conn.execute("SELECT COUNT(*) n FROM results WHERE test_id=?", (test_id,)).fetchone()["n"], "already_closed": True}

    questions = conn.execute("SELECT id, position FROM questions WHERE test_id=? ORDER BY position", (test_id,)).fetchall()
    user_rows = conn.execute("SELECT DISTINCT user_id FROM results WHERE test_id=? ORDER BY user_id", (test_id,)).fetchall()
    users = [row["user_id"] for row in user_rows]
    if users and questions:
        answer_lookup = {
            (row["user_id"], row["question_id"]): row["is_correct"]
            for row in conn.execute("SELECT user_id, question_id, is_correct FROM answers WHERE test_id=?", (test_id,)).fetchall()
        }
        matrix = [[int(answer_lookup.get((user_id, question["id"]), 0)) for question in questions] for user_id in users]
        theta_values, item_values = estimate_rasch(matrix)
        for user_id, theta in zip(users, theta_values):
            conn.execute("UPDATE results SET theta=? WHERE test_id=? AND user_id=?", (round(theta, 4), test_id, user_id))
        for question, item_b in zip(questions, item_values):
            conn.execute("UPDATE questions SET difficulty=? WHERE id=?", (round(item_b, 4), question["id"]))
    conn.execute("UPDATE tests SET status='closed', closed_at=? WHERE id=?", (int(time.time()), test_id))
    return {"participants": len(users), "already_closed": False, "calibration_warning": len(users) < 30}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "service": "rash-telegram-miniapp"}


@app.get("/api/profile")
def profile(user: dict = Depends(authenticated_user)):
    with db_session() as conn:
        attempts = conn.execute("SELECT COUNT(*) n FROM results WHERE user_id=?", (user["id"],)).fetchone()["n"]
        user_row = conn.execute("SELECT * FROM users WHERE user_id=?", (user["id"],)).fetchone()
    return {
        "id": user["id"],
        "username": user.get("username"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "attempts": attempts,
        "is_admin": user["id"] in ADMIN_IDS,
        "joined_at": user_row["joined_at"] if user_row else None,
    }


@app.post("/api/tests")
def create_test(payload: TestIn, user: dict = Depends(authenticated_user)):
    require_admin(user)
    prepared = []
    for index, question in enumerate(payload.questions, start=1):
        kind = question.kind.lower().strip()
        if kind not in {"mcq", "short"}:
            raise HTTPException(status_code=422, detail=f"{index}-savol turi noto'g'ri.")
        options = [str(option).strip() for option in question.options if str(option).strip()]
        correct = question.correct_answer.strip()
        if kind == "mcq":
            options = [option.upper() if len(option) == 1 and option.upper() in "ABCD" else option for option in options]
            if len(options) < 2:
                raise HTTPException(status_code=422, detail=f"{index}-savol uchun kamida 2 ta variant kiriting.")
            if normalize_answer(correct) not in {normalize_answer(option) for option in options}:
                raise HTTPException(status_code=422, detail=f"{index}-savolning to'g'ri javobi variantlardan biri bo'lishi kerak.")
        elif not correct:
            raise HTTPException(status_code=422, detail=f"{index}-savol uchun to'g'ri javob kerak.")
        prepared.append((index, question.text.strip(), kind, options, correct, question.difficulty))

    with db_session() as conn:
        code = generate_code(conn)
        now = int(time.time())
        cur = conn.execute("INSERT INTO tests(code, title, creator_id, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                           (code, payload.title.strip(), user["id"], now))
        test_id = cur.lastrowid
        for position, text, kind, options, correct, difficulty in prepared:
            conn.execute("""INSERT INTO questions(test_id, position, text, kind, options_json, correct_answer, difficulty)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (test_id, position, text, kind, json.dumps(options, ensure_ascii=False), correct, difficulty))
    return {"ok": True, "id": test_id, "code": code, "title": payload.title.strip(), "questions": len(prepared)}


@app.get("/api/tests/mine")
def my_tests(user: dict = Depends(authenticated_user)):
    require_admin(user)
    with db_session() as conn:
        rows = conn.execute("""
            SELECT t.id, t.code, t.title, t.status, t.created_at, t.closed_at,
                   (SELECT COUNT(*) FROM questions q WHERE q.test_id=t.id) AS question_count,
                   (SELECT COUNT(*) FROM results r WHERE r.test_id=t.id) AS participant_count
            FROM tests t WHERE t.creator_id=? ORDER BY t.created_at DESC
        """, (user["id"],)).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/tests/by-code/{code}")
def get_test_by_code(code: str, user: dict = Depends(authenticated_user)):
    with db_session() as conn:
        test = conn.execute("SELECT id, code, title, status FROM tests WHERE code=?", (code.strip(),)).fetchone()
        if not test:
            raise HTTPException(status_code=404, detail="Bunday test kodi topilmadi.")
        if test["status"] != "active":
            raise HTTPException(status_code=410, detail="Bu test yakunlangan.")
        already = conn.execute("SELECT 1 FROM results WHERE test_id=? AND user_id=?", (test["id"], user["id"])).fetchone()
        if already:
            raise HTTPException(status_code=409, detail="Siz bu testni avval topshirgansiz.")
        questions = conn.execute("SELECT id, position, text, kind, options_json FROM questions WHERE test_id=? ORDER BY position", (test["id"],)).fetchall()
    return {
        "id": test["id"], "code": test["code"], "title": test["title"],
        "questions": [{"id": q["id"], "position": q["position"], "text": q["text"],
                       "kind": q["kind"], "options": json.loads(q["options_json"])} for q in questions]
    }


@app.post("/api/submit")
def submit_test(payload: SubmitIn, user: dict = Depends(authenticated_user)):
    with db_session() as conn:
        test = conn.execute("SELECT * FROM tests WHERE code=?", (payload.code.strip(),)).fetchone()
        if not test:
            raise HTTPException(status_code=404, detail="Test kodi topilmadi.")
        if test["status"] != "active":
            raise HTTPException(status_code=410, detail="Test yopilgan, javob yuborib bo'lmaydi.")
        if conn.execute("SELECT 1 FROM results WHERE test_id=? AND user_id=?", (test["id"], user["id"])).fetchone():
            raise HTTPException(status_code=409, detail="Bu test uchun javoblaringiz allaqachon yuborilgan.")

        questions = conn.execute("SELECT * FROM questions WHERE test_id=? ORDER BY position", (test["id"],)).fetchall()
        provided = {item.question_id: item.answer.strip() for item in payload.answers}
        question_ids = {q["id"] for q in questions}
        if len(provided) != len(payload.answers):
            raise HTTPException(status_code=422, detail="Bir savolga bir nechta javob yuborilgan.")
        if set(provided) != question_ids:
            raise HTTPException(status_code=422, detail="Har bir savolga javob belgilang.")

        raw_score = 0
        now = int(time.time())
        for q in questions:
            answer = provided[q["id"]]
            if not answer:
                raise HTTPException(status_code=422, detail=f"{q['position']}-savol javobsiz qolgan.")
            is_correct = int(normalize_answer(answer) == normalize_answer(q["correct_answer"]))
            raw_score += is_correct
            conn.execute("""INSERT INTO answers(test_id, question_id, user_id, answer, is_correct, submitted_at)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                         (test["id"], q["id"], user["id"], answer, is_correct, now))
        total = len(questions)
        percent = 100.0 * raw_score / total if total else 0.0
        conn.execute("""INSERT INTO results(test_id, user_id, raw_score, total_questions, percent, theta, submitted_at)
                        VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                     (test["id"], user["id"], raw_score, total, round(percent, 2), now))
    return {"ok": True, "title": test["title"], "raw_score": raw_score,
            "total_questions": total, "percent": round(percent, 2),
            "theta": None, "message": "Rasch theta test yakunlangandan keyin hisoblanadi."}


@app.get("/api/results")
def results(user: dict = Depends(authenticated_user)):
    with db_session() as conn:
        rows = conn.execute("""
            SELECT r.raw_score, r.total_questions, r.percent, r.theta, r.submitted_at,
                   t.title, t.code, t.status
            FROM results r JOIN tests t ON t.id=r.test_id
            WHERE r.user_id=? ORDER BY r.submitted_at DESC
        """, (user["id"],)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/tests/{test_id}/close")
def close_test(test_id: int, user: dict = Depends(authenticated_user)):
    require_admin(user)
    with db_session() as conn:
        test = conn.execute("SELECT creator_id FROM tests WHERE id=?", (test_id,)).fetchone()
        if not test:
            raise HTTPException(status_code=404, detail="Test topilmadi.")
        if test["creator_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Faqat test yaratuvchisi testni yopishi mumkin.")
        summary = close_test_and_calibrate(conn, test_id)
    summary["ok"] = True
    return summary


@app.get("/api/tests/{test_id}/responses")
def test_responses(test_id: int, user: dict = Depends(authenticated_user)):
    require_admin(user)
    with db_session() as conn:
        test = conn.execute("SELECT * FROM tests WHERE id=? AND creator_id=?", (test_id, user["id"])).fetchone()
        if not test:
            raise HTTPException(status_code=404, detail="Test topilmadi yoki sizga tegishli emas.")
        questions = conn.execute("SELECT id, position, text, difficulty FROM questions WHERE test_id=? ORDER BY position", (test_id,)).fetchall()
        participants = conn.execute("""
            SELECT r.user_id, u.first_name, u.last_name, u.username, r.raw_score,
                   r.total_questions, r.percent, r.theta, r.submitted_at
            FROM results r LEFT JOIN users u ON u.user_id=r.user_id
            WHERE r.test_id=? ORDER BY r.raw_score DESC, r.percent DESC
        """, (test_id,)).fetchall()
        answers = conn.execute("""
            SELECT a.user_id, a.question_id, a.answer, a.is_correct
            FROM answers a WHERE a.test_id=?
        """, (test_id,)).fetchall()
    answers_by_user: dict[int, dict[int, dict]] = {}
    for answer in answers:
        answers_by_user.setdefault(answer["user_id"], {})[answer["question_id"]] = {
            "answer": answer["answer"], "is_correct": bool(answer["is_correct"])
        }
    return {
        "test": {"id": test["id"], "code": test["code"], "title": test["title"], "status": test["status"]},
        "questions": [dict(q) for q in questions],
        "participants": [dict(p) | {"answers": answers_by_user.get(p["user_id"], {})} for p in participants],
        "calibration_warning": len(participants) < 30
    }


if AIROGRAM_AVAILABLE:
    # Telegram bot: buttons open the web app *inside* Telegram.
    dp = Dispatcher()


    def main_keyboard() -> InlineKeyboardMarkup:
        # Inline Web App buttons provide authenticated Telegram initData to the backend.
        # Reply-keyboard Web Apps can have empty initData, so they are unsuitable for
        # the protected profile/results/admin endpoints used by this application.
        def web_button(text: str, page: str) -> InlineKeyboardButton:
            return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{WEBAPP_URL}/?page={page}"))

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [web_button("📝 Javoblarni tekshirish", "check")],
                [web_button("📊 Mening natijalarim", "results"), web_button("👤 Profilim", "profile")],
                [web_button("➕ Test yaratish", "create")],
                [web_button("✅ Faol testlarni yakunlash", "finish")],
            ]
        )


    @dp.message(CommandStart())
    async def start_command(message: Message):
        if not WEBAPP_URL.startswith("https://"):
            await message.answer("Bot ishga tayyorlanmoqda, lekin WEBAPP_URL HTTPS manzili .env faylida sozlanmagan.")
            return
        await message.answer(
            "Assalomu alaykum! 👋\n\n"
            "RASH modeli asosidagi test platformasiga xush kelibsiz. Kerakli bo'limni pastdagi menyudan tanlang.\n\n"
            "Test yaratish va yakunlash uchun administrator ruxsati kerak.",
            reply_markup=main_keyboard(),
        )


    @dp.message(Command("id"))
    async def id_command(message: Message):
        await message.answer(f"Telegram ID: {message.from_user.id if message.from_user else 'aniqlanmadi'}")


    @dp.message(Command("help"))
    async def help_command(message: Message):
        await message.answer(
            "Foydalanish: menyudan kerakli bo'limni tanlang.\n"
            "• Test kodi bilan javob topshirish\n"
            "• Natijalarni ko'rish\n"
            "• Ruxsat berilgan bo'lsa, test yaratish va yakunlash\n\n"
            "Admin ID ni ko'rish: /id"
        )


    @dp.message(F.web_app_data)
    async def handle_web_app_data(message: Message):
        # Reply-keyboard Mini Apps may send a small data payload using sendData.
        # The full test submission flow in this project uses authenticated HTTPS API calls.
        await message.answer("Ilovadan ma'lumot qabul qilindi.", reply_markup=main_keyboard())




async def main() -> None:
    if LOCAL_DEV:
        if WEB_SERVER_HOST not in {"127.0.0.1", "localhost"}:
            raise RuntimeError(
                "LOCAL_DEV xavfsizligi uchun WEB_SERVER_HOST=127.0.0.1 yoki localhost bo'lishi kerak."
            )
        init_db()
        print("RASH Mini App lokal sinov rejimida: http://127.0.0.1:" + str(WEB_SERVER_PORT))
        print("Bu rejim Telegram bilan ulanmaydi; brauzerdagi sinov uchun soxta lokal profil ishlatiladi.")
        config = uvicorn.Config(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
        return

    if not AIROGRAM_AVAILABLE:
        raise RuntimeError("Telegram botni ishga tushirish uchun 'pip install -r requirements.txt' bajaring.")
    if not BOT_TOKEN or "PUT_YOUR_REAL_TOKEN_HERE" in BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN ni .env faylida @BotFather tokeniga almashtiring.")
    if not WEBAPP_URL.startswith("https://"):
        raise RuntimeError("WEBAPP_URL haqiqiy HTTPS domen bo'lishi kerak. README dagi deploy qadamlarini bajaring.")

    init_db()
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="RASH Test", web_app=WebAppInfo(url=f"{WEBAPP_URL}/?page=home"))
        )
    except Exception as exc:
        print(f"Could not configure Telegram chat menu button: {exc}")
    config = uvicorn.Config(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT, log_level="info", proxy_headers=True)
    server = uvicorn.Server(config)
    try:
        await asyncio.gather(dp.start_polling(bot), server.serve())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
