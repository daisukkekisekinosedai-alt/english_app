from __future__ import annotations

import asyncio
import csv
import os
import hashlib
import html
import io
import random
import re
import sqlite3
import time
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None


# =========================================================
# Numbered feature modules
# =========================================================
# 後から「1,4,5だけ使う」のように切り替えやすくするための機能番号です。
# 環境変数 ENABLED_FEATURES に "1,4,5" のように指定すると、その番号だけ有効になります。
FEATURE_MODULES = [
    {
        "id": 1,
        "key": "smart",
        "name": "スマート学習エンジン",
        "short_name": "スマート学習",
        "route": "smart",
        "emoji": "⚡",
        "description": "履歴を見て、今日やるべき単語を自動選定します。",
        "default_enabled": True,
    },
    {
        "id": 2,
        "key": "focus",
        "name": "集中モード",
        "short_name": "集中",
        "route": "focus",
        "emoji": "🧘",
        "description": "25分集中・10問・復習の流れを1画面にまとめます。",
        "default_enabled": True,
    },
    {
        "id": 3,
        "key": "plan",
        "name": "今日の学習計画",
        "short_name": "計画",
        "route": "plan",
        "emoji": "🗓️",
        "description": "今日のミッションと学習ロードマップを自動で出します。",
        "default_enabled": True,
    },
    {
        "id": 4,
        "key": "exam",
        "name": "試験モード",
        "short_name": "試験",
        "route": "exam",
        "emoji": "🎯",
        "description": "20問・30問の本番寄りドリルで得点力を確認します。",
        "default_enabled": True,
    },
    {
        "id": 5,
        "key": "mistakes",
        "name": "ミスノート",
        "short_name": "ミス",
        "route": "mistakes",
        "emoji": "🧠",
        "description": "間違えた単語を理由付きで集約し、復習導線を作ります。",
        "default_enabled": True,
    },
]

FEATURE_MODULE_MAP = {item["id"]: item for item in FEATURE_MODULES}
FEATURE_MODULE_KEY_MAP = {item["key"]: item for item in FEATURE_MODULES}


def enabled_feature_ids() -> set[int]:
    raw = os.environ.get("ENABLED_FEATURES", "").strip()
    if not raw:
        return {item["id"] for item in FEATURE_MODULES if item.get("default_enabled", True)}

    ids: set[int] = set()
    for part in re.split(r"[,、\s]+", raw):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids


def feature_enabled(feature_id: int | str) -> bool:
    if isinstance(feature_id, str):
        item = FEATURE_MODULE_KEY_MAP.get(feature_id)
        if not item:
            return False
        feature_id = item["id"]
    try:
        return int(feature_id) in enabled_feature_ids()
    except Exception:
        return False


def enabled_feature_modules() -> list[dict]:
    enabled = enabled_feature_ids()
    return [item for item in FEATURE_MODULES if item["id"] in enabled]


def feature_href(feature_id: int | str) -> str:
    try:
        fid = int(feature_id)
    except Exception:
        item = FEATURE_MODULE_KEY_MAP.get(str(feature_id))
        fid = item["id"] if item else 0

    route_map = {
        1: "smart",
        2: "focus",
        3: "plan",
        4: "exam",
        5: "mistakes",
    }
    endpoint = route_map.get(fid)
    if not endpoint:
        return "#"
    # ミスノートは直接開けるようにする。ナビ表示の有無とURLの到達性を分ける。
    if fid != 5 and not feature_enabled(fid):
        return "#"
    try:
        return url_for(endpoint)
    except Exception:
        return "#"



app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "english.db"))
AUDIO_DIR = BASE_DIR / "static" / "audio"
ICON_DIR = BASE_DIR / "static" / "uploads" / "icons"

DEFAULT_EDGE_VOICE = "en-US-JennyNeural"

EDGE_VOICES = [
    ("en-US-JennyNeural", "Jenny / 米国女性"),
    ("en-US-GuyNeural", "Guy / 米国男性"),
    ("en-US-AriaNeural", "Aria / 米国女性"),
    ("en-US-ChristopherNeural", "Christopher / 米国男性"),
    ("en-GB-SoniaNeural", "Sonia / 英国女性"),
    ("en-GB-RyanNeural", "Ryan / 英国男性"),
]


MASTER_USERNAME = os.environ.get("MASTER_USERNAME", "master").strip().lower()
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "giants")

CAT_TYPES = [
    {"key": "milk", "name": "ミルクねこ", "description": "いちばん標準。やさしく見守る相棒。", "preview": "images/cats/cat-neutral.png"},
    {"key": "playful", "name": "あそびねこ", "description": "元気系。正解した時にテンション高め。", "preview": "images/cats/cat-play.png"},
    {"key": "relax", "name": "まったりねこ", "description": "落ち着いた癒し系。休憩しながら学習。", "preview": "images/cats/cat-rest.png"},
    {"key": "sleepy", "name": "ねむねこ", "description": "ゆるい眠そうな猫。リスニングのお供に。", "preview": "images/cats/cat-sleepy.png"},
    {"key": "study", "name": "勉強ねこ", "description": "一緒に単語帳を開く勉強モード。", "preview": "images/cats/cat-study.png"},
]

CAT_TYPE_LABELS = {item["key"]: item["name"] for item in CAT_TYPES}

CAT_STATE_MAP = {
    "milk": {
        "home": "images/cats/cat-play.png",
        "neutral": "images/cats/cat-neutral.png",
        "quiz": "images/cats/cat-neutral.png",
        "listen": "images/cats/cat-sleepy.png",
        "correct": "images/cats/cat-play.png",
        "wrong": "images/cats/cat-sad.png",
        "finish_good": "images/cats/cat-play.png",
        "finish_ok": "images/cats/cat-rest.png",
        "finish_low": "images/cats/cat-sad.png",
    },
    "playful": {
        "home": "images/cats/cat-play.png",
        "neutral": "images/cats/cat-play.png",
        "quiz": "images/cats/cat-play.png",
        "listen": "images/cats/cat-neutral.png",
        "correct": "images/cats/cat-play.png",
        "wrong": "images/cats/cat-sad.png",
        "finish_good": "images/cats/cat-play.png",
        "finish_ok": "images/cats/cat-neutral.png",
        "finish_low": "images/cats/cat-sad.png",
    },
    "relax": {
        "home": "images/cats/cat-rest.png",
        "neutral": "images/cats/cat-rest.png",
        "quiz": "images/cats/cat-neutral.png",
        "listen": "images/cats/cat-sleepy.png",
        "correct": "images/cats/cat-neutral.png",
        "wrong": "images/cats/cat-sad.png",
        "finish_good": "images/cats/cat-play.png",
        "finish_ok": "images/cats/cat-rest.png",
        "finish_low": "images/cats/cat-sad.png",
    },
    "sleepy": {
        "home": "images/cats/cat-sleepy.png",
        "neutral": "images/cats/cat-sleepy.png",
        "quiz": "images/cats/cat-rest.png",
        "listen": "images/cats/cat-sleepy.png",
        "correct": "images/cats/cat-neutral.png",
        "wrong": "images/cats/cat-sad.png",
        "finish_good": "images/cats/cat-play.png",
        "finish_ok": "images/cats/cat-sleepy.png",
        "finish_low": "images/cats/cat-sad.png",
    },
    "study": {
        "home": "images/cats/cat-study.png",
        "neutral": "images/cats/cat-study.png",
        "quiz": "images/cats/cat-study.png",
        "listen": "images/cats/cat-neutral.png",
        "correct": "images/cats/cat-play.png",
        "wrong": "images/cats/cat-sad.png",
        "finish_good": "images/cats/cat-play.png",
        "finish_ok": "images/cats/cat-study.png",
        "finish_low": "images/cats/cat-sad.png",
    },
}


SAMPLE_WORDS = [
    ("apple", "りんご", "I ate an apple this morning.", "まずは定番の単語", "日常", 1),
    ("important", "重要な", "This meeting is important.", "仕事でもよく使う", "仕事", 2),
    ("develop", "開発する", "We develop a web application.", "アプリ開発でよく使う", "IT", 2),
    ("improve", "改善する", "I want to improve my English.", "成長系の単語", "学習", 2),
    ("customer", "顧客", "The customer asked a question.", "仕事向き", "仕事", 2),
    ("schedule", "予定", "Please check the schedule.", "業務で超頻出", "仕事", 1),
    ("confirm", "確認する", "Could you confirm this issue?", "メールで使える", "仕事", 2),
    ("explain", "説明する", "I will explain the reason.", "会議で使える", "仕事", 2),
    ("prepare", "準備する", "I need to prepare the document.", "日常でも仕事でも使う", "仕事", 1),
    ("decision", "決定", "We made a decision.", "名詞", "仕事", 2),
    ("environment", "環境", "This is a test environment.", "IT系で頻出", "IT", 2),
    ("result", "結果", "The result looks good.", "テスト結果など", "IT", 1),
    ("error", "エラー", "An error occurred.", "そのまま使える", "IT", 1),
    ("deploy", "デプロイする", "We deploy the app today.", "開発用語", "IT", 3),
    ("database", "データベース", "The data is stored in the database.", "DB", "IT", 2),
    ("practice", "練習する", "Practice makes progress.", "学習系", "学習", 1),
    ("remember", "覚える", "I remember this word.", "英単語学習っぽい", "学習", 1),
    ("review", "復習する", "Let's review weak words.", "復習", "学習", 1),
    ("feature", "機能", "This app has many features.", "アプリの機能", "IT", 2),
    ("progress", "進捗", "Please share your progress.", "仕事で使いやすい", "仕事", 2),
]


def get_db_connection() -> sqlite3.Connection:
    prepare_persistent_storage()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_answer(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    value = value.replace("　", " ")
    value = re.sub(r"\s+", " ", value)
    return value.lower()


def split_answers(japanese: str) -> list[str]:
    parts = re.split(r"[,、/／]", japanese)
    return [normalize_answer(part) for part in parts if normalize_answer(part)]


def is_answer_correct(user_answer: str, correct_answer: str) -> bool:
    """
    正解判定。

    重要:
    日本語訳が「主導権、取り組み」のように複数ある場合、
    入力式では「主導権」だけでも正解にしたい。
    一方で4択クイズでは、ボタンの値として「主導権、取り組み」全文が送られる。
    そのため「全文一致」と「分割後のどれかに一致」の両方を正解にする。
    """
    normalized = normalize_answer(user_answer)
    full_answer = normalize_answer(correct_answer)
    candidates = split_answers(correct_answer)

    if not normalized:
        return False

    return normalized == full_answer or normalized in candidates


def ensure_column(conn: sqlite3.Connection, table: str, column_name: str, ddl: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    prepare_persistent_storage()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            icon_file TEXT DEFAULT '',
            role TEXT DEFAULT 'user',
            cat_type TEXT DEFAULT 'milk',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            scope TEXT NOT NULL,
            total_count INTEGER NOT NULL,
            correct_count INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            share_text TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT NOT NULL,
            japanese TEXT NOT NULL,
            example TEXT DEFAULT '',
            memo TEXT DEFAULT '',
            audio_text TEXT DEFAULT '',
            audio_file TEXT DEFAULT '',
            example_audio_file TEXT DEFAULT '',
            category TEXT DEFAULT '未分類',
            part_of_speech TEXT DEFAULT '',
            level INTEGER DEFAULT 1,
            favorite INTEGER DEFAULT 0,
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            imported_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            invalid_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            deleted_at TEXT DEFAULT '',
            deleted_count INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            FOREIGN KEY (created_by_user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_word_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            favorite INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, word_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (word_id) REFERENCES words(id)
        )
        """
    )

    ensure_column(conn, "import_batches", "invalid_count", "invalid_count INTEGER DEFAULT 0")
    ensure_column(conn, "import_batches", "status", "status TEXT DEFAULT 'active'")
    ensure_column(conn, "import_batches", "deleted_at", "deleted_at TEXT DEFAULT ''")
    ensure_column(conn, "import_batches", "deleted_count", "deleted_count INTEGER DEFAULT 0")
    ensure_column(conn, "import_batches", "note", "note TEXT DEFAULT ''")

    # 旧版DBをそのまま使えるように列を追加します。
    ensure_column(conn, "words", "example", "example TEXT DEFAULT ''")
    ensure_column(conn, "words", "memo", "memo TEXT DEFAULT ''")
    ensure_column(conn, "words", "audio_text", "audio_text TEXT DEFAULT ''")
    ensure_column(conn, "words", "audio_file", "audio_file TEXT DEFAULT ''")
    ensure_column(conn, "words", "example_audio_file", "example_audio_file TEXT DEFAULT ''")
    ensure_column(conn, "words", "category", "category TEXT DEFAULT '未分類'")
    ensure_column(conn, "words", "part_of_speech", "part_of_speech TEXT DEFAULT ''")
    ensure_column(conn, "words", "level", "level INTEGER DEFAULT 1")
    ensure_column(conn, "words", "favorite", "favorite INTEGER DEFAULT 0")
    ensure_column(conn, "words", "created_by_user_id", "created_by_user_id INTEGER")
    ensure_column(conn, "words", "import_batch_id", "import_batch_id INTEGER")
    ensure_column(conn, "words", "created_at", f"created_at TEXT DEFAULT '{now_text()}'")
    ensure_column(conn, "words", "updated_at", f"updated_at TEXT DEFAULT '{now_text()}'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS study_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            user_answer TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (word_id) REFERENCES words(id)
        )
        """
    )

    ensure_column(conn, "study_logs", "user_id", "user_id INTEGER")
    ensure_column(conn, "study_logs", "test_session_id", "test_session_id INTEGER")
    ensure_column(conn, "users", "display_name", "display_name TEXT DEFAULT ''")
    ensure_column(conn, "users", "icon_file", "icon_file TEXT DEFAULT ''")
    ensure_column(conn, "users", "updated_at", f"updated_at TEXT DEFAULT '{now_text()}'")

    ensure_column(conn, "users", "role", "role TEXT DEFAULT 'user'")
    ensure_column(conn, "users", "cat_type", "cat_type TEXT DEFAULT 'milk'")

    # masterユーザー設定:
    # masterアカウントは固定で username=master / password=giants を自動作成します。
    # 最初に登録した通常ユーザーをmasterにする方式は使いません。
    master_hash = generate_password_hash(MASTER_PASSWORD)
    existing_master = conn.execute("SELECT id FROM users WHERE lower(username) = ?", (MASTER_USERNAME,)).fetchone()
    if existing_master:
        conn.execute(
            """
            UPDATE users
            SET display_name = 'master',
                password_hash = ?,
                role = 'master',
                cat_type = COALESCE(NULLIF(cat_type, ''), 'study'),
                updated_at = ?
            WHERE id = ?
            """,
            (master_hash, now_text(), existing_master["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, cat_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (MASTER_USERNAME, "master", master_hash, "master", "study", now_text(), now_text()),
        )

    # master以外は通常ユーザーに戻す。
    conn.execute("UPDATE users SET role = 'user' WHERE lower(username) != ?", (MASTER_USERNAME,))

    ensure_column(conn, "test_sessions", "share_text", "share_text TEXT DEFAULT ''")

    backfill_part_of_speech(conn)
    conn.commit()
    conn.close()



def get_tts_text(word: sqlite3.Row) -> str:
    return (word["audio_text"] or word["english"] or "").strip()


def safe_audio_filename(text: str, suffix: str = "word", ext: str = "mp3") -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{suffix}_{digest}.{ext}"


def clean_text_for_tts(text: str) -> str:
    clean_text = (text or "").strip()
    clean_text = re.sub(r"\s+", " ", clean_text)

    # 短い英文は句点を足した方が自然に読みやすい。
    if clean_text and not re.search(r"[.!?]$", clean_text):
        clean_text += "."

    return clean_text


def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def pick_english_voice(engine):
    try:
        voices = engine.getProperty("voices")
        for voice in voices:
            voice_text = " ".join([
                str(getattr(voice, "id", "")),
                str(getattr(voice, "name", "")),
                " ".join(getattr(voice, "languages", []) or []),
            ]).lower()
            if "en-us" in voice_text or "english" in voice_text or "zira" in voice_text or "david" in voice_text:
                engine.setProperty("voice", voice.id)
                return
    except Exception:
        return


def generate_audio_file(
    text: str,
    suffix: str = "word",
    prefer: str = "edge",
    voice: str = DEFAULT_EDGE_VOICE,
    rate: str = "+0%",
) -> tuple[str | None, str | None]:
    """
    無料で音声ファイルを作る。
    1. edge-tts: APIキー不要、mp3、自然寄り、ネット接続が必要
    2. gTTS: APIキー不要、mp3、ネット接続が必要
    3. pyttsx3: 完全ローカル、wav、PCの英語音声に依存
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    clean_text = clean_text_for_tts(text)
    if not clean_text:
        return None, "読み上げるテキストが空です。"

    # Edge TTS: 無料・APIキー不要・自然寄りのニューラル音声。
    if prefer in ("edge", "auto") and edge_tts is not None:
        try:
            filename = safe_audio_filename(f"{voice}|{rate}|{clean_text}", suffix=suffix, ext="mp3")
            output_path = AUDIO_DIR / filename
            if not output_path.exists():
                communicate = edge_tts.Communicate(clean_text, voice=voice, rate=rate)
                run_async(communicate.save(str(output_path)))
            return f"audio/{filename}", None
        except Exception as exc:
            edge_error = str(exc)
        else:
            edge_error = ""
    else:
        edge_error = ""

    # gTTS: Edgeが失敗した場合のフォールバック。
    if prefer in ("gtts", "auto", "edge") and gTTS is not None:
        try:
            filename = safe_audio_filename(clean_text, suffix=suffix, ext="mp3")
            output_path = AUDIO_DIR / filename
            if not output_path.exists():
                tts = gTTS(text=clean_text, lang="en", slow=False)
                tts.save(str(output_path))
            return f"audio/{filename}", None
        except Exception as exc:
            gtts_error = str(exc)
        else:
            gtts_error = ""
    else:
        gtts_error = ""

    # pyttsx3: ネットがない場合の最終フォールバック。
    if pyttsx3 is not None:
        try:
            filename = safe_audio_filename(clean_text, suffix=suffix, ext="wav")
            output_path = AUDIO_DIR / filename
            if not output_path.exists():
                engine = pyttsx3.init()
                pick_english_voice(engine)
                engine.setProperty("rate", 145)
                engine.setProperty("volume", 1.0)
                engine.save_to_file(clean_text, str(output_path))
                engine.runAndWait()
                for _ in range(10):
                    if output_path.exists() and output_path.stat().st_size > 0:
                        break
                    time.sleep(0.1)
            return f"audio/{filename}", None
        except Exception as exc:
            return None, f"音声生成に失敗しました: edge={edge_error}, gtts={gtts_error}, local={exc}"

    return None, "edge-tts / gTTS / pyttsx3 が利用できません。requirements.txt をインストールしてください。"


def save_word_audio_path(word_id: int, column_name: str, audio_path: str) -> None:
    if column_name not in ("audio_file", "example_audio_file"):
        return
    conn = get_db_connection()
    conn.execute(
        f"UPDATE words SET {column_name} = ?, updated_at = ? WHERE id = ?",
        (audio_path, now_text(), word_id),
    )
    conn.commit()
    conn.close()



def prepare_persistent_storage() -> None:
    """
    ローカルではプロジェクト内に保存します。
    Renderでは DATA_DIR=/var/data を指定すると、
    DB・生成音声・アップロード画像を永続ディスク側へ保存できます。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if DATA_DIR.resolve() == BASE_DIR.resolve():
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        return

    persistent_static = DATA_DIR / "static"
    persistent_audio = persistent_static / "audio"
    persistent_uploads = persistent_static / "uploads"
    persistent_icons = persistent_uploads / "icons"

    persistent_audio.mkdir(parents=True, exist_ok=True)
    persistent_icons.mkdir(parents=True, exist_ok=True)

    link_targets = [
        (BASE_DIR / "static" / "audio", persistent_audio),
        (BASE_DIR / "static" / "uploads", persistent_uploads),
    ]

    for link_path, target_path in link_targets:
        try:
            if link_path.is_symlink():
                if link_path.resolve() == target_path.resolve():
                    continue
                link_path.unlink()
            elif link_path.exists():
                if link_path.is_dir() and not any(link_path.iterdir()):
                    link_path.rmdir()
                else:
                    continue

            link_path.parent.mkdir(parents=True, exist_ok=True)
            link_path.symlink_to(target_path, target_is_directory=True)
        except Exception:
            link_path.mkdir(parents=True, exist_ok=True)


ALLOWED_ICON_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def current_user_id() -> int | None:
    value = session.get("user_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_user(user_id: int | None) -> sqlite3.Row | None:
    if user_id is None:
        return None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def get_current_user() -> sqlite3.Row | None:
    return get_user(current_user_id())


def get_user_role(user: sqlite3.Row | None) -> str:
    if not user:
        return ""
    try:
        return (user["role"] or "").strip().lower()
    except Exception:
        return ""


def is_master_user(user: sqlite3.Row | None = None) -> bool:
    if user is None:
        user = get_current_user()
    if not user:
        return False

    try:
        username = (user["username"] or "").strip().lower()
    except Exception:
        username = ""

    return get_user_role(user) == "master" or username == MASTER_USERNAME


def master_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return redirect(url_for("login", next=request.path))
        if not is_master_user():
            return render_template("permission_denied.html"), 403
        return view_func(*args, **kwargs)
    return wrapped


def get_cat_type_key(user: sqlite3.Row | None = None) -> str:
    if user is None:
        user = get_current_user()
    if not user:
        return "milk"
    try:
        key = (user["cat_type"] or "milk").strip()
    except Exception:
        key = "milk"
    return key if key in CAT_STATE_MAP else "milk"


def cat_type_label(key: str | None) -> str:
    return CAT_TYPE_LABELS.get(key or "milk", CAT_TYPE_LABELS["milk"])


def cat_image(state: str = "neutral") -> str:
    key = get_cat_type_key()
    return CAT_STATE_MAP.get(key, CAT_STATE_MAP["milk"]).get(state, CAT_STATE_MAP["milk"]["neutral"])


def progress_percent(value: int | float, target: int | float) -> int:
    if target <= 0:
        return 100
    return max(0, min(100, int((value / target) * 100)))


def get_cat_room_items(stats: dict) -> list[dict]:
    """
    DBを増やさず、既存の学習履歴から猫の部屋アイテム解放を判定します。
    masterアカウントの場合は家具をすべて解放済みにします。
    """
    master_room_mode = is_master_user()

    total_logs = int(stats.get("total_logs", 0) or 0)
    correct_logs = int(stats.get("correct_logs", 0) or 0)
    favorite_words = int(stats.get("favorite_words", 0) or 0)
    accuracy = float(stats.get("accuracy", 0) or 0)

    game = stats.get("gamification", {}).get("game", {})
    streak = stats.get("gamification", {}).get("streak", {})
    level = int(game.get("level", 1) or 1)
    perfect_sessions = int(game.get("perfect_sessions", 0) or 0)
    current_streak = int(streak.get("current", 0) or 0)
    longest_streak = int(streak.get("longest", 0) or 0)

    raw_items = [
        {
            "key": "cushion",
            "name": "プリンセス猫ベッド",
            "emoji": "🛋️",
            "image": "images/room_items/royal_bed.png",
            "condition": total_logs >= 10,
            "progress": progress_percent(total_logs, 10),
            "requirement": "10問回答で解放",
            "message": "猫が主役になれる、ふかふか王座ベッド。",
            "style": "left: 13%; bottom: 18%;",
        },
        {
            "key": "yarn",
            "name": "おもちゃチェスト",
            "emoji": "🧶",
            "image": "images/room_items/toy_chest.png",
            "condition": current_streak >= 3 or longest_streak >= 3,
            "progress": progress_percent(max(current_streak, longest_streak), 3),
            "requirement": "3日連続学習で解放",
            "message": "お気に入りのおもちゃをしまえる高級チェスト。",
            "style": "right: 16%; bottom: 18%;",
        },
        {
            "key": "crown",
            "name": "ハートソファ",
            "emoji": "👑",
            "image": "images/room_items/heart_sofa.png",
            "condition": perfect_sessions >= 1,
            "progress": progress_percent(perfect_sessions, 1),
            "requirement": "10問満点1回で解放",
            "message": "満点を取った猫だけが座れる、ごほうびソファ。",
            "style": "left: 50%; top: 18%;",
        },
        {
            "key": "tower",
            "name": "プリンセスキャットタワー",
            "emoji": "🗼",
            "image": "images/room_items/princess_tower.png",
            "condition": total_logs >= 100,
            "progress": progress_percent(total_logs, 100),
            "requirement": "100問回答で解放",
            "message": "部屋の主役になる、ピンクの豪華キャットタワー。",
            "style": "right: 7%; bottom: 34%;",
        },
        {
            "key": "bookshelf",
            "name": "クラシックソファ",
            "emoji": "📚",
            "image": "images/room_items/red_sofa.png",
            "condition": level >= 10,
            "progress": progress_percent(level, 10),
            "requirement": "Lv10で解放",
            "message": "落ち着いて英単語を眺めるためのクラシックソファ。",
            "style": "left: 7%; bottom: 38%;",
        },
        {
            "key": "trophy",
            "name": "星を見る望遠鏡",
            "emoji": "🏆",
            "image": "images/room_items/telescope.png",
            "condition": total_logs >= 500,
            "progress": progress_percent(total_logs, 500),
            "requirement": "500問回答で解放",
            "message": "努力の先を見渡すための特別な望遠鏡。",
            "style": "right: 30%; top: 24%;",
        },
        {
            "key": "fish",
            "name": "フードステーション",
            "emoji": "🐟",
            "image": "images/room_items/food_station.png",
            "condition": favorite_words >= 5,
            "progress": progress_percent(favorite_words, 5),
            "requirement": "お気に入り5語で解放",
            "message": "お気に入り単語のごほうびフードステーション。",
            "style": "left: 29%; bottom: 12%;",
        },
        {
            "key": "ribbon",
            "name": "モンステラ観葉植物",
            "emoji": "🎀",
            "image": "images/room_items/monstera.png",
            "condition": accuracy >= 80 and total_logs >= 30,
            "progress": min(progress_percent(accuracy, 80), progress_percent(total_logs, 30)),
            "requirement": "30問以上回答かつ正答率80%以上で解放",
            "message": "正答率が育つほど、部屋にも緑が増えます。",
            "style": "right: 42%; top: 12%;",
        },
        {
            "key": "window",
            "name": "展望ソファ",
            "emoji": "🌙",
            "image": "images/room_items/red_sofa.png",
            "condition": longest_streak >= 7,
            "progress": progress_percent(longest_streak, 7),
            "requirement": "7日連続学習で解放",
            "message": "連続学習の景色を眺めるための特等席。",
            "style": "left: 33%; top: 18%;",
        },
        {
            "key": "plant",
            "name": "語彙の観葉植物",
            "emoji": "🌿",
            "image": "images/room_items/monstera.png",
            "condition": correct_logs >= 100,
            "progress": progress_percent(correct_logs, 100),
            "requirement": "100問正解で解放",
            "message": "正解が増えるほど、部屋も育ちます。",
            "style": "left: 17%; top: 28%;",
        },
    ]

    for item in raw_items:
        if master_room_mode:
            item["unlocked"] = True
            item["progress"] = 100
            item["message"] = item["message"] + " masterなので最初から使用できます。"
        else:
            item["unlocked"] = bool(item["condition"])

    return raw_items


def get_cat_room_summary(items: list[dict]) -> dict:
    unlocked = [item for item in items if item["unlocked"]]
    locked = [item for item in items if not item["unlocked"]]
    next_item = sorted(locked, key=lambda item: item["progress"], reverse=True)[0] if locked else None

    if len(unlocked) == len(items):
        message = "全部そろったにゃ。ここはもう語彙王の猫部屋です。"
    elif len(unlocked) >= 6:
        message = "だいぶ部屋が育ってきたにゃ。あと少しで豪邸です。"
    elif len(unlocked) >= 3:
        message = "いい感じに家具が増えてきたにゃ。毎日の学習がちゃんと形になってます。"
    elif len(unlocked) >= 1:
        message = "最初の家具をゲット。ここから猫部屋を育てよう。"
    else:
        message = "まだ何もない部屋。まずは10問解いてクッションを置こう。"

    return {
        "unlocked_count": len(unlocked),
        "total_count": len(items),
        "locked_count": len(locked),
        "next_item": next_item,
        "message": message,
        "completion": progress_percent(len(unlocked), len(items)),
    }



def get_weak_category_insight(user_id: int | None) -> dict | None:
    if user_id is None:
        return None

    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(w.category, ''), '未分類') AS category,
            COUNT(l.id) AS total_count,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            ROUND(100.0 * SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(l.id), 1) AS accuracy
        FROM study_logs l
        JOIN words w ON w.id = l.word_id
        WHERE l.user_id = ?
        GROUP BY COALESCE(NULLIF(w.category, ''), '未分類')
        HAVING total_count >= 3
        ORDER BY accuracy ASC, total_count DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "category": row["category"],
        "total_count": row["total_count"],
        "correct_count": row["correct_count"] or 0,
        "accuracy": row["accuracy"] or 0,
    }


def get_weak_pos_insight(user_id: int | None) -> dict | None:
    if user_id is None:
        return None

    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(w.part_of_speech, ''), 'other') AS part_of_speech,
            COUNT(l.id) AS total_count,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            ROUND(100.0 * SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(l.id), 1) AS accuracy
        FROM study_logs l
        JOIN words w ON w.id = l.word_id
        WHERE l.user_id = ?
        GROUP BY COALESCE(NULLIF(w.part_of_speech, ''), 'other')
        HAVING total_count >= 3
        ORDER BY accuracy ASC, total_count DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "part_of_speech": row["part_of_speech"],
        "label": part_of_speech_label(row["part_of_speech"]),
        "total_count": row["total_count"],
        "correct_count": row["correct_count"] or 0,
        "accuracy": row["accuracy"] or 0,
    }


def get_due_review_count(user_id: int | None) -> int:
    if user_id is None:
        return 0

    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT
                w.id,
                MAX(l.created_at) AS last_answered_at,
                SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count,
                SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count
            FROM words w
            JOIN study_logs l ON l.word_id = w.id
            WHERE l.user_id = ?
            GROUP BY w.id
            HAVING wrong_count > 0
               AND datetime(last_answered_at) <= datetime('now', '-1 day', 'localtime')
        )
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return row["count"] if row else 0


def parse_datetime_safe(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:19], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")[:19])
    except Exception:
        return None


def days_since(value: str | None) -> int | None:
    dt = parse_datetime_safe(value)
    if dt is None:
        return None
    return max(0, (datetime.now() - dt).days)


def smart_scope_label(scope: str) -> str:
    labels = {
        "all": "全単語",
        "weak": "苦手単語",
        "favorite": "お気に入り",
        "today_wrong": "今日のミス",
        "repeat_wrong": "繰り返しミス",
        "stale": "久しぶりの単語",
        "smart": "おすすめ",
    }
    if scope.startswith("category:"):
        return scope.split(":", 1)[1]
    return labels.get(scope, scope)


def get_word_learning_profiles(user_id: int | None = None) -> list[dict]:
    uid = user_id if user_id is not None else current_user_id()
    if uid is None:
        return []

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            w.id,
            w.english,
            w.japanese,
            w.category,
            w.part_of_speech,
            w.level,
            COUNT(l.id) AS attempts,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count,
            MAX(l.created_at) AS last_answered_at,
            MAX(CASE WHEN l.is_correct = 0 THEN l.created_at ELSE NULL END) AS last_wrong_at,
            MAX(CASE WHEN l.is_correct = 1 THEN l.created_at ELSE NULL END) AS last_correct_at
        FROM words w
        LEFT JOIN study_logs l
          ON l.word_id = w.id
         AND l.user_id = ?
        GROUP BY w.id
        """,
        (uid,),
    ).fetchall()
    conn.close()

    profiles = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        accuracy = round((correct_count / attempts) * 100, 1) if attempts else None
        last_days = days_since(row["last_answered_at"])
        wrong_days = days_since(row["last_wrong_at"])

        score = 0
        reason = "新規"
        bucket = "new"

        if attempts == 0:
            score = 86
            reason = "まだ一度も解いていない新規単語"
            bucket = "new"
        else:
            # 復習間隔: ミスが多いほど短く、正解が多いほど長く
            if wrong_count >= 3:
                due_after = 1
            elif wrong_count >= 1:
                due_after = 2
            elif correct_count >= 3:
                due_after = 10
            else:
                due_after = 4

            is_due = last_days is not None and last_days >= due_after
            if wrong_count > 0 and wrong_days is not None and wrong_days >= 1:
                score = 95 + min(wrong_count * 4, 20)
                reason = f"{wrong_count}回ミス。復習タイミング"
                bucket = "due"
            elif accuracy is not None and accuracy < 60 and attempts >= 2:
                score = 88 + min(wrong_count * 3, 12)
                reason = f"正答率{accuracy}%で弱点候補"
                bucket = "weak"
            elif is_due:
                score = 74 + min(last_days or 0, 18)
                reason = f"{last_days}日ぶり。忘却防止"
                bucket = "stale"
            elif attempts == 1:
                score = 68
                reason = "1回だけ解いた単語。定着確認"
                bucket = "followup"
            else:
                score = 36
                reason = "定着済み候補"
                bucket = "mastered"

        profiles.append(
            {
                "id": row["id"],
                "english": row["english"],
                "japanese": row["japanese"],
                "category": row["category"] or "未分類",
                "part_of_speech": normalize_part_of_speech(row["part_of_speech"]) or "other",
                "part_of_speech_label": part_of_speech_label(row["part_of_speech"]),
                "level": row["level"],
                "attempts": attempts,
                "correct_count": correct_count,
                "wrong_count": wrong_count,
                "accuracy": accuracy,
                "last_answered_at": row["last_answered_at"],
                "last_wrong_at": row["last_wrong_at"],
                "days_since_last": last_days,
                "score": int(score),
                "reason": reason,
                "bucket": bucket,
            }
        )

    profiles.sort(key=lambda item: (-item["score"], item["attempts"], item["english"].lower()))
    return profiles


def get_smart_candidate_ids(user_id: int | None = None, limit: int = 30) -> list[int]:
    profiles = get_word_learning_profiles(user_id)
    if not profiles:
        return []

    # バランスよく選ぶ: 復習/弱点/新規/忘却防止を混ぜる
    buckets = {
        "due": [],
        "weak": [],
        "new": [],
        "stale": [],
        "followup": [],
        "mastered": [],
    }
    for profile in profiles:
        buckets.setdefault(profile["bucket"], []).append(profile)

    selected = []
    recipe = [
        ("due", 4),
        ("weak", 3),
        ("stale", 2),
        ("new", 3),
        ("followup", 2),
        ("mastered", 1),
    ]

    used = set()
    for bucket, take in recipe:
        for profile in buckets.get(bucket, [])[:take]:
            if profile["id"] not in used:
                selected.append(profile)
                used.add(profile["id"])

    for profile in profiles:
        if len(selected) >= limit:
            break
        if profile["id"] not in used:
            selected.append(profile)
            used.add(profile["id"])

    return [item["id"] for item in selected[:limit]]


def get_smart_breakdown(profiles: list[dict]) -> dict:
    buckets = {
        "due": {"label": "復習優先", "count": 0},
        "weak": {"label": "弱点候補", "count": 0},
        "new": {"label": "新規単語", "count": 0},
        "stale": {"label": "忘却防止", "count": 0},
        "followup": {"label": "定着確認", "count": 0},
        "mastered": {"label": "定着済み", "count": 0},
    }
    for profile in profiles:
        if profile["bucket"] in buckets:
            buckets[profile["bucket"]]["count"] += 1
    return buckets


def get_category_weakness_profiles(user_id: int | None = None, limit: int = 5) -> list[dict]:
    uid = user_id if user_id is not None else current_user_id()
    if uid is None:
        return []

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(w.category, ''), '未分類') AS category,
            COUNT(l.id) AS attempts,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count
        FROM study_logs l
        JOIN words w ON w.id = l.word_id
        WHERE l.user_id = ?
        GROUP BY COALESCE(NULLIF(w.category, ''), '未分類')
        HAVING attempts >= 3
        ORDER BY (1.0 * wrong_count / attempts) DESC, attempts DESC
        LIMIT ?
        """,
        (uid, limit),
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        correct = int(row["correct_count"] or 0)
        accuracy = round((correct / attempts) * 100, 1) if attempts else 0
        result.append({
            "category": row["category"],
            "attempts": attempts,
            "correct_count": correct,
            "wrong_count": int(row["wrong_count"] or 0),
            "accuracy": accuracy,
        })
    return result


def get_pos_weakness_profiles(user_id: int | None = None, limit: int = 5) -> list[dict]:
    uid = user_id if user_id is not None else current_user_id()
    if uid is None:
        return []

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(w.part_of_speech, ''), 'other') AS part_of_speech,
            COUNT(l.id) AS attempts,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count
        FROM study_logs l
        JOIN words w ON w.id = l.word_id
        WHERE l.user_id = ?
        GROUP BY COALESCE(NULLIF(w.part_of_speech, ''), 'other')
        HAVING attempts >= 3
        ORDER BY (1.0 * wrong_count / attempts) DESC, attempts DESC
        LIMIT ?
        """,
        (uid, limit),
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        correct = int(row["correct_count"] or 0)
        accuracy = round((correct / attempts) * 100, 1) if attempts else 0
        pos = normalize_part_of_speech(row["part_of_speech"]) or "other"
        result.append({
            "part_of_speech": pos,
            "label": part_of_speech_label(pos),
            "attempts": attempts,
            "correct_count": correct,
            "wrong_count": int(row["wrong_count"] or 0),
            "accuracy": accuracy,
        })
    return result


def build_smart_study_plan(user_id: int | None = None) -> dict:
    uid = user_id if user_id is not None else current_user_id()
    stats = get_stats(uid) if uid is not None else get_stats()
    profiles = get_word_learning_profiles(uid)
    top_words = profiles[:12]
    breakdown = get_smart_breakdown(profiles)
    category_weakness = get_category_weakness_profiles(uid)
    pos_weakness = get_pos_weakness_profiles(uid)

    due_count = breakdown["due"]["count"]
    weak_count = breakdown["weak"]["count"]
    new_count = breakdown["new"]["count"]
    stale_count = breakdown["stale"]["count"]

    if not profiles:
        title = "単語を入れると、学習プランを自動生成できます"
        message = "まずはCSVインポートか単語追加から始めましょう。履歴が貯まると、あなた専用の復習順に並びます。"
        mode = "empty"
    elif stats["total_logs"] == 0:
        title = "最初の10問で診断を開始します"
        message = "まだ回答履歴がないので、新規単語から10問選びます。1回解くと、次回から弱点と復習タイミングを自動判定できます。"
        mode = "start"
    elif due_count >= 5:
        title = "今日は復習を先に回収する日です"
        message = f"復習優先の単語が{due_count}語あります。おすすめ10問では、忘れやすい単語を先に出します。"
        mode = "review"
    elif weak_count >= 5:
        title = "弱点を潰すと一気に伸びます"
        message = f"弱点候補が{weak_count}語あります。今日は正答率が低い単語を中心に出します。"
        mode = "weak"
    elif stale_count >= 10:
        title = "忘却防止の日です"
        message = f"7日以上触れていない単語が{stale_count}語あります。忘れる前に軽く確認しましょう。"
        mode = "stale"
    else:
        title = "今日はバランス型で進めます"
        message = "復習・弱点・新規を混ぜたおすすめ10問を作りました。迷ったらこれだけでOKです。"
        mode = "balanced"

    missions = [
        {
            "title": "おすすめ10問を完走",
            "description": "復習・弱点・新規を自動で混ぜた10問です。",
            "done": False,
            "url": url_for("session_start", mode="choice", scope="smart", count=10),
            "button": "おすすめ10問",
        },
        {
            "title": "復習対象を1セット回収",
            "description": f"復習優先: {due_count}語",
            "done": due_count == 0 and stats["total_logs"] > 0,
            "url": url_for("session_start", mode="choice", scope="smart", count=10),
            "button": "復習する",
        },
        {
            "title": "弱点を確認",
            "description": f"弱点候補: {weak_count}語",
            "done": weak_count == 0 and stats["total_logs"] >= 10,
            "url": url_for("weak"),
            "button": "弱点を見る",
        },
    ]

    return {
        "title": title,
        "message": message,
        "mode": mode,
        "stats": stats,
        "profiles": profiles,
        "top_words": top_words,
        "breakdown": breakdown,
        "category_weakness": category_weakness,
        "pos_weakness": pos_weakness,
        "missions": missions,
    }



def build_learning_coach(stats: dict, user_id: int | None = None) -> dict:
    """
    にゃんコーチのコメントを作ります。
    DBに新しいテーブルは作らず、既存の学習履歴から判断します。
    """
    uid = user_id if user_id is not None else current_user_id()
    total = int(stats.get("total_logs", 0) or 0)
    correct = int(stats.get("correct_logs", 0) or 0)
    accuracy = float(stats.get("accuracy", 0) or 0)
    review_stats = stats.get("review_stats", {}) or {}
    gamification = stats.get("gamification", {}) or {}
    streak = gamification.get("streak", {}) or {}
    game = gamification.get("game", {}) or {}

    weak_category = get_weak_category_insight(uid)
    weak_pos = get_weak_pos_insight(uid)
    due_review = get_due_review_count(uid)

    actions: list[dict] = []

    if total == 0:
        title = "まずは10問、にゃんコーチと始めるにゃ"
        message = "最初は正答率よりも、回答履歴を作ることが大事です。10問解くと、次からあなた専用の弱点コメントが出しやすくなります。"
        tone = "start"
        actions.append({"label": "まず10問やる", "endpoint": "session_start", "params": {"mode": "choice", "scope": "all", "count": 10}})
    elif due_review >= 5:
        title = "今日は復習回収日だにゃ"
        message = f"復習タイミングの単語が {due_review} 語あります。新しい単語を増やす前に、昨日以前に間違えた単語を軽く回収すると定着しやすいです。"
        tone = "review"
        actions.append({"label": "復習する", "endpoint": "review", "params": {}})
    elif weak_category and weak_category["accuracy"] < 70:
        title = f"{weak_category['category']} を少し鍛えたいにゃ"
        message = f"{weak_category['category']} の正答率が {weak_category['accuracy']}% です。今日はこのカテゴリを意識して、似た意味の単語をまとめて覚えるのがおすすめです。"
        tone = "weak"
        actions.append({"label": f"{weak_category['category']}を見る", "endpoint": "words", "params": {"category": weak_category["category"]}})
    elif weak_pos and weak_pos["accuracy"] < 70:
        title = f"{weak_pos['label']}で少しミスが出てるにゃ"
        message = f"{weak_pos['label']}の正答率が {weak_pos['accuracy']}% です。4択は同じ品詞から出るので、意味の細かい違いを確認すると一気に伸びます。"
        tone = "weak"
        actions.append({"label": "苦手単語を見る", "endpoint": "weak", "params": {}})
    elif accuracy >= 90 and total >= 30:
        title = "かなり強いにゃ、次はスピード勝負"
        message = f"累計正答率 {accuracy}% はかなり優秀です。次は10問をテンポよく解いて、迷う単語だけ復習に回すと効率が上がります。"
        tone = "good"
        actions.append({"label": "10問チャレンジ", "endpoint": "session_start", "params": {"mode": "choice", "scope": "all", "count": 10}})
    elif accuracy >= 75:
        title = "いい感じに育ってるにゃ"
        message = f"正答率 {accuracy}% で安定してきています。今日は苦手単語を少し混ぜると、得点力がもう一段上がります。"
        tone = "good"
        actions.append({"label": "苦手10問", "endpoint": "session_start", "params": {"mode": "choice", "scope": "weak", "count": 10}})
    elif streak.get("current", 0) >= 3:
        title = f"{streak.get('current')}日連続、継続が強いにゃ"
        message = "正答率よりもまず継続が勝ちです。今日も10問だけやれば、語彙の土台がちゃんと積み上がります。"
        tone = "streak"
        actions.append({"label": "今日の10問", "endpoint": "session_start", "params": {"mode": "choice", "scope": "all", "count": 10}})
    else:
        title = "今日は軽く積み上げるにゃ"
        message = "新しい単語を10問だけ解いて、間違えた単語をあとで復習する流れがおすすめです。小さく続けるのが一番強いです。"
        tone = "normal"
        actions.append({"label": "10問解く", "endpoint": "session_start", "params": {"mode": "choice", "scope": "all", "count": 10}})

    # サブ提案は最大2つ
    if review_stats.get("repeat_wrong", 0):
        actions.append({"label": "繰り返しミスを見る", "endpoint": "review", "params": {}})
    elif game.get("level", 1) < 10:
        actions.append({"label": "Lvを上げる", "endpoint": "session_start", "params": {"mode": "choice", "scope": "all", "count": 10}})

    return {
        "title": title,
        "message": message,
        "tone": tone,
        "actions": actions[:2],
        "weak_category": weak_category,
        "weak_pos": weak_pos,
        "due_review": due_review,
    }


def build_session_coach(data: dict, accuracy: float) -> dict:
    total = int(data.get("total", 0) or 0)
    correct = int(data.get("correct", 0) or 0)
    best_streak = int(data.get("best_streak", 0) or 0)

    wrong_answers = [a for a in data.get("answers", []) if not a.get("is_correct")]
    wrong_count = len(wrong_answers)
    wrong_preview = [a.get("english") for a in wrong_answers[:3] if a.get("english")]

    if data.get("scope") == "smart":
        if accuracy >= 80:
            title = "スマート学習、かなり効いてるにゃ"
            message = "おすすめ10問で高得点です。復習・弱点・新規がバランスよく回収できています。明日もこのボタンだけ押せばOKです。"
            tone = "good"
        elif accuracy >= 60:
            title = "今日のおすすめ単語は当たりだにゃ"
            message = "スマート学習でミスが出た単語は、次回さらに優先されます。つまり今日のミスは明日の伸びしろです。"
            tone = "review"
        else:
            title = "弱点発見に成功したにゃ"
            message = "おすすめ10問で苦戦した単語は、復習優先に回ります。次回はこの範囲を重点的に出します。"
            tone = "weak"
    elif accuracy == 100:
        title = "完璧にゃ。今日は勝ち切ったにゃ"
        message = "10問満点です。明日は新しい単語を混ぜるか、苦手カテゴリに挑戦するとさらに伸びます。"
        tone = "perfect"
    elif accuracy >= 80:
        title = "かなり良い完走だにゃ"
        message = f"{correct}/{total} 正解。あと少しで満点です。間違えた単語だけ今のうちに見直すと、次で取り返せます。"
        tone = "good"
    elif accuracy >= 60:
        title = "ここから回収できるにゃ"
        message = f"{correct}/{total} 正解。今日は覚える単語と怪しい単語が分かれた回です。ミスした単語を3語だけ復習しましょう。"
        tone = "review"
    else:
        title = "今日は伸びしろ発見回だにゃ"
        message = f"{correct}/{total} 正解。落ち込む回ではなく、復習対象を見つけた回です。次は苦手単語モードで軽く回収しましょう。"
        tone = "weak"

    if best_streak >= 5:
        message += f" ちなみに最高 {best_streak} 問連続正解、これはかなり良い流れです。"
    elif wrong_preview:
        message += " 要注意単語: " + " / ".join(wrong_preview)

    return {
        "title": title,
        "message": message,
        "tone": tone,
        "wrong_count": wrong_count,
        "wrong_preview": wrong_preview,
    }



@app.context_processor
def inject_current_user():
    user = get_current_user()
    return {
        "current_user": user,
        "is_master": is_master_user(user),
        "cat_types": CAT_TYPES,
        "cat_image": cat_image,
        "cat_type_label": cat_type_label,
        "part_of_speech_label": part_of_speech_label,
        "part_of_speech_labels": PART_OF_SPEECH_LABELS,
        "feature_enabled": feature_enabled,
        "feature_modules": FEATURE_MODULES,
        "enabled_feature_modules": enabled_feature_modules(),
        "feature_href": feature_href,
    }


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


def allowed_icon(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_ICON_EXTENSIONS


def save_uploaded_icon(file_storage, user_id: int) -> str:
    if not file_storage or not file_storage.filename:
        return ""
    if not allowed_icon(file_storage.filename):
        return ""
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    icon_name = f"user_{user_id}_{int(time.time())}.{ext}"
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    file_storage.save(ICON_DIR / icon_name)
    return f"uploads/icons/{icon_name}"



def share_mode_label(mode: str) -> str:
    mode_map = {
        "choice": "4択クイズ",
        "input": "入力式クイズ",
        "listen": "リスニング",
    }
    return mode_map.get(mode, mode)


def share_scope_label(scope: str) -> str:
    scope_map = {
        "all": "全単語",
        "weak": "苦手単語",
        "favorite": "お気に入り",
        "today_wrong": "今日ミスった単語",
        "repeat_wrong": "何度もミスる単語",
        "stale": "1週間触ってない単語",
    }
    if scope.startswith("category:"):
        return scope.split(":", 1)[1]
    return scope_map.get(scope, scope)


def share_score_comment(accuracy: float, correct: int, total: int) -> str:
    if total == 0:
        return "今日はまだ助走。ここから始める。"
    if accuracy == 100:
        return "満点。これはもう英語、勝ちです。"
    if accuracy >= 90:
        return "かなり仕上がってきた。あと少しで無双。"
    if accuracy >= 80:
        return "いい感じに英語筋が育ってる。"
    if accuracy >= 60:
        return "ミスもあるけど、ちゃんと前に進んでる。"
    return "伸びしろ多め。むしろここからが一番おいしい。"


def share_streak_line(total_answers: int) -> str:
    if total_answers >= 100:
        return "今日だけで100問超え。さすがに脳が英語モード。"
    if total_answers >= 50:
        return "50問以上やった。これは普通にえらい。"
    if total_answers >= 20:
        return "20問以上積んだ。小さく見えてかなり効くやつ。"
    if total_answers >= 10:
        return "10問だけでも、昨日より前に進んだ。"
    if total_answers > 0:
        return "少しでもやった時点で勝ち。"
    return "今日はまだ未回答。夜に1問だけでも回収したい。"


def create_share_text(test_session: sqlite3.Row, user: sqlite3.Row | None = None) -> str:
    display = user["display_name"] if user else "ユーザー"
    mode = share_mode_label(test_session["mode"])
    scope = share_scope_label(test_session["scope"])
    correct = test_session["correct_count"]
    total = test_session["total_count"]
    accuracy = test_session["accuracy"]
    comment = share_score_comment(accuracy, correct, total)

    return "\n".join([
        "🔥 English Pocket 今日の英語ログ",
        "",
        f"{display} は {mode}（{scope}）で",
        f"{correct}/{total} 正解・正答率 {accuracy}%",
        "",
        comment,
        "TOEIC950語彙、地味に強敵。でも潰していく。",
        "",
        "#英語学習 #TOEIC #今日の積み上げ #EnglishPocket",
    ])


def xml_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def wrap_svg_text(text: str, width: int = 22, max_lines: int = 5) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    raw_lines = text.splitlines()
    lines: list[str] = []

    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        # スペースの有無に応じて、単語単位 or 文字単位で折り返します。
        if " " in raw:
            current = ""
            for word in raw.split():
                candidate = (current + " " + word).strip()
                if len(candidate) <= width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    if len(word) <= width:
                        current = word
                    else:
                        for i in range(0, len(word), width):
                            lines.append(word[i:i+width])
                        current = ""
            if current:
                lines.append(current)
        else:
            for i in range(0, len(raw), width):
                lines.append(raw[i:i+width])

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines[-1]:
            lines[-1] = lines[-1][: max(0, width - 1)] + "…"
        else:
            lines[-1] = "…"
    return lines


def build_share_svg(
    *,
    eyebrow: str,
    title: str,
    subtitle: str,
    main_score: str,
    score_label: str,
    comment: str,
    detail_lines: list[str],
    footer_lines: list[str],
    accent: str = "#ff8fbd",
) -> str:
    width = 1080
    height = 1350

    title_lines = wrap_svg_text(title, width=18, max_lines=2)
    subtitle_lines = wrap_svg_text(subtitle, width=28, max_lines=2)
    comment_lines = wrap_svg_text(comment, width=25, max_lines=4)

    detail_lines_clean = []
    for line in detail_lines:
        detail_lines_clean.extend(wrap_svg_text(line, width=34, max_lines=2) or [""])
    detail_lines_clean = detail_lines_clean[:6]

    footer_lines_clean = []
    for line in footer_lines:
        footer_lines_clean.extend(wrap_svg_text(line, width=40, max_lines=2) or [""])
    footer_lines_clean = footer_lines_clean[:4]

    def render_lines(lines: list[str], x: int, start_y: int, line_height: int, size: int, color: str, weight: str = "500"):
        buf = []
        y = start_y
        for line in lines:
            buf.append(
                f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}">{xml_escape(line)}</text>'
            )
            y += line_height
        return "\n".join(buf), y

    title_svg, next_y = render_lines(title_lines, 110, 235, 54, 42, "#5c2740", "700")
    subtitle_svg, _ = render_lines(subtitle_lines, 110, next_y + 8, 34, 24, "#8d5e74", "500")
    comment_svg, _ = render_lines(comment_lines, 110, 720, 42, 30, "#5c2740", "600")
    detail_svg, _ = render_lines(detail_lines_clean, 120, 930, 36, 24, "#70465a", "500")
    footer_svg, _ = render_lines(footer_lines_clean, 110, 1190, 32, 22, "#8f6a7d", "500")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#fff9fc" />
            <stop offset="55%" stop-color="#fff1f7" />
            <stop offset="100%" stop-color="#f7ecff" />
        </linearGradient>
        <linearGradient id="accentGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="{xml_escape(accent)}" />
            <stop offset="100%" stop-color="#ffb8d2" />
        </linearGradient>
        <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="20" stdDeviation="28" flood-color="#f0aec9" flood-opacity="0.22"/>
        </filter>
    </defs>

    <rect width="{width}" height="{height}" fill="url(#bg)"/>
    <circle cx="950" cy="120" r="130" fill="#ffd7e8" opacity="0.42"/>
    <circle cx="140" cy="1220" r="160" fill="#ffe7f1" opacity="0.65"/>
    <circle cx="910" cy="1110" r="90" fill="#f4dfff" opacity="0.55"/>

    <rect x="60" y="60" rx="48" ry="48" width="960" height="1230" fill="#ffffff" filter="url(#softShadow)"/>
    <rect x="60" y="60" rx="48" ry="48" width="960" height="1230" fill="none" stroke="#ffd4e5" stroke-width="2"/>

    <rect x="110" y="120" rx="22" ry="22" width="250" height="54" fill="url(#accentGrad)"/>
    <text x="140" y="156" font-size="24" font-weight="700" fill="#ffffff">{xml_escape(eyebrow)}</text>

    <circle cx="905" cy="175" r="66" fill="#fff1f7" stroke="#ffd4e5" stroke-width="3"/>
    <text x="905" y="190" text-anchor="middle" font-size="52">🐱</text>

    {title_svg}
    {subtitle_svg}

    <rect x="110" y="365" rx="36" ry="36" width="860" height="235" fill="url(#accentGrad)"/>
    <text x="540" y="470" text-anchor="middle" font-size="88" font-weight="800" fill="#ffffff">{xml_escape(main_score)}</text>
    <text x="540" y="535" text-anchor="middle" font-size="28" font-weight="600" fill="#fff7fb">{xml_escape(score_label)}</text>

    <rect x="110" y="645" rx="28" ry="28" width="860" height="180" fill="#fff6fa" stroke="#ffd8ea" stroke-width="2"/>
    <text x="110" y="600" font-size="22" font-weight="700" fill="#c85e8a">Coach comment</text>
    {comment_svg}

    <rect x="110" y="875" rx="28" ry="28" width="860" height="235" fill="#fffdfd" stroke="#f1dbe6" stroke-width="2"/>
    <text x="110" y="845" font-size="22" font-weight="700" fill="#c85e8a">Summary</text>
    {detail_svg}

    <line x1="110" y1="1160" x2="970" y2="1160" stroke="#f0d8e4" stroke-width="2"/>
    {footer_svg}

    <text x="110" y="1270" font-size="22" font-weight="700" fill="#ff8fbd">にゃんにゃんイングリッシュ</text>
    <text x="970" y="1270" text-anchor="end" font-size="20" font-weight="600" fill="#9c7b8b">Made for sharing</text>
</svg>'''
    return svg


def build_today_share_svg(user: sqlite3.Row, summary: dict, stats: dict, total_answers: int, total_correct: int, accuracy: float) -> str:
    comment = share_score_comment(accuracy, total_correct, total_answers)
    streak = stats["gamification"]["streak"]["current"]
    level = stats["gamification"]["game"]["level"]
    title_name = user["display_name"]

    detail_lines = [
        f"今日の回答数: {total_answers}問",
        f"正解数: {total_correct}問 / 正答率 {accuracy}%",
        f"学習レベル: Lv.{level}",
        f"{streak}日連続学習中",
    ]

    if summary.get("logs"):
        for row in summary["logs"][:2]:
            row_total = row["total_count"]
            row_correct = row["correct_count"] or 0
            row_accuracy = round((row_correct / row_total) * 100, 1) if row_total else 0
            detail_lines.append(f"{share_mode_label(row['mode'])}: {row_correct}/{row_total} ({row_accuracy}%)")

    footer_lines = [
        "TOEIC高難度単語をコツコツ学習中。",
        "#英語学習 #TOEIC #今日の積み上げ",
    ]

    return build_share_svg(
        eyebrow="Today Share",
        title=f"{title_name} の今日の英語ログ",
        subtitle=datetime.now().strftime("%Y-%m-%d"),
        main_score=f"{total_correct}/{total_answers}",
        score_label=f"正解数 / 正答率 {accuracy}%",
        comment=comment,
        detail_lines=detail_lines,
        footer_lines=footer_lines,
    )


def build_session_share_svg(user: sqlite3.Row, test_session: sqlite3.Row) -> str:
    mode = share_mode_label(test_session["mode"])
    scope = share_scope_label(test_session["scope"])
    correct = test_session["correct_count"]
    total = test_session["total_count"]
    accuracy = test_session["accuracy"]
    comment = share_score_comment(accuracy, correct, total)

    detail_lines = [
        f"テスト種別: {mode}",
        f"出題範囲: {scope}",
        f"スコア: {correct}/{total}",
        f"正答率: {accuracy}%",
        f"挑戦者: {user['display_name']}",
        f"実施日: {(test_session['created_at'] or '')[:10]}",
    ]

    footer_lines = [
        "結果を画像化してそのまま共有できます。",
        "#にゃんにゃんイングリッシュ #TOEIC #英語学習",
    ]

    return build_share_svg(
        eyebrow="Session Result",
        title=f"{user['display_name']} のテスト結果",
        subtitle=f"{mode} / {scope}",
        main_score=f"{correct}/{total}",
        score_label=f"正答率 {accuracy}%",
        comment=comment,
        detail_lines=detail_lines,
        footer_lines=footer_lines,
    )


def create_test_session(user_id: int, mode: str, scope: str, total: int, correct: int) -> int:
    accuracy = round((correct / total) * 100, 1) if total else 0
    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO test_sessions (user_id, mode, scope, total_count, correct_count, accuracy, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, mode, scope, total, correct, accuracy, now_text()),
    )
    test_session_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM test_sessions WHERE id = ?", (test_session_id,)).fetchone()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    share_text = create_share_text(row, user)
    conn.execute("UPDATE test_sessions SET share_text = ? WHERE id = ?", (share_text, test_session_id))
    conn.commit()
    conn.close()
    return test_session_id



def word_select_sql() -> str:
    return """
        SELECT
            w.id,
            w.english,
            w.japanese,
            w.example,
            w.memo,
            w.audio_text,
            w.audio_file,
            w.example_audio_file,
            w.category,
            w.part_of_speech,
            w.level,
            COALESCE(f.favorite, 0) AS favorite,
            w.favorite AS global_favorite,
            w.created_by_user_id,
            w.created_at,
            w.updated_at,
            u.display_name AS created_by_name,
            u.username AS created_by_username,
            u.icon_file AS created_by_icon
        FROM words w
        LEFT JOIN users u ON u.id = w.created_by_user_id
        LEFT JOIN user_word_flags f
            ON f.word_id = w.id
           AND f.user_id = ?
    """


def require_user_id() -> int:
    uid = current_user_id()
    if uid is None:
        raise RuntimeError("login required")
    return uid


def fetch_word(word_id: int) -> sqlite3.Row | None:
    conn = get_db_connection()
    uid = current_user_id() or 0
    word = conn.execute(
        word_select_sql() + " WHERE w.id = ?",
        (uid, word_id),
    ).fetchone()
    conn.close()
    return word


def fetch_words(q: str = "", category: str = "", favorite_only: bool = False) -> list[sqlite3.Row]:
    where = []
    params: list[object] = []
    uid = current_user_id() or 0

    if q:
        where.append("(lower(w.english) LIKE ? OR lower(w.japanese) LIKE ? OR lower(w.example) LIKE ? OR lower(w.memo) LIKE ? OR lower(w.audio_text) LIKE ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like, like, like, like])

    if category:
        where.append("w.category = ?")
        params.append(category)

    if favorite_only:
        where.append("COALESCE(f.favorite, 0) = 1")

    sql = word_select_sql()
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(f.favorite, 0) DESC, w.id DESC"

    conn = get_db_connection()
    words = conn.execute(sql, [uid] + params).fetchall()
    conn.close()
    return words


def fetch_all_words() -> list[sqlite3.Row]:
    return fetch_words()


def get_categories() -> list[str]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT category FROM words WHERE category IS NOT NULL AND category != '' ORDER BY category"
    ).fetchall()
    conn.close()
    return [row["category"] for row in rows]


def get_candidate_ids(scope: str = "all") -> list[int]:
    if scope == "smart":
        return get_smart_candidate_ids(current_user_id())

    conn = get_db_connection()

    if scope == "weak":
        uid = current_user_id()
        if uid is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT w.id
                FROM words w
                JOIN study_logs l ON w.id = l.word_id
                WHERE l.user_id = ?
                GROUP BY w.id
                HAVING SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) > 0
                """,
                (uid,),
            ).fetchall()

    elif scope == "today_wrong":
        uid = current_user_id()
        if uid is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT w.id
                FROM words w
                JOIN study_logs l ON w.id = l.word_id
                WHERE l.user_id = ?
                  AND l.is_correct = 0
                  AND date(l.created_at, 'localtime') = date('now', 'localtime')
                """,
                (uid,),
            ).fetchall()

    elif scope == "repeat_wrong":
        uid = current_user_id()
        if uid is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT w.id
                FROM words w
                JOIN study_logs l ON w.id = l.word_id
                WHERE l.user_id = ?
                GROUP BY w.id
                HAVING SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) >= 2
                ORDER BY SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) DESC
                """,
                (uid,),
            ).fetchall()

    elif scope == "stale":
        uid = current_user_id()
        if uid is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT w.id
                FROM words w
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM study_logs l
                    WHERE l.user_id = ?
                      AND l.word_id = w.id
                      AND datetime(l.created_at) >= datetime('now', '-7 days', 'localtime')
                )
                """,
                (uid,),
            ).fetchall()

    elif scope == "favorite":
        uid = current_user_id()
        if uid is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT w.id
                FROM words w
                JOIN user_word_flags f ON f.word_id = w.id
                WHERE f.user_id = ? AND f.favorite = 1
                """,
                (uid,),
            ).fetchall()

    elif scope.startswith("category:"):
        category = scope.split(":", 1)[1]
        rows = conn.execute(
            "SELECT id FROM words WHERE COALESCE(NULLIF(category, ''), '未分類') = ?",
            (category,),
        ).fetchall()

    else:
        rows = conn.execute("SELECT id FROM words").fetchall()

    conn.close()
    return [row["id"] for row in rows]


def get_random_word(scope: str = "all") -> sqlite3.Row | None:
    ids = get_candidate_ids(scope)

    if not ids and scope != "all":
        ids = get_candidate_ids("all")

    if not ids:
        return None

    return fetch_word(random.choice(ids))



PART_OF_SPEECH_LABELS = {
    "noun": "名詞",
    "verb": "動詞",
    "adjective": "形容詞",
    "adverb": "副詞",
    "other": "その他",
}


def normalize_part_of_speech(value: str | None) -> str:
    text = (value or "").strip().lower()

    mapping = {
        "noun": "noun",
        "n": "noun",
        "名詞": "noun",
        "verb": "verb",
        "v": "verb",
        "動詞": "verb",
        "adjective": "adjective",
        "adj": "adjective",
        "形容詞": "adjective",
        "形容動詞": "adjective",
        "adverb": "adverb",
        "adv": "adverb",
        "副詞": "adverb",
        "other": "other",
        "その他": "other",
    }

    return mapping.get(text, text if text in PART_OF_SPEECH_LABELS else "")


def infer_part_of_speech(english: str = "", japanese: str = "", category: str = "") -> str:
    """
    既存CSVに品詞列がない場合の自動推定です。
    4択の難易度調整が目的なので、完璧な文法判定よりも
    「日本語の見た目で答えがバレない」ことを優先しています。
    """
    jp = (japanese or "").strip()
    en = (english or "").strip().lower()
    cat = (category or "").strip().lower()

    # 複数訳は先頭を主な訳として見る
    primary = re.split(r"[,、/／;；]", jp)[0].strip()

    # 副詞: 「〜に」「〜く」や英語の -ly を優先
    if en.endswith("ly") or primary.endswith("に") or primary.endswith("的に") or primary.endswith("く"):
        return "adverb"

    # 動詞: 日本語訳で「〜する」「〜させる」「〜になる」など
    verb_endings = (
        "する", "させる", "される", "できる", "なる", "得る", "える", "める", "ける",
        "す", "つ", "く", "ぐ", "む", "ぶ", "ぬ", "る"
    )
    if any(primary.endswith(end) for end in verb_endings):
        # 「大きく」「詳しく」のような副詞を動詞扱いしない
        if not primary.endswith(("く", "に")):
            return "verb"

    # 形容詞: 日本語訳で「〜な」「〜の」「〜的な」「〜可能な」など
    adjective_endings = (
        "な", "の", "的な", "可能な", "できる", "らしい", "やすい", "にくい",
        "高い", "低い", "多い", "少ない", "良い", "悪い", "大きい", "小さい",
        "新しい", "古い", "早い", "遅い", "強い", "弱い", "正確な", "重要な"
    )
    if any(primary.endswith(end) for end in adjective_endings):
        return "adjective"

    # 英語側のざっくり判定
    adjective_suffixes = (
        "able", "ible", "al", "ive", "ous", "ful", "less", "ic", "ical",
        "ary", "ory", "ent", "ant", "ate", "y"
    )
    noun_suffixes = (
        "tion", "sion", "ment", "ness", "ity", "ance", "ence", "ship",
        "ism", "ist", "er", "or", "ee", "cy", "age", "ure", "hood", "dom"
    )

    if en.endswith(adjective_suffixes):
        return "adjective"
    if en.endswith(noun_suffixes):
        return "noun"

    if "verbs" in cat or "verb" in cat:
        return "verb"
    if "adjectives" in cat or "adjective" in cat:
        return "adjective"
    if "modifiers" in cat or "adverb" in cat:
        return "adverb"
    if "nouns" in cat or "noun" in cat:
        return "noun"

    return "noun"


def part_of_speech_label(value: str | None) -> str:
    return PART_OF_SPEECH_LABELS.get(normalize_part_of_speech(value), "未分類")


def backfill_part_of_speech(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, english, japanese, category, part_of_speech
        FROM words
        WHERE part_of_speech IS NULL OR part_of_speech = ''
        """
    ).fetchall()

    for row in rows:
        inferred = infer_part_of_speech(row["english"], row["japanese"], row["category"])
        conn.execute(
            "UPDATE words SET part_of_speech = ?, updated_at = ? WHERE id = ?",
            (inferred, now_text(), row["id"]),
        )


def get_choices(correct_word: sqlite3.Row, limit: int = 4) -> list[str]:
    """
    4択のダミー選択肢は、正解単語と同じ品詞から優先して選びます。
    これにより「日本語訳が〜するだから動詞だな」のような品詞バレを防ぎます。
    """
    correct_pos = normalize_part_of_speech(correct_word["part_of_speech"])
    if not correct_pos:
        correct_pos = infer_part_of_speech(
            correct_word["english"],
            correct_word["japanese"],
            correct_word["category"],
        )

    conn = get_db_connection()

    wrong_words = conn.execute(
        """
        SELECT japanese
        FROM words
        WHERE id != ?
          AND part_of_speech = ?
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (correct_word["id"], correct_pos, limit - 1),
    ).fetchall()

    # 同じ品詞が足りない場合だけ、ランダムで補完
    if len(wrong_words) < limit - 1:
        already = [correct_word["japanese"]] + [row["japanese"] for row in wrong_words]
        placeholders = ",".join(["?"] * len(already))
        extra_limit = (limit - 1) - len(wrong_words)
        extra_words = conn.execute(
            f"""
            SELECT japanese
            FROM words
            WHERE id != ?
              AND japanese NOT IN ({placeholders})
            ORDER BY RANDOM()
            LIMIT ?
            """,
            [correct_word["id"]] + already + [extra_limit],
        ).fetchall()
        wrong_words = list(wrong_words) + list(extra_words)

    conn.close()

    choices = [correct_word["japanese"]] + [row["japanese"] for row in wrong_words]
    random.shuffle(choices)
    return choices



def get_recent_correct_streak(user_id: int | None, limit: int = 50) -> int:
    if user_id is None:
        return 0

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT is_correct
        FROM study_logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    conn.close()

    streak = 0
    for row in rows:
        if row["is_correct"]:
            streak += 1
        else:
            break
    return streak


def get_cat_reaction(is_correct: bool, streak: int = 0, finished: bool = False, accuracy: float | None = None) -> dict:
    """
    猫のリアクションを1か所で管理します。
    テンプレート側は title/message/effect/cat_state/badge を表示するだけです。
    """
    if finished:
        score = accuracy or 0
        if score == 100:
            return {
                "title": "満点にゃ！天才すぎる！",
                "message": "10問全部正解。猫、完全にお祭りモードです。今日は語彙の神かもしれない。",
                "effect": "festival",
                "cat_state": "finish_good",
                "badge": "🎉 PERFECT",
            }
        if score >= 80:
            return {
                "title": "ナイス完走にゃ！",
                "message": "かなり良いペース。猫も肉球で拍手しています。もう一周したらさらに固まりそう。",
                "effect": "confetti",
                "cat_state": "finish_good",
                "badge": "👏 GREAT",
            }
        if score >= 60:
            return {
                "title": "いい感じにゃ。",
                "message": "合格ライン。焦らず復習すればちゃんと伸びます。猫も横で見守っています。",
                "effect": "soft",
                "cat_state": "finish_ok",
                "badge": "🐾 GOOD",
            }
        return {
            "title": "伸びしろ回にゃ。",
            "message": "今日は回収日。間違えた単語だけ復習すると、次はかなり取り返せます。",
            "effect": "none",
            "cat_state": "finish_low",
            "badge": "🌱 REVIEW",
        }

    if is_correct:
        if streak >= 10:
            return {
                "title": f"{streak}問連続正解！猫、祭りです。",
                "message": "ここまで来たら完全にゾーン。語彙力がもふもふ伸びています。",
                "effect": "festival",
                "cat_state": "correct",
                "badge": "🔥 STREAK",
            }
        if streak >= 5:
            return {
                "title": f"{streak}問連続正解にゃ！",
                "message": "かなり乗ってます。猫も前のめりで応援中。",
                "effect": "confetti",
                "cat_state": "correct",
                "badge": "✨ COMBO",
            }
        if streak >= 3:
            return {
                "title": "3問連続正解！肉球拍手にゃ。",
                "message": "いいリズム。ここから連勝を伸ばしていこう。",
                "effect": "clap",
                "cat_state": "correct",
                "badge": "👏 NICE",
            }
        return {
            "title": "やった、正解にゃ。",
            "message": "この調子で語彙力をもふもふ育てよう。",
            "effect": "sparkle",
            "cat_state": "correct",
            "badge": "🐾 OK",
        }

    return {
        "title": "惜しいにゃ…。",
        "message": "でもミスった単語は伸びしろ。次で回収しよう。",
        "effect": "sad",
        "cat_state": "wrong",
        "badge": "💧 REVIEW",
    }


def get_home_cat_message(stats: dict) -> dict:
    streak = stats.get("gamification", {}).get("streak", {}).get("current", 0)
    total_logs = stats.get("total_logs", 0)

    if streak >= 7:
        return {
            "title": f"{streak}日連続で来てるにゃ。",
            "message": "これはもう習慣化の勝ち。猫も玄関で待ってます。",
            "effect": "sparkle",
        }
    if streak >= 3:
        return {
            "title": f"{streak}日連続学習中にゃ。",
            "message": "良い流れ。今日も10問だけやればかなり強いです。",
            "effect": "soft",
        }
    if total_logs > 0:
        return {
            "title": "今日も来たにゃ。",
            "message": "まずは1問でも勝ち。続けた人から語彙が増えます。",
            "effect": "none",
        }
    return {
        "title": "最初の一問、いくにゃ？",
        "message": "猫が横で見ています。まずは軽く10問から。",
        "effect": "none",
    }


def record_answer(word_id: int, mode: str, user_answer: str, test_session_id: int | None = None) -> tuple[sqlite3.Row | None, bool]:
    word = fetch_word(word_id)
    if word is None:
        return None, False

    correct = is_answer_correct(user_answer, word["japanese"])
    uid = current_user_id()

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO study_logs (
            user_id,
            test_session_id,
            word_id,
            mode,
            user_answer,
            correct_answer,
            is_correct,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            test_session_id,
            word_id,
            mode,
            user_answer,
            word["japanese"],
            1 if correct else 0,
            now_text(),
        ),
    )
    conn.commit()
    conn.close()

    return word, correct



def get_user_learning_dates(user_id: int) -> list[str]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT DISTINCT date(created_at, 'localtime') AS learned_date
        FROM study_logs
        WHERE user_id = ?
        ORDER BY learned_date DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return [row["learned_date"] for row in rows if row["learned_date"]]


def calculate_streak(user_id: int) -> dict:
    dates = get_user_learning_dates(user_id)
    if not dates:
        return {
            "current": 0,
            "longest": 0,
            "last_date": None,
            "today_done": False,
        }

    from datetime import date, timedelta

    date_set = {datetime.strptime(d, "%Y-%m-%d").date() for d in dates}
    today = date.today()
    today_done = today in date_set

    # 今日やっていない場合でも、昨日まで続いていれば current として見せる。
    cursor = today if today_done else today - timedelta(days=1)
    current = 0
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    for d in sorted(date_set):
        c = d
        count = 0
        while c in date_set:
            count += 1
            c += timedelta(days=1)
        longest = max(longest, count)

    return {
        "current": current,
        "longest": longest,
        "last_date": max(date_set).isoformat(),
        "today_done": today_done,
    }


def calculate_exp_and_level(user_id: int) -> dict:
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_answers,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_answers,
            SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS wrong_answers
        FROM study_logs
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    perfect_sessions = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM test_sessions
        WHERE user_id = ?
          AND total_count > 0
          AND correct_count = total_count
        """,
        (user_id,),
    ).fetchone()["count"]

    conn.close()

    total_answers = row["total_answers"] or 0
    correct_answers = row["correct_answers"] or 0
    wrong_answers = row["wrong_answers"] or 0

    exp = correct_answers * 10 + wrong_answers * 3 + perfect_sessions * 50

    # ほどよく上がるレベル式。Lv1から開始。
    level = max(1, int((exp / 120) ** 0.65) + 1)
    current_level_base = int(((level - 1) ** (1 / 0.65)) * 120) if level > 1 else 0
    next_level_exp = int((level ** (1 / 0.65)) * 120)
    progress = exp - current_level_base
    need = max(1, next_level_exp - current_level_base)
    progress_pct = round(min(100, max(0, progress / need * 100)), 1)

    title = "英語ビギナー"
    if level >= 30:
        title = "TOEIC語彙モンスター"
    elif level >= 20:
        title = "語彙ハンター"
    elif level >= 10:
        title = "英語筋トレ民"
    elif level >= 5:
        title = "積み上げ勢"

    return {
        "exp": exp,
        "level": level,
        "title": title,
        "next_level_exp": next_level_exp,
        "progress": progress,
        "need": need,
        "progress_pct": progress_pct,
        "perfect_sessions": perfect_sessions,
    }


def get_badges(user_id: int) -> list[dict]:
    conn = get_db_connection()

    total_answers = conn.execute(
        "SELECT COUNT(*) AS count FROM study_logs WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]

    correct_answers = conn.execute(
        "SELECT COUNT(*) AS count FROM study_logs WHERE user_id = ? AND is_correct = 1",
        (user_id,),
    ).fetchone()["count"]

    perfect_sessions = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM test_sessions
        WHERE user_id = ? AND total_count > 0 AND correct_count = total_count
        """,
        (user_id,),
    ).fetchone()["count"]

    listening_answers = conn.execute(
        "SELECT COUNT(*) AS count FROM study_logs WHERE user_id = ? AND mode = 'listen'",
        (user_id,),
    ).fetchone()["count"]

    distinct_words = conn.execute(
        "SELECT COUNT(DISTINCT word_id) AS count FROM study_logs WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]

    added_words = conn.execute(
        "SELECT COUNT(*) AS count FROM words WHERE created_by_user_id = ?",
        (user_id,),
    ).fetchone()["count"]

    conn.close()

    streak = calculate_streak(user_id)
    game = calculate_exp_and_level(user_id)

    badge_defs = [
        ("はじめの一歩", "初めて回答した", "🌱", total_answers >= 1),
        ("10問突破", "10問以上回答した", "🔟", total_answers >= 10),
        ("100問回答", "100問以上回答した", "💯", total_answers >= 100),
        ("500問回答", "500問以上回答した", "🔥", total_answers >= 500),
        ("満点ハンター", "10問テストで満点を取った", "🏆", perfect_sessions >= 1),
        ("満点コレクター", "満点を5回取った", "👑", perfect_sessions >= 5),
        ("継続の鬼", "7日連続で学習した", "🗓️", streak["current"] >= 7),
        ("耳が育ってきた", "リスニングを50問やった", "🎧", listening_answers >= 50),
        ("語彙モンスター", "100語以上に触れた", "🧠", distinct_words >= 100),
        ("単語職人", "自分で単語を20個追加した", "🛠️", added_words >= 20),
        ("Lv.10到達", "レベル10に到達した", "⚡", game["level"] >= 10),
        ("Lv.20到達", "レベル20に到達した", "🚀", game["level"] >= 20),
    ]

    return [
        {
            "name": name,
            "description": description,
            "icon": icon,
            "unlocked": unlocked,
        }
        for name, description, icon, unlocked in badge_defs
    ]


def get_recent_badges(user_id: int, limit: int = 3) -> list[dict]:
    unlocked = [b for b in get_badges(user_id) if b["unlocked"]]
    return unlocked[-limit:]


def get_gamification_summary(user_id: int) -> dict:
    return {
        "streak": calculate_streak(user_id),
        "game": calculate_exp_and_level(user_id),
        "badges": get_badges(user_id),
        "recent_badges": get_recent_badges(user_id),
    }


def get_review_stats(user_id: int) -> dict:
    conn = get_db_connection()

    today_wrong = conn.execute(
        """
        SELECT COUNT(DISTINCT word_id) AS count
        FROM study_logs
        WHERE user_id = ?
          AND is_correct = 0
          AND date(created_at, 'localtime') = date('now', 'localtime')
        """,
        (user_id,),
    ).fetchone()["count"]

    repeat_wrong = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT word_id
            FROM study_logs
            WHERE user_id = ?
            GROUP BY word_id
            HAVING SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) >= 2
        )
        """,
        (user_id,),
    ).fetchone()["count"]

    stale = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM words w
        WHERE NOT EXISTS (
            SELECT 1
            FROM study_logs l
            WHERE l.user_id = ?
              AND l.word_id = w.id
              AND datetime(l.created_at) >= datetime('now', '-7 days', 'localtime')
        )
        """,
        (user_id,),
    ).fetchone()["count"]

    conn.close()

    return {
        "today_wrong": today_wrong,
        "repeat_wrong": repeat_wrong,
        "stale": stale,
    }


def get_toeic_category_modes() -> list[dict]:
    preferred = [
        "Business / Management",
        "Finance / Accounting",
        "Legal / Compliance",
        "Procurement / Logistics",
        "Marketing / Sales",
        "HR / Workplace",
        "IT / Data",
        "Manufacturing / Quality",
        "Travel / Events",
        "Advanced Verbs",
        "Advanced Modifiers",
        "Abstract / Academic",
        "TOEIC Phrases",
    ]

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(category, ''), '未分類') AS category,
            COUNT(*) AS count
        FROM words
        GROUP BY COALESCE(NULLIF(category, ''), '未分類')
        HAVING count > 0
        """
    ).fetchall()
    conn.close()

    by_category = {row["category"]: row["count"] for row in rows}
    result = []

    for category in preferred:
        if category in by_category:
            result.append({"category": category, "count": by_category[category]})

    for category, count in sorted(by_category.items()):
        if category not in preferred:
            result.append({"category": category, "count": count})

    return result


def get_stats(user_id: int | None = None) -> dict:
    uid = user_id if user_id is not None else current_user_id()
    conn = get_db_connection()

    total_words = conn.execute("SELECT COUNT(*) AS count FROM words").fetchone()["count"]
    if uid is None:
        favorite_words = 0
    else:
        favorite_words = conn.execute(
            "SELECT COUNT(*) AS count FROM user_word_flags WHERE user_id = ? AND favorite = 1",
            (uid,),
        ).fetchone()["count"]

    if uid is None:
        total_logs = 0
        correct_logs = 0
        recent_logs = []
        weak_words = []
        recent_tests = []
    else:
        total_logs = conn.execute(
            "SELECT COUNT(*) AS count FROM study_logs WHERE user_id = ?", (uid,)
        ).fetchone()["count"]
        correct_logs = conn.execute(
            "SELECT COUNT(*) AS count FROM study_logs WHERE user_id = ? AND is_correct = 1", (uid,)
        ).fetchone()["count"]

        recent_logs = conn.execute(
            """
            SELECT
                l.*,
                w.english
            FROM study_logs l
            JOIN words w ON w.id = l.word_id
            WHERE l.user_id = ?
            ORDER BY l.id DESC
            LIMIT 10
            """,
            (uid,),
        ).fetchall()

        weak_words = conn.execute(
            """
            SELECT
                w.id,
                w.english,
                w.japanese,
                w.category,
                w.level,
                COALESCE(f.favorite, 0) AS favorite,
                COUNT(l.id) AS total_count,
                SUM(CASE WHEN l.is_correct = 0 THEN 1 ELSE 0 END) AS incorrect_count,
                ROUND(
                    100.0 * SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(l.id),
                    1
                ) AS accuracy
            FROM words w
            JOIN study_logs l ON w.id = l.word_id
            LEFT JOIN user_word_flags f ON f.word_id = w.id AND f.user_id = ?
            WHERE l.user_id = ?
            GROUP BY w.id
            HAVING incorrect_count > 0
            ORDER BY incorrect_count DESC, total_count DESC
            LIMIT 10
            """,
            (uid, uid),
        ).fetchall()

        recent_tests = conn.execute(
            """
            SELECT *
            FROM test_sessions
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (uid,),
        ).fetchall()

    category_stats = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(category, ''), '未分類') AS category,
            COUNT(*) AS count
        FROM words
        GROUP BY COALESCE(NULLIF(category, ''), '未分類')
        ORDER BY count DESC, category
        """
    ).fetchall()

    conn.close()

    accuracy = round((correct_logs / total_logs) * 100, 1) if total_logs else 0
    gamification = get_gamification_summary(uid) if uid is not None else {
        "streak": {"current": 0, "longest": 0, "last_date": None, "today_done": False},
        "game": {"exp": 0, "level": 1, "title": "英語ビギナー", "next_level_exp": 120, "progress": 0, "need": 120, "progress_pct": 0, "perfect_sessions": 0},
        "badges": [],
        "recent_badges": [],
    }
    review_stats = get_review_stats(uid) if uid is not None else {"today_wrong": 0, "repeat_wrong": 0, "stale": 0}

    return {
        "total_words": total_words,
        "favorite_words": favorite_words,
        "total_logs": total_logs,
        "correct_logs": correct_logs,
        "accuracy": accuracy,
        "recent_logs": recent_logs,
        "weak_words": weak_words,
        "recent_tests": recent_tests,
        "category_stats": category_stats,
        "gamification": gamification,
        "review_stats": review_stats,
    }


def get_rankings(period: str = "all") -> list[dict]:
    where = "l.user_id IS NOT NULL"
    params: list[object] = []

    if period == "today":
        where += " AND date(l.created_at, 'localtime') = date('now', 'localtime')"
    elif period == "week":
        where += " AND datetime(l.created_at) >= datetime('now', '-7 days', 'localtime')"

    conn = get_db_connection()
    rows = conn.execute(
        f"""
        SELECT
            u.id,
            u.username,
            u.display_name,
            u.icon_file,
            COUNT(l.id) AS total_answers,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_answers,
            ROUND(100.0 * SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(l.id), 1) AS accuracy
        FROM users u
        JOIN study_logs l ON u.id = l.user_id
        WHERE {where}
        GROUP BY u.id
        HAVING total_answers > 0
        ORDER BY correct_answers DESC, accuracy DESC, total_answers DESC
        LIMIT 50
        """,
        params,
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        game = calculate_exp_and_level(row["id"])
        streak = calculate_streak(row["id"])
        result.append({
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "icon_file": row["icon_file"],
            "total_answers": row["total_answers"],
            "correct_answers": row["correct_answers"] or 0,
            "accuracy": row["accuracy"] or 0,
            "level": game["level"],
            "title": game["title"],
            "exp": game["exp"],
            "streak": streak["current"],
        })
    return result


def get_daily_user_summary(user_id: int) -> dict:
    conn = get_db_connection()
    tests = conn.execute(
        """
        SELECT *
        FROM test_sessions
        WHERE user_id = ? AND date(created_at) = date('now', 'localtime')
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()
    logs = conn.execute(
        """
        SELECT
            mode,
            COUNT(*) AS total_count,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_count
        FROM study_logs
        WHERE user_id = ? AND date(created_at) = date('now', 'localtime')
        GROUP BY mode
        ORDER BY mode
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return {"tests": tests, "logs": logs}


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip() or username
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not username or not password:
            return render_template("register.html", error="ユーザー名とパスワードを入力してください。")
        if password != password_confirm:
            return render_template("register.html", error="パスワードが一致しません。")
        if len(password) < 4:
            return render_template("register.html", error="パスワードは4文字以上にしてください。")

        conn = get_db_connection()
        role = "master" if username.lower() == MASTER_USERNAME else "user"
        cat_type = request.form.get("cat_type", "milk").strip()
        if cat_type not in CAT_STATE_MAP:
            cat_type = "milk"
        exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            conn.close()
            return render_template("register.html", error="そのユーザー名は既に使われています。")

        cursor = conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, cat_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, display_name, generate_password_hash(password), role, cat_type, now_text(), now_text()),
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        icon_file = save_uploaded_icon(request.files.get("icon"), user_id)
        if icon_file:
            conn = get_db_connection()
            conn.execute("UPDATE users SET icon_file = ?, updated_at = ? WHERE id = ?", (icon_file, now_text(), user_id))
            conn.commit()
            conn.close()

        session["user_id"] = user_id
        return redirect(url_for("index"))

    return render_template("register.html", error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or url_for("index")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="ユーザー名またはパスワードが違います。", next_url=next_url)

        session["user_id"] = user["id"]
        return redirect(next_url)

    return render_template("login.html", error=None, next_url=request.args.get("next", ""))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip() or user["username"]
        new_password = request.form.get("new_password", "")
        cat_type = request.form.get("cat_type", "milk").strip()
        if cat_type not in CAT_STATE_MAP:
            cat_type = "milk"

        icon_file = save_uploaded_icon(request.files.get("icon"), user["id"])

        conn = get_db_connection()
        if new_password:
            conn.execute(
                "UPDATE users SET display_name = ?, cat_type = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                (display_name, cat_type, generate_password_hash(new_password), now_text(), user["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET display_name = ?, cat_type = ?, updated_at = ? WHERE id = ?",
                (display_name, cat_type, now_text(), user["id"]),
            )
        if icon_file:
            conn.execute("UPDATE users SET icon_file = ?, updated_at = ? WHERE id = ?", (icon_file, now_text(), user["id"]))
        conn.commit()
        conn.close()
        return redirect(url_for("profile"))

    stats = get_stats(user["id"])
    return render_template("profile.html", user=user, stats=stats)


@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/")
@login_required
def index():
    stats = get_stats()
    home_cat_message = get_home_cat_message(stats)
    coach = build_learning_coach(stats)
    return render_template("index.html", stats=stats, home_cat_message=home_cat_message, coach=coach)


@app.route("/words")
@login_required
def words():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    favorite = request.args.get("favorite") == "1"
    all_words = fetch_words(q=q, category=category, favorite_only=favorite)
    categories = get_categories()
    return render_template(
        "words.html",
        words=all_words,
        categories=categories,
        q=q,
        selected_category=category,
        favorite=favorite,
        added=request.args.get("added", ""),
        skipped=request.args.get("skipped", ""),
    )


def normalize_english_key(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def find_existing_word_by_english(conn: sqlite3.Connection, english: str, exclude_id: int | None = None) -> sqlite3.Row | None:
    normalized = normalize_english_key(english)
    if not normalized:
        return None

    if exclude_id is None:
        return conn.execute(
            "SELECT * FROM words WHERE lower(trim(english)) = ? LIMIT 1",
            (normalized,),
        ).fetchone()

    return conn.execute(
        "SELECT * FROM words WHERE lower(trim(english)) = ? AND id != ? LIMIT 1",
        (normalized, exclude_id),
    ).fetchone()


@app.route("/words/add", methods=["GET", "POST"])
@app.route("/add", methods=["GET", "POST"])
@login_required
def add_word():
    if request.method == "POST":
        english = request.form.get("english", "").strip()
        japanese = request.form.get("japanese", "").strip()
        example = request.form.get("example", "").strip()
        memo = request.form.get("memo", "").strip()
        audio_text = request.form.get("audio_text", "").strip()
        category = request.form.get("category", "").strip() or "未分類"
        part_of_speech = normalize_part_of_speech(request.form.get("part_of_speech", ""))
        if not part_of_speech:
            part_of_speech = infer_part_of_speech(english, japanese, category)
        level = int(request.form.get("level", "1"))
        favorite = 1 if request.form.get("favorite") == "on" else 0

        if english and japanese:
            conn = get_db_connection()
            existing = find_existing_word_by_english(conn, english)
            if existing:
                conn.close()
                return redirect(url_for("edit_word", word_id=existing["id"], duplicate="1"))

            conn.execute(
                """
                INSERT INTO words (english, japanese, example, memo, audio_text, category, part_of_speech, level, favorite, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (english, japanese, example, memo, audio_text, category, part_of_speech, level, favorite, current_user_id(), now_text(), now_text()),
            )
            conn.commit()
            conn.close()

        return redirect(url_for("words"))

    return render_template("word_form.html", mode="add", word=None, categories=get_categories())


@app.route("/words/<int:word_id>/edit", methods=["GET", "POST"])
@master_required
def edit_word(word_id: int):
    word = fetch_word(word_id)
    if word is None:
        return redirect(url_for("words"))

    if request.method == "POST":
        english = request.form.get("english", "").strip()
        japanese = request.form.get("japanese", "").strip()
        example = request.form.get("example", "").strip()
        memo = request.form.get("memo", "").strip()
        audio_text = request.form.get("audio_text", "").strip()
        category = request.form.get("category", "").strip() or "未分類"
        part_of_speech = normalize_part_of_speech(request.form.get("part_of_speech", ""))
        if not part_of_speech:
            part_of_speech = infer_part_of_speech(english, japanese, category)
        level = int(request.form.get("level", "1"))
        favorite = 1 if request.form.get("favorite") == "on" else 0

        if english and japanese:
            conn = get_db_connection()
            existing = find_existing_word_by_english(conn, english, exclude_id=word_id)
            if existing:
                conn.close()
                return redirect(url_for("edit_word", word_id=existing["id"], duplicate="1"))

            conn.execute(
                """
                UPDATE words
                SET english = ?, japanese = ?, example = ?, memo = ?, audio_text = ?, category = ?, part_of_speech = ?, level = ?, favorite = ?, updated_at = ?
                WHERE id = ?
                """,
                (english, japanese, example, memo, audio_text, category, part_of_speech, level, favorite, now_text(), word_id),
            )
            conn.commit()
            conn.close()

        return redirect(url_for("words"))

    return render_template("word_form.html", mode="edit", word=word, categories=get_categories())


@app.route("/words/<int:word_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(word_id: int):
    uid = require_user_id()
    word = fetch_word(word_id)
    if word is not None:
        conn = get_db_connection()
        existing = conn.execute(
            "SELECT * FROM user_word_flags WHERE user_id = ? AND word_id = ?",
            (uid, word_id),
        ).fetchone()

        if existing:
            new_value = 0 if existing["favorite"] else 1
            conn.execute(
                "UPDATE user_word_flags SET favorite = ?, updated_at = ? WHERE user_id = ? AND word_id = ?",
                (new_value, now_text(), uid, word_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO user_word_flags (user_id, word_id, favorite, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (uid, word_id, now_text(), now_text()),
            )

        conn.commit()
        conn.close()

    return redirect(request.referrer or url_for("words"))


@app.route("/words/<int:word_id>/delete", methods=["POST"])
@master_required
def delete_word(word_id: int):
    word = fetch_word(word_id)
    if word is None:
        return redirect(url_for("words"))

    conn = get_db_connection()
    conn.execute("DELETE FROM study_logs WHERE word_id = ?", (word_id,))
    conn.execute("DELETE FROM user_word_flags WHERE word_id = ?", (word_id,))
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("words"))


@app.route("/seed", methods=["POST"])
@master_required
def seed_words():
    conn = get_db_connection()
    added_count = 0
    skipped_count = 0

    for english, japanese, example, memo, category, level in SAMPLE_WORDS:
        exists = find_existing_word_by_english(conn, english)

        if not exists:
            audio_text = english
            conn.execute(
                """
                INSERT INTO words (english, japanese, example, memo, audio_text, category, part_of_speech, level, favorite, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (english, japanese, example, memo, audio_text, category, infer_part_of_speech(english, japanese, category), level, current_user_id(), now_text(), now_text()),
            )
            added_count += 1
        else:
            skipped_count += 1

    conn.commit()
    conn.close()
    return redirect(url_for("words", added=added_count, skipped=skipped_count))


@app.route("/quiz")
@login_required
def quiz():
    mode = request.args.get("mode", "choice")
    scope = request.args.get("scope", "all")
    word = get_random_word(scope=scope)

    if word is None:
        return redirect(url_for("words", error="no_words"))

    choices = get_choices(word) if mode == "choice" else []
    return render_template("quiz.html", word=word, choices=choices, mode=mode, scope=scope)


@app.route("/words/<int:word_id>/generate-audio", methods=["POST"])
@master_required
def generate_word_audio(word_id: int):
    word = fetch_word(word_id)
    if word is None:
        return redirect(url_for("words"))

    prefer = request.form.get("prefer", "edge")
    voice = request.form.get("voice", DEFAULT_EDGE_VOICE)
    rate = request.form.get("rate", "+0%")
    target = request.form.get("target", "word")

    if target == "example":
        text = (word["example"] or "").strip()
        column = "example_audio_file"
        suffix = "example"
    else:
        text = get_tts_text(word)
        column = "audio_file"
        suffix = "word"

    audio_path, error = generate_audio_file(text, suffix=f"{suffix}_{word_id}", prefer=prefer, voice=voice, rate=rate)

    if audio_path:
        save_word_audio_path(word_id, column, audio_path)

    return redirect(request.referrer or url_for("words"))


@app.route("/generate-audio-all", methods=["POST"])
@master_required
def generate_audio_all():
    prefer = request.form.get("prefer", "edge")
    voice = request.form.get("voice", DEFAULT_EDGE_VOICE)
    rate = request.form.get("rate", "+0%")
    words = fetch_all_words()

    for word in words:
        text = get_tts_text(word)
        if text and not word["audio_file"]:
            audio_path, error = generate_audio_file(text, suffix=f"word_{word['id']}", prefer=prefer, voice=voice, rate=rate)
            if audio_path:
                save_word_audio_path(word["id"], "audio_file", audio_path)

        example = (word["example"] or "").strip()
        if example and not word["example_audio_file"]:
            audio_path, error = generate_audio_file(example, suffix=f"example_{word['id']}", prefer=prefer, voice=voice, rate=rate)
            if audio_path:
                save_word_audio_path(word["id"], "example_audio_file", audio_path)

    return redirect(request.referrer or url_for("words"))


@app.route("/tts")
@master_required
def tts_page():
    words = fetch_all_words()
    generated_count = sum(1 for word in words if word["audio_file"])
    example_generated_count = sum(1 for word in words if word["example_audio_file"])
    return render_template(
        "tts.html",
        words=words,
        generated_count=generated_count,
        example_generated_count=example_generated_count,
        edge_voices=EDGE_VOICES,
        default_edge_voice=DEFAULT_EDGE_VOICE,
    )


@app.route("/listen")
@login_required
def listen_quiz():
    scope = request.args.get("scope", "all")
    word = get_random_word(scope=scope)

    if word is None:
        return redirect(url_for("words", error="no_words"))

    # v18: リスニングは入力式ではなく、日本語訳を選ぶ4択問題にします。
    choices = get_choices(word)
    return render_template("listening_quiz.html", word=word, choices=choices, mode="listen", scope=scope)


@app.route("/answer", methods=["POST"])
@login_required
def answer():
    word_id = int(request.form["word_id"])
    mode = request.form.get("mode", "choice")
    scope = request.form.get("scope", "all")
    user_answer = request.form.get("answer", "")

    word, correct = record_answer(word_id, mode, user_answer)

    if word is None:
        return redirect(url_for("quiz"))

    streak = get_recent_correct_streak(current_user_id())
    reaction = get_cat_reaction(correct, streak=streak)

    return render_template(
        "result.html",
        word=word,
        user_answer=user_answer,
        is_correct=correct,
        mode=mode,
        scope=scope,
        reaction=reaction,
        streak=streak,
    )


@app.route("/session/start")
@login_required
def session_start():
    mode = request.args.get("mode", "choice")
    scope = request.args.get("scope", "all")
    count = int(request.args.get("count", "10"))

    candidate_ids = get_candidate_ids(scope)
    if not candidate_ids and scope != "all":
        candidate_ids = get_candidate_ids("all")

    if not candidate_ids:
        return redirect(url_for("add_word"))

    if scope == "smart":
        ids = candidate_ids[:count]
        if len(ids) < count and candidate_ids:
            while len(ids) < count:
                ids.append(candidate_ids[len(ids) % len(candidate_ids)])
    else:
        random.shuffle(candidate_ids)

        if len(candidate_ids) >= count:
            ids = candidate_ids[:count]
        else:
            ids = candidate_ids[:]
            while len(ids) < count:
                ids.append(random.choice(candidate_ids))

    session["quiz_session"] = {
        "ids": ids,
        "index": 0,
        "correct": 0,
        "total": len(ids),
        "mode": mode,
        "scope": scope,
        "answers": [],
        "current_streak": 0,
        "best_streak": 0,
    }

    return redirect(url_for("session_quiz"))


@app.route("/session/quiz")
@login_required
def session_quiz():
    data = session.get("quiz_session")
    if not data:
        return redirect(url_for("index"))

    if data["index"] >= data["total"]:
        return redirect(url_for("session_finish"))

    word = fetch_word(data["ids"][data["index"]])
    if word is None:
        data["index"] += 1
        session["quiz_session"] = data
        return redirect(url_for("session_quiz"))

    choices = get_choices(word) if data["mode"] in ["choice", "listen"] else []

    return render_template(
        "session_quiz.html",
        word=word,
        choices=choices,
        data=data,
    )


@app.route("/session/answer", methods=["POST"])
@login_required
def session_answer():
    data = session.get("quiz_session")
    if not data:
        return redirect(url_for("index"))

    word_id = int(request.form["word_id"])
    user_answer = request.form.get("answer", "")
    mode = data["mode"]

    word, correct = record_answer(word_id, mode, user_answer)

    if word is None:
        return redirect(url_for("session_quiz"))

    if correct:
        data["correct"] += 1
        data["current_streak"] = data.get("current_streak", 0) + 1
    else:
        data["current_streak"] = 0

    data["best_streak"] = max(data.get("best_streak", 0), data.get("current_streak", 0))

    data["answers"].append(
        {
            "english": word["english"],
            "user_answer": user_answer,
            "correct_answer": word["japanese"],
            "is_correct": correct,
        }
    )

    data["index"] += 1
    session["quiz_session"] = data

    reaction = get_cat_reaction(correct, streak=data.get("current_streak", 0))

    return render_template(
        "session_result.html",
        word=word,
        user_answer=user_answer,
        is_correct=correct,
        data=data,
        is_finished=data["index"] >= data["total"],
        reaction=reaction,
    )


@app.route("/session/finish")
@login_required
def session_finish():
    data = session.get("quiz_session")
    if not data:
        return redirect(url_for("index"))

    accuracy = round((data["correct"] / data["total"]) * 100, 1) if data["total"] else 0
    test_session_id = data.get("test_session_id")
    if not test_session_id:
        test_session_id = create_test_session(
            current_user_id(),
            data.get("mode", "choice"),
            data.get("scope", "all"),
            data.get("total", 0),
            data.get("correct", 0),
        )
        data["test_session_id"] = test_session_id
        session["quiz_session"] = data

    conn = get_db_connection()
    test_session = conn.execute("SELECT * FROM test_sessions WHERE id = ?", (test_session_id,)).fetchone()
    conn.close()

    finish_reaction = get_cat_reaction(True, streak=data.get("best_streak", 0), finished=True, accuracy=accuracy)
    session_coach = build_session_coach(data, accuracy)
    return render_template("session_finish.html", data=data, accuracy=accuracy, test_session=test_session, finish_reaction=finish_reaction, session_coach=session_coach)


@app.route("/session/reset")
@login_required
def session_reset():
    session.pop("quiz_session", None)
    return redirect(url_for("index"))



@app.route("/users")
@login_required
def users():
    # ユーザー一覧は公開しない。人が増えた時の心理的ハードルを下げるため、通常ユーザーには見せません。
    return redirect(url_for("rankings"))


@app.route("/admin")
@master_required
def admin_home():
    return redirect(url_for("admin_users"))


@app.route("/admin/users")
@master_required
def admin_users():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            u.id,
            u.username,
            u.display_name,
            u.icon_file,
            u.role,
            u.cat_type,
            u.created_at,
            COUNT(DISTINCT l.id) AS total_answers,
            SUM(CASE WHEN l.is_correct = 1 THEN 1 ELSE 0 END) AS correct_answers,
            COUNT(DISTINCT f.id) AS favorite_count
        FROM users u
        LEFT JOIN study_logs l ON l.user_id = u.id
        LEFT JOIN user_word_flags f ON f.user_id = u.id AND f.favorite = 1
        GROUP BY u.id
        ORDER BY
            CASE WHEN u.role = 'master' THEN 0 ELSE 1 END,
            u.id ASC
        """
    ).fetchall()
    conn.close()
    return render_template("admin_users.html", users=rows)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@master_required
def admin_delete_user(user_id: int):
    current_id = require_user_id()
    if user_id == current_id:
        return redirect(url_for("admin_users", error="self"))

    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        conn.close()
        return redirect(url_for("admin_users", error="not_found"))

    conn.execute("DELETE FROM test_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM study_logs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_word_flags WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE words SET created_by_user_id = NULL WHERE created_by_user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_users", deleted="1"))


def create_import_batch(conn: sqlite3.Connection, filename: str, user_id: int | None) -> int:
    cursor = conn.execute(
        """
        INSERT INTO import_batches (
            filename,
            imported_count,
            skipped_count,
            invalid_count,
            status,
            created_by_user_id,
            created_at
        )
        VALUES (?, 0, 0, 0, 'active', ?, ?)
        """,
        (filename or "uploaded.csv", user_id, now_text()),
    )
    return int(cursor.lastrowid)


def update_import_batch_counts(
    conn: sqlite3.Connection,
    batch_id: int,
    imported_count: int,
    skipped_count: int,
    invalid_count: int,
) -> None:
    conn.execute(
        """
        UPDATE import_batches
        SET imported_count = ?,
            skipped_count = ?,
            invalid_count = ?
        WHERE id = ?
        """,
        (imported_count, skipped_count, invalid_count, batch_id),
    )


def get_import_batches() -> list[sqlite3.Row]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            b.id,
            b.filename,
            b.imported_count,
            b.skipped_count,
            b.invalid_count,
            b.status,
            b.created_at,
            b.deleted_at,
            b.deleted_count,
            COALESCE(u.display_name, 'unknown') AS created_by,
            COUNT(w.id) AS current_word_count
        FROM import_batches b
        LEFT JOIN users u ON u.id = b.created_by_user_id
        LEFT JOIN words w ON w.import_batch_id = b.id
        GROUP BY
            b.id,
            b.filename,
            b.imported_count,
            b.skipped_count,
            b.invalid_count,
            b.status,
            b.created_at,
            b.deleted_at,
            b.deleted_count,
            u.display_name
        ORDER BY b.id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_import_batch_detail(batch_id: int) -> dict | None:
    conn = get_db_connection()
    batch = conn.execute(
        """
        SELECT
            b.*,
            COALESCE(u.display_name, 'unknown') AS created_by
        FROM import_batches b
        LEFT JOIN users u ON u.id = b.created_by_user_id
        WHERE b.id = ?
        """,
        (batch_id,),
    ).fetchone()

    if batch is None:
        conn.close()
        return None

    words = conn.execute(
        """
        SELECT id, english, japanese, category, level, part_of_speech, created_at
        FROM words
        WHERE import_batch_id = ?
        ORDER BY id DESC
        LIMIT 500
        """,
        (batch_id,),
    ).fetchall()

    counts = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM words
        WHERE import_batch_id = ?
        """,
        (batch_id,),
    ).fetchone()

    conn.close()
    return {
        "batch": batch,
        "words": words,
        "current_word_count": int(counts["count"] or 0),
    }


def delete_import_batch_words(batch_id: int) -> int:
    conn = get_db_connection()
    rows = conn.execute("SELECT id FROM words WHERE import_batch_id = ?", (batch_id,)).fetchall()
    word_ids = [int(row["id"]) for row in rows]

    if not word_ids:
        conn.execute(
            """
            UPDATE import_batches
            SET status = 'deleted',
                deleted_at = ?,
                deleted_count = 0
            WHERE id = ?
            """,
            (now_text(), batch_id),
        )
        conn.commit()
        conn.close()
        return 0

    placeholders = ",".join(["?"] * len(word_ids))
    # v21:
    # CSVバッチ削除でも study_logs は消しません。
    # 単語だけを取り下げ、ユーザーの累計EXP/レベルは保持します。
    conn.execute(f"DELETE FROM user_word_flags WHERE word_id IN ({placeholders})", word_ids)
    conn.execute(f"DELETE FROM words WHERE id IN ({placeholders})", word_ids)
    conn.execute(
        """
        UPDATE import_batches
        SET status = 'deleted',
            deleted_at = ?,
            deleted_count = ?
        WHERE id = ?
        """,
        (now_text(), len(word_ids), batch_id),
    )
    conn.commit()
    conn.close()
    return len(word_ids)



@app.route("/admin/words")
@master_required
def admin_words():
    conn = get_db_connection()
    total_words = conn.execute("SELECT COUNT(*) AS count FROM words").fetchone()["count"]
    imported_words = conn.execute("SELECT COUNT(*) AS count FROM words WHERE import_batch_id IS NOT NULL").fetchone()["count"]
    manual_words = conn.execute("SELECT COUNT(*) AS count FROM words WHERE import_batch_id IS NULL").fetchone()["count"]
    active_batches = conn.execute("SELECT COUNT(*) AS count FROM import_batches WHERE status = 'active'").fetchone()["count"]
    categories = conn.execute(
        """
        SELECT COALESCE(NULLIF(category, ''), '未分類') AS category, COUNT(*) AS count
        FROM words
        GROUP BY COALESCE(NULLIF(category, ''), '未分類')
        ORDER BY count DESC, category ASC
        """
    ).fetchall()
    recent_words = conn.execute(
        """
        SELECT id, english, japanese, category, level, import_batch_id
        FROM words
        ORDER BY id DESC
        LIMIT 300
        """
    ).fetchall()
    conn.close()
    recent_batches = get_import_batches()[:5]
    return render_template(
        "admin_words.html",
        total_words=total_words,
        imported_words=imported_words,
        manual_words=manual_words,
        active_batches=active_batches,
        categories=categories,
        words=recent_words,
        recent_batches=recent_batches,
    )


def delete_words_by_ids(word_ids: list[int]) -> int:
    clean_ids = []
    for word_id in word_ids:
        try:
            clean_ids.append(int(word_id))
        except Exception:
            pass
    clean_ids = sorted(set(clean_ids))

    if not clean_ids:
        return 0

    placeholders = ",".join(["?"] * len(clean_ids))
    conn = get_db_connection()
    # v21:
    # 単語を削除しても、学習履歴 study_logs は残します。
    # レベル/EXP/連続学習/テスト履歴を「過去の実績」として保持するためです。
    # 画面上の単語別表示は words とJOINするので、削除済み単語は通常表示されません。
    conn.execute(f"DELETE FROM user_word_flags WHERE word_id IN ({placeholders})", clean_ids)
    conn.execute(f"DELETE FROM words WHERE id IN ({placeholders})", clean_ids)
    conn.commit()
    conn.close()
    return len(clean_ids)


@app.route("/admin/words/delete-selected", methods=["POST"])
@master_required
def admin_delete_selected_words():
    ids = request.form.getlist("word_ids")
    deleted_count = delete_words_by_ids(ids)
    return redirect(url_for("admin_words", deleted=deleted_count))


@app.route("/admin/words/delete-category", methods=["POST"])
@master_required
def admin_delete_words_by_category():
    category = request.form.get("category", "").strip()
    confirm = request.form.get("confirm_category", "").strip()

    if not category or confirm != category:
        return redirect(url_for("admin_words", error="category_confirm"))

    conn = get_db_connection()
    if category == "未分類":
        rows = conn.execute("SELECT id FROM words WHERE category IS NULL OR category = ''").fetchall()
    else:
        rows = conn.execute("SELECT id FROM words WHERE category = ?", (category,)).fetchall()
    conn.close()

    deleted_count = delete_words_by_ids([row["id"] for row in rows])
    return redirect(url_for("admin_words", deleted=deleted_count))


@app.route("/admin/words/delete-all", methods=["POST"])
@master_required
def admin_delete_all_words():
    confirm = request.form.get("confirm_text", "").strip()

    if confirm != "DELETE":
        return redirect(url_for("admin_words", error="confirm"))

    conn = get_db_connection()
    # v21:
    # 全単語削除でも study_logs は消しません。
    # 学習実績・レベル・EXP・連続学習はユーザーの過去実績として保持します。
    conn.execute("DELETE FROM user_word_flags")
    conn.execute("DELETE FROM words")
    conn.execute(
        """
        UPDATE import_batches
        SET status = 'deleted',
            deleted_at = ?,
            deleted_count = imported_count
        WHERE status = 'active'
        """,
        (now_text(),),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("admin_words", deleted_all="1"))


@app.route("/rankings")
@login_required
def rankings():
    period = request.args.get("period", "all")
    if period not in {"all", "today", "week"}:
        period = "all"
    rows = get_rankings(period)
    return render_template("rankings.html", rankings=rows, period=period)


@app.route("/share/today")
@login_required
def share_today():
    user = get_current_user()
    summary = get_daily_user_summary(user["id"])

    total_answers = sum(row["total_count"] for row in summary["logs"])
    total_correct = sum(row["correct_count"] or 0 for row in summary["logs"])
    accuracy = round((total_correct / total_answers) * 100, 1) if total_answers else 0

    comment = share_score_comment(accuracy, total_correct, total_answers)
    streak = share_streak_line(total_answers)

    lines = [
        "📚 English Pocket 今日の英語ログ",
        "",
        f"{user['display_name']} は今日 {total_answers}問 解いて",
        f"{total_correct}問 正解しました。",
        f"正答率は {accuracy}%",
        "",
        comment,
        streak,
        "",
    ]

    if summary["logs"]:
        lines.append("内訳")
        for row in summary["logs"]:
            row_total = row["total_count"]
            row_correct = row["correct_count"] or 0
            row_accuracy = round((row_correct / row_total) * 100, 1) if row_total else 0
            mode = share_mode_label(row["mode"])
            lines.append(f"・{mode}: {row_correct}/{row_total} 正解（{row_accuracy}%）")
        lines.append("")
    else:
        lines.append("今日はまだ未回答。1問だけでもやるか。")
        lines.append("")

    stats = get_stats(user["id"])
    game = stats["gamification"]["game"]
    streak_info = stats["gamification"]["streak"]

    lines.extend([
        f"Lv.{game['level']} {game['title']} / {streak_info['current']}日連続学習中",
        "TOEIC950語彙、容赦ないけど燃える。",
        "",
        "#英語学習 #TOEIC #今日の積み上げ #EnglishPocket",
    ])

    share_text = "\n".join(lines)
    stats = get_stats(user["id"])
    return render_template("share_today.html", summary=summary, share_text=share_text, total_answers=total_answers, total_correct=total_correct, accuracy=accuracy, stats=stats)



@app.route("/share/session/<int:test_session_id>")
@login_required
def share_session(test_session_id: int):
    uid = current_user_id()
    conn = get_db_connection()
    test_session = conn.execute(
        "SELECT * FROM test_sessions WHERE id = ? AND user_id = ?",
        (test_session_id, uid),
    ).fetchone()
    conn.close()
    if test_session is None:
        return redirect(url_for("dashboard"))
    return render_template("share_session.html", test_session=test_session)



@app.route("/cat-room")
@login_required
def cat_room():
    # v15: 猫の部屋は廃止。古いリンクから来た場合はホームへ戻します。
    return redirect(url_for("index"))


@app.route("/badges")
@login_required
def badges():
    uid = require_user_id()
    stats = get_stats(uid)
    return render_template("badges.html", stats=stats, badges=stats["gamification"]["badges"])


def build_focus_payload(user_id: int) -> dict:
    plan = build_smart_study_plan(user_id)
    due = plan["breakdown"]["due"]["count"]
    weak = plan["breakdown"]["weak"]["count"]
    if due >= 5:
        title = "復習回収フォーカス"
        message = "今日は新しいことより、忘れかけた単語を取り戻すのが効率的です。"
    elif weak >= 5:
        title = "弱点つぶしフォーカス"
        message = "正答率が低い単語を短時間で回収しましょう。"
    else:
        title = "バランス集中フォーカス"
        message = "復習・弱点・新規を混ぜて、25分で一気に進めます。"

    return {
        "title": title,
        "message": message,
        "plan": plan,
        "steps": [
            {"time": "3分", "title": "準備", "description": "スマート学習ページで今日の優先単語を確認。"},
            {"time": "12分", "title": "おすすめ10問", "description": "迷わず10問を完走。ミスは気にせず記録を作る。"},
            {"time": "7分", "title": "ミス回収", "description": "ミスノートで間違えた単語を見直す。"},
            {"time": "3分", "title": "仕上げ", "description": "もう一度おすすめ10問か、苦手カテゴリを1セット。"},
        ],
    }


def build_daily_plan(user_id: int) -> dict:
    smart_plan = build_smart_study_plan(user_id)
    stats = smart_plan["stats"]
    game = stats.get("gamification", {}).get("game", {})
    streak = stats.get("gamification", {}).get("streak", {})

    total_logs = int(stats.get("total_logs", 0) or 0)
    accuracy = float(stats.get("accuracy", 0) or 0)

    if total_logs < 20:
        phase = "診断フェーズ"
        goal = "まずは20問分の回答履歴を作る"
    elif accuracy < 70:
        phase = "弱点補強フェーズ"
        goal = "苦手単語を優先して正答率70%を超える"
    elif streak.get("current", 0) < 3:
        phase = "習慣化フェーズ"
        goal = "3日連続学習を作る"
    else:
        phase = "得点力強化フェーズ"
        goal = "おすすめ10問で80%以上を安定させる"

    roadmap = [
        {
            "title": "今日",
            "description": "おすすめ10問を1回完走。ミスが出たらミスノートへ。",
            "url": url_for("session_start", mode="choice", scope="smart", count=10),
            "button": "今日の10問",
        },
        {
            "title": "明日",
            "description": "今日ミスした単語が自動で復習優先に回ります。",
            "url": url_for("smart"),
            "button": "スマート学習",
        },
        {
            "title": "今週",
            "description": "苦手カテゴリを1つ選んで、重点的に10問ずつ回します。",
            "url": url_for("mistakes") if feature_enabled(5) else url_for("weak"),
            "button": "弱点を見る",
        },
    ]

    return {
        "phase": phase,
        "goal": goal,
        "smart_plan": smart_plan,
        "top_words": smart_plan.get("top_words", [])[:5],
        "roadmap": roadmap,
        "level": game.get("level", 1),
        "title": game.get("title", ""),
        "streak": streak.get("current", 0),
    }


def build_exam_payload(user_id: int) -> dict:
    plan = build_smart_study_plan(user_id)
    stats = plan["stats"]
    accuracy = float(stats.get("accuracy", 0) or 0)
    total_logs = int(stats.get("total_logs", 0) or 0)

    if total_logs < 30:
        readiness = "診断中"
        advice = "まずは30問ほど解いて、試験モードの判定材料を増やしましょう。"
    elif accuracy >= 85:
        readiness = "本番寄りOK"
        advice = "20問・30問でスピードと安定感を確認しましょう。"
    elif accuracy >= 70:
        readiness = "実戦練習向き"
        advice = "試験モードでミスを出し、ミスノートで回収する流れが効果的です。"
    else:
        readiness = "基礎固め優先"
        advice = "試験モードは短めの20問から。終わったらミスノートで復習しましょう。"

    return {
        "readiness": readiness,
        "advice": advice,
        "stats": stats,
        "plan": plan,
        "drills": [
            {
                "title": "スマート20問",
                "description": "復習・弱点・新規を混ぜた実戦ドリル。",
                "url": url_for("session_start", mode="choice", scope="smart", count=20),
                "tag": "おすすめ",
            },
            {
                "title": "スマート30問",
                "description": "少し長めに集中して、得点力を確認。",
                "url": url_for("session_start", mode="choice", scope="smart", count=30),
                "tag": "本番寄り",
            },
            {
                "title": "リスニング20問",
                "description": "音声で聞いて意味を取る練習。",
                "url": url_for("session_start", mode="listen", scope="smart", count=20),
                "tag": "音声",
            },
        ],
    }


def get_mistake_notebook(user_id: int, limit: int = 80) -> dict:
    """
    ミスノート用データを安全に取得します。
    Render/SQLite環境差で落ちにくいように、複雑な集計関数は避けています。
    """
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            w.id,
            w.english,
            w.japanese,
            w.example,
            COALESCE(NULLIF(w.category, ''), '未分類') AS category,
            COALESCE(NULLIF(w.part_of_speech, ''), 'other') AS part_of_speech,
            w.level,
            COUNT(l.id) AS wrong_count,
            MAX(l.created_at) AS last_wrong_at
        FROM study_logs l
        JOIN words w ON w.id = l.word_id
        WHERE l.user_id = ?
          AND l.is_correct = 0
        GROUP BY
            w.id,
            w.english,
            w.japanese,
            w.example,
            w.category,
            w.part_of_speech,
            w.level
        ORDER BY wrong_count DESC, datetime(last_wrong_at) DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    answers_by_word: dict[int, list[str]] = {}
    if rows:
        word_ids = [int(row["id"]) for row in rows]
        placeholders = ",".join(["?"] * len(word_ids))
        answer_rows = conn.execute(
            f"""
            SELECT word_id, user_answer
            FROM study_logs
            WHERE user_id = ?
              AND is_correct = 0
              AND word_id IN ({placeholders})
            ORDER BY id DESC
            """,
            [user_id] + word_ids,
        ).fetchall()
        for answer_row in answer_rows:
            wid = int(answer_row["word_id"])
            text = (answer_row["user_answer"] or "").strip()
            if text:
                answers_by_word.setdefault(wid, [])
                if text not in answers_by_word[wid]:
                    answers_by_word[wid].append(text)

    conn.close()

    items = []
    for row in rows:
        wrong_count = int(row["wrong_count"] or 0)
        last_days = days_since(row["last_wrong_at"])
        if wrong_count >= 3:
            priority = "最優先"
            tone = "high"
        elif last_days is not None and last_days <= 2:
            priority = "近日ミス"
            tone = "recent"
        else:
            priority = "復習候補"
            tone = "normal"

        word_id = int(row["id"])
        wrong_answers = " / ".join(answers_by_word.get(word_id, [])[:5])

        items.append({
            "id": word_id,
            "english": row["english"],
            "japanese": row["japanese"],
            "example": row["example"],
            "category": row["category"] or "未分類",
            "part_of_speech": normalize_part_of_speech(row["part_of_speech"]) or "other",
            "part_of_speech_label": part_of_speech_label(row["part_of_speech"]),
            "level": row["level"],
            "wrong_count": wrong_count,
            "last_wrong_at": row["last_wrong_at"],
            "days_since_last_wrong": last_days,
            "wrong_answers": wrong_answers,
            "priority": priority,
            "tone": tone,
        })

    return {
        "items": items,
        "total": len(items),
        "high_count": sum(1 for item in items if item["tone"] == "high"),
        "recent_count": sum(1 for item in items if item["tone"] == "recent"),
        "error": "",
    }



@app.route("/smart")
@login_required
def smart():
    if not feature_enabled(1):
        return redirect(url_for("index"))
    uid = require_user_id()
    plan = build_smart_study_plan(uid)
    return render_template("smart.html", plan=plan)



@app.route("/debug/features")
@login_required
def debug_features():
    return jsonify({
        "enabled_features": sorted(list(enabled_feature_ids())),
        "modules": [
            {
                "id": item["id"],
                "key": item["key"],
                "enabled": feature_enabled(item["id"]),
            }
            for item in FEATURE_MODULES
        ],
    })



@app.route("/features")
@login_required
def features():
    return render_template("features.html")



@app.route("/focus")
@login_required
def focus():
    if not feature_enabled(2):
        return redirect(url_for("index"))
    uid = require_user_id()
    payload = build_focus_payload(uid)
    return render_template("focus.html", payload=payload)


@app.route("/plan")
@login_required
def plan():
    if not feature_enabled(3):
        return redirect(url_for("index"))
    uid = require_user_id()
    payload = build_daily_plan(uid)
    return render_template("plan.html", payload=payload)


@app.route("/exam")
@login_required
def exam():
    if not feature_enabled(4):
        return redirect(url_for("index"))
    uid = require_user_id()
    payload = build_exam_payload(uid)
    return render_template("exam.html", payload=payload)


@app.route("/mistakes")
@app.route("/missnote")
@app.route("/missnotebook")
@app.route("/miss-note-book")
@app.route("/miss-notebook")
@app.route("/miss_note")
@app.route("/mistakenote")
@app.route("/mistakenotebook")
@app.route("/mistake-notebook")
@app.route("/mistake_note")
@app.route("/mistake")
@app.route("/miss")
@app.route("/miss-note")
@login_required
def mistakes():
    # v17 hotfix3:
    # ミスノートは学習の中核機能なので、URLの揺れやDB状態に強くします。
    uid = require_user_id()
    try:
        notebook = get_mistake_notebook(uid)
    except Exception as exc:
        notebook = {
            "items": [],
            "total": 0,
            "high_count": 0,
            "recent_count": 0,
            "error": str(exc),
        }
    return render_template("mistakes.html", notebook=notebook)




@app.route("/mistake-note")
@app.route("/mistake_note_direct")
@login_required
def mistake_note_direct():
    uid = require_user_id()
    try:
        notebook = get_mistake_notebook(uid)
        error = ""
    except Exception as exc:
        notebook = {
            "items": [],
            "total": 0,
            "high_count": 0,
            "recent_count": 0,
            "error": str(exc),
        }
        error = str(exc)
    return render_template("mistakes_safe.html", notebook=notebook, error=error)


@app.route("/mistake-note-health")
def mistake_note_health():
    return "mistake-note route ok", 200



@app.route("/mistake-note-raw")
@login_required
def mistake_note_raw():
    uid = require_user_id()
    try:
        notebook = get_mistake_notebook(uid)
        lines = [
            "<h1>ミスノート RAW</h1>",
            f"<p>total: {notebook.get('total', 0)}</p>",
            "<ul>",
        ]
        for item in notebook.get("items", [])[:100]:
            lines.append(f"<li><b>{item.get('english')}</b> - {item.get('japanese')} / {item.get('wrong_count')}回ミス</li>")
        lines.append("</ul>")
        lines.append('<p><a href="/mistake-note">通常表示へ</a></p>')
        return "\\n".join(lines), 200
    except Exception as exc:
        return f"<h1>mistake-note raw error</h1><pre>{str(exc)}</pre>", 500



@app.route("/review")
@login_required
def review():
    uid = require_user_id()
    stats = get_stats(uid)
    return render_template("review.html", stats=stats, review_stats=stats["review_stats"])


@app.route("/toeic-modes")
@login_required
def toeic_modes():
    categories = get_toeic_category_modes()
    return render_template("toeic_modes.html", categories=categories)


@app.route("/share/card")
@login_required
def share_card():
    uid = require_user_id()
    user = get_current_user()
    summary = get_daily_user_summary(uid)
    stats = get_stats(uid)

    total_answers = sum(row["total_count"] for row in summary["logs"])
    total_correct = sum(row["correct_count"] or 0 for row in summary["logs"])
    accuracy = round((total_correct / total_answers) * 100, 1) if total_answers else 0
    comment = share_score_comment(accuracy, total_correct, total_answers)

    return render_template(
        "share_card.html",
        user=user,
        stats=stats,
        summary=summary,
        total_answers=total_answers,
        total_correct=total_correct,
        accuracy=accuracy,
        comment=comment,
    )


@app.route("/share/today/image.svg")
@login_required
def share_today_image_svg():
    uid = require_user_id()
    user = get_current_user()
    summary = get_daily_user_summary(uid)
    stats = get_stats(uid)

    total_answers = sum(row["total_count"] for row in summary["logs"])
    total_correct = sum(row["correct_count"] or 0 for row in summary["logs"])
    accuracy = round((total_correct / total_answers) * 100, 1) if total_answers else 0

    svg = build_today_share_svg(user, summary, stats, total_answers, total_correct, accuracy)
    return Response(svg, mimetype="image/svg+xml")


@app.route("/share/session/<int:test_session_id>/image.svg")
@login_required
def share_session_image_svg(test_session_id: int):
    uid = current_user_id()
    conn = get_db_connection()
    test_session = conn.execute(
        "SELECT * FROM test_sessions WHERE id = ? AND user_id = ?",
        (test_session_id, uid),
    ).fetchone()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()

    if test_session is None or user is None:
        return redirect(url_for("dashboard"))

    svg = build_session_share_svg(user, test_session)
    return Response(svg, mimetype="image/svg+xml")


@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_stats()
    coach = build_learning_coach(stats)
    return render_template("dashboard.html", stats=stats, coach=coach)


@app.route("/weak")
@login_required
def weak():
    stats = get_stats()
    return render_template("weak.html", weak_words=stats["weak_words"])


@app.route("/admin/import-batches")
@master_required
def admin_import_batches():
    batches = get_import_batches()
    return render_template("import_batches.html", batches=batches)


@app.route("/admin/import-batches/<int:batch_id>")
@master_required
def admin_import_batch_detail(batch_id: int):
    detail = get_import_batch_detail(batch_id)
    if detail is None:
        return redirect(url_for("admin_import_batches", error="not_found"))
    return render_template("import_batch_detail.html", detail=detail)


@app.route("/admin/import-batches/<int:batch_id>/delete", methods=["POST"])
@master_required
def admin_delete_import_batch(batch_id: int):
    confirm = request.form.get("confirm_batch_id", "").strip()
    if confirm != str(batch_id):
        return redirect(url_for("admin_import_batch_detail", batch_id=batch_id, error="confirm"))

    deleted_count = delete_import_batch_words(batch_id)
    return redirect(url_for("admin_import_batches", deleted_batch=batch_id, deleted_count=deleted_count))



@app.route("/import", methods=["GET", "POST"])
@master_required
def import_words():
    if request.method == "POST":
        uploaded_file = request.files.get("csv_file")
        if not uploaded_file:
            return render_template("import_result.html", imported_count=0, skipped_count=0, invalid_count=0, batch_id=None, error="CSVファイルが選択されていません。")

        original_filename = uploaded_file.filename or "uploaded.csv"
        raw = uploaded_file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932")

        reader = csv.DictReader(io.StringIO(text))
        imported_count = 0
        skipped_count = 0
        invalid_count = 0

        conn = get_db_connection()
        batch_id = create_import_batch(conn, original_filename, current_user_id())

        for row in reader:
            english = (row.get("english") or row.get("英単語") or "").strip()
            japanese = (row.get("japanese") or row.get("日本語") or "").strip()

            if not english or not japanese:
                invalid_count += 1
                continue

            example = (row.get("example") or row.get("例文") or "").strip()
            memo = (row.get("memo") or row.get("メモ") or "").strip()
            audio_text = (row.get("audio_text") or row.get("読み上げ用") or row.get("音声用テキスト") or "").strip()
            category = (row.get("category") or row.get("カテゴリ") or "未分類").strip() or "未分類"
            part_of_speech = normalize_part_of_speech(
                row.get("part_of_speech") or row.get("pos") or row.get("品詞") or ""
            )
            if not part_of_speech:
                part_of_speech = infer_part_of_speech(english, japanese, category)

            try:
                level = int(row.get("level") or row.get("レベル") or 1)
            except ValueError:
                level = 1

            exists = find_existing_word_by_english(conn, english)

            if exists:
                skipped_count += 1
                continue

            conn.execute(
                """
                INSERT INTO words (
                    english,
                    japanese,
                    example,
                    memo,
                    audio_text,
                    category,
                    part_of_speech,
                    level,
                    favorite,
                    created_by_user_id,
                    import_batch_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    english,
                    japanese,
                    example,
                    memo,
                    audio_text,
                    category,
                    part_of_speech,
                    level,
                    current_user_id(),
                    batch_id,
                    now_text(),
                    now_text(),
                ),
            )
            imported_count += 1

        update_import_batch_counts(conn, batch_id, imported_count, skipped_count, invalid_count)
        conn.commit()
        conn.close()

        return render_template(
            "import_result.html",
            imported_count=imported_count,
            skipped_count=skipped_count,
            invalid_count=invalid_count,
            batch_id=batch_id,
            filename=original_filename,
            error=None,
        )

    return render_template("import_words.html")


@app.route("/export")
@login_required
def export_words():
    words = fetch_all_words()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["english", "japanese", "example", "memo", "audio_text", "category", "level", "favorite"])

    for word in words:
        writer.writerow([
            word["english"],
            word["japanese"],
            word["example"],
            word["memo"],
            word["audio_text"],
            word["category"],
            word["level"],
            word["favorite"],
        ])

    csv_text = "\ufeff" + output.getvalue()

    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=english_words.csv"},
    )


@app.route("/api")
def api_help():
    return render_template("api.html")


@app.get("/api/words")
def api_words():
    all_words = fetch_all_words()
    return jsonify(
        [
            {
                "id": word["id"],
                "english": word["english"],
                "japanese": word["japanese"],
                "example": word["example"],
                "memo": word["memo"],
                "audio_text": word["audio_text"],
                "category": word["category"],
                "level": word["level"],
                "favorite": bool(word["favorite"]),
                "created_at": word["created_at"],
                "updated_at": word["updated_at"],
            }
            for word in all_words
        ]
    )


@app.post("/api/words")
def api_add_word():
    payload = request.get_json(silent=True) or {}

    english = str(payload.get("english", "")).strip()
    japanese = str(payload.get("japanese", "")).strip()
    example = str(payload.get("example", "")).strip()
    memo = str(payload.get("memo", "")).strip()
    audio_text = str(payload.get("audio_text", "")).strip()
    category = str(payload.get("category", "未分類")).strip() or "未分類"
    level = int(payload.get("level", 1))
    favorite = 1 if payload.get("favorite") else 0

    if not english or not japanese:
        return jsonify({"ok": False, "error": "english and japanese are required"}), 400

    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO words (english, japanese, example, memo, audio_text, category, level, favorite, created_by_user_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (english, japanese, example, memo, audio_text, category, level, favorite, current_user_id(), now_text(), now_text()),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return jsonify({"ok": True, "id": new_id})


@app.get("/api/quiz")
def api_quiz():
    mode = request.args.get("mode", "choice")
    scope = request.args.get("scope", "all")
    word = get_random_word(scope=scope)

    if word is None:
        return jsonify({"ok": False, "error": "no words"}), 404

    choices = get_choices(word) if mode == "choice" else []

    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "scope": scope,
            "question": {
                "word_id": word["id"],
                "english": word["english"],
                "example": word["example"],
                "audio_text": word["audio_text"],
                "category": word["category"],
                "level": word["level"],
            },
            "choices": choices,
        }
    )


@app.post("/api/answer")
def api_answer():
    payload = request.get_json(silent=True) or {}

    try:
        word_id = int(payload.get("word_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "word_id is required"}), 400

    answer_text = str(payload.get("answer", "")).strip()
    mode = str(payload.get("mode", "choice")).strip()

    word, correct = record_answer(word_id, mode, answer_text)

    if word is None:
        return jsonify({"ok": False, "error": "word not found"}), 404

    return jsonify(
        {
            "ok": True,
            "is_correct": correct,
            "correct_answer": word["japanese"],
            "english": word["english"],
        }
    )


@app.get("/api/stats")
def api_stats():
    stats = get_stats()

    return jsonify(
        {
            "total_words": stats["total_words"],
            "favorite_words": stats["favorite_words"],
            "total_logs": stats["total_logs"],
            "correct_logs": stats["correct_logs"],
            "accuracy": stats["accuracy"],
            "weak_words": [
                {
                    "id": row["id"],
                    "english": row["english"],
                    "japanese": row["japanese"],
                    "category": row["category"],
                    "level": row["level"],
                    "favorite": bool(row["favorite"]),
                    "total_count": row["total_count"],
                    "incorrect_count": row["incorrect_count"],
                    "accuracy": row["accuracy"],
                }
                for row in stats["weak_words"]
            ],
        }
    )


# Initialize database for production servers such as Gunicorn on Render.
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
