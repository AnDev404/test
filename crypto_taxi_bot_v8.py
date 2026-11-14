import getpass
import html
import json
import os
import re
import secrets
import sys
import threading
import time
import textwrap
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class _Dummy:
        def __getattr__(self, name):
            return ""

    Fore = _Dummy()
    Style = _Dummy()


# ================= CONFIG =================
BASE_URL = "https://thecryptotaxi.com"
API_LOGIN = f"{BASE_URL}/api/auth/login"
API_STATE = f"{BASE_URL}/api/state"
API_START_TRIP = f"{BASE_URL}/api/trips/start"

# Satu identitas perangkat yang stabil untuk instalasi ini.
# Tidak diacak ulang setiap kali script dijalankan.
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
DEFAULT_INTERVAL = 5
DASHBOARD_REFRESH = 2
UI_REFRESH = 1
SUMMARY_API_REFRESH = 30
USDT_IDR_REFRESH = 600
USDT_IDR_API = "https://api.coinpaprika.com/v1/tickers/usdt-tether"
MAIN_BOX_WIDTH = 64
MAIN_INFO_LABEL_WIDTH = 27

DATA_DIR = Path(__file__).resolve().parent / "ct_auto_bot_data"
DATA_FILE = DATA_DIR / "account_session.json"
STORAGE_LOCK = threading.RLock()

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_POLL_TIMEOUT = 10
TELEGRAM_MESSAGE_LIMIT = 3900

# Warna terminal
C_OK = Fore.GREEN + Style.BRIGHT
C_ERR = Fore.RED + Style.BRIGHT
C_WARN = Fore.YELLOW + Style.BRIGHT
C_INFO = Fore.CYAN + Style.BRIGHT
C_DIM = Fore.WHITE + Style.DIM
C_MAG = Fore.MAGENTA + Style.BRIGHT
C_BLUE = Fore.BLUE + Style.BRIGHT
C_RESET = Style.RESET_ALL

LINE = "─"


# ================= STORAGE =================
def random_device_id() -> str:
    """Buat device ID satu kali dan simpan agar stabil antar-sesi."""
    return f"{secrets.token_hex(16)}.{secrets.token_hex(32)}"


def default_data() -> dict:
    return {
        "version": 2,
        "profile": {
            "user_agent": USER_AGENT,
            "device_id": random_device_id(),
            "lang": ACCEPT_LANGUAGE,
        },
        "accounts": [],
        "active_account_id": None,
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
            "message_id": None,
            "last_signature": None,
        },
    }


def get_telegram_settings(data: dict) -> dict:
    """Ambil pengaturan Telegram tanpa mengubah konfigurasi yang sudah ada."""
    defaults = {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "message_id": None,
        "last_signature": None,
    }
    config = data.get("telegram")
    if not isinstance(config, dict):
        config = {}
        data["telegram"] = config
    for key, value in defaults.items():
        config.setdefault(key, value)
    return config


def get_accounts(data: dict) -> list:
    accounts = data.get("accounts", [])
    return accounts if isinstance(accounts, list) else []


def find_account(data: dict, account_id: str = None):
    if not account_id:
        return None
    for account in get_accounts(data):
        if account.get("id") == account_id:
            return account
    return None


def get_selected_account(data: dict):
    accounts = get_accounts(data)
    if not accounts:
        return None
    selected = find_account(data, data.get("active_account_id"))
    if selected is not None:
        return selected
    data["active_account_id"] = accounts[0].get("id")
    return accounts[0]


def set_selected_account(data: dict, account: dict) -> None:
    data["active_account_id"] = account.get("id")
    save_data(data)

def ensure_storage_permissions(path: Path, is_dir: bool = False) -> None:
    """Batasi akses file sesi pada sistem yang mendukung chmod."""
    try:
        os.chmod(path, 0o700 if is_dir else 0o600)
    except OSError:
        # Windows atau filesystem tertentu mungkin tidak mendukung chmod.
        pass


def load_data() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_storage_permissions(DATA_DIR, is_dir=True)

    if not DATA_FILE.exists():
        data = default_data()
        save_data(data)
        return data

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"File penyimpanan tidak bisa dibaca: {DATA_FILE}\nDetail: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("Format file penyimpanan tidak dikenal.")

    # Migrasi otomatis dari format SINGLE ACCOUNT versi 1.
    if data.get("version") == 1:
        profile = data.get("profile") or {}
        profile.setdefault("user_agent", USER_AGENT)
        profile.setdefault("device_id", random_device_id())
        profile.setdefault("lang", ACCEPT_LANGUAGE)
        legacy_session = data.get("session")
        accounts = []
        active_id = None
        if isinstance(legacy_session, dict):
            legacy_session = dict(legacy_session)
            legacy_session.setdefault("id", secrets.token_hex(4))
            accounts.append(legacy_session)
            active_id = legacy_session["id"]
        data = {
            "version": 2,
            "profile": profile,
            "accounts": accounts,
            "active_account_id": active_id,
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "chat_id": "",
                "message_id": None,
                "last_signature": None,
            },
        }
        save_data(data)
        return data

    if data.get("version") != 2:
        raise RuntimeError("Format file penyimpanan tidak dikenal.")

    data.setdefault("profile", {})
    data["profile"].setdefault("user_agent", USER_AGENT)
    data["profile"].setdefault("device_id", random_device_id())
    data["profile"].setdefault("lang", ACCEPT_LANGUAGE)
    data.setdefault("accounts", [])
    data.setdefault("active_account_id", None)
    telegram_config_was_missing = not isinstance(data.get("telegram"), dict)
    existing_telegram_config = data.get("telegram") if isinstance(data.get("telegram"), dict) else {}
    telegram_keys = ("enabled", "bot_token", "chat_id", "message_id", "last_signature")
    telegram_keys_missing = any(key not in existing_telegram_config for key in telegram_keys)
    telegram_config = get_telegram_settings(data)

    if not isinstance(data["accounts"], list):
        raise RuntimeError("Daftar akun pada file penyimpanan tidak valid.")

    # Pastikan setiap akun mempunyai ID lokal yang stabil.
    changed = False
    for account in data["accounts"]:
        if not isinstance(account, dict):
            raise RuntimeError("Ada data akun yang formatnya tidak valid.")
        if not account.get("id"):
            account["id"] = secrets.token_hex(4)
            changed = True
    if changed or telegram_config_was_missing or telegram_keys_missing:
        save_data(data)
    return data

def save_data(data: dict) -> None:
    """Simpan JSON secara atomik dengan lock dan file sementara yang unik."""
    with STORAGE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ensure_storage_permissions(DATA_DIR, is_dir=True)

        temp_file = DATA_DIR / (
            f".{DATA_FILE.name}.{os.getpid()}.{threading.get_ident()}."
            f"{secrets.token_hex(6)}.tmp"
        )
        try:
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            ensure_storage_permissions(temp_file)
            os.replace(temp_file, DATA_FILE)
            ensure_storage_permissions(DATA_FILE)
        except OSError as exc:
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"Gagal menyimpan data sesi: {exc}") from exc


def serialize_cookies(session: requests.Session) -> list:
    cookies = []
    for cookie in session.cookies:
        cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": bool(cookie.secure),
            "expires": cookie.expires,
            "rest": cookie._rest,
        })
    return cookies


def restore_cookies(session: requests.Session, cookie_rows: list) -> None:
    for row in cookie_rows:
        cookie = requests.cookies.create_cookie(
            name=row["name"],
            value=row["value"],
            domain=row.get("domain") or "",
            path=row.get("path") or "/",
            secure=bool(row.get("secure", False)),
            expires=row.get("expires"),
            rest=row.get("rest") or {},
        )
        session.cookies.set_cookie(cookie)


def save_session(data: dict, username: str, session: requests.Session, state=None) -> None:
    me = (state or {}).get("me", {}) if isinstance(state, dict) else {}
    user_id = me.get("id")
    actual_username = me.get("username") or username

    # Satu rangkaian update akun + simpan dilindungi agar tidak saling menimpa.
    with STORAGE_LOCK:
        account = None
        for item in get_accounts(data):
            if user_id is not None and str(item.get("user_id")) == str(user_id):
                account = item
                break
        if account is None:
            for item in get_accounts(data):
                if str(item.get("username", "")).casefold() == str(actual_username).casefold():
                    account = item
                    break

        if account is None:
            account = {"id": secrets.token_hex(4)}
            data.setdefault("accounts", []).append(account)

        account.update({
            "username": actual_username,
            "user_id": user_id if user_id is not None else account.get("user_id"),
            "cookies": serialize_cookies(session),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        })
        data["active_account_id"] = account["id"]
        save_data(data)


def delete_saved_account(data: dict, account_id: str) -> bool:
    accounts = get_accounts(data)
    retained = [item for item in accounts if item.get("id") != account_id]
    if len(retained) == len(accounts):
        return False
    data["accounts"] = retained
    if data.get("active_account_id") == account_id:
        data["active_account_id"] = retained[0].get("id") if retained else None
    save_data(data)
    return True

def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def banner() -> None:
    """Banner dengan lebar tetap; teks judul selalu terpusat dan garis utuh."""
    inner_width = MAIN_BOX_WIDTH - 4
    top = "  ╔" + "═" * inner_width + "╗"
    bottom = "  ╚" + "═" * inner_width + "╝"
    title_1 = "THE CRYPTO TAXI - AUTO BOT".center(inner_width)
    title_2 = "MULTI ACCOUNT MANAGER".center(inner_width)
    print()
    print(C_INFO + top + C_RESET)
    print(C_INFO + "  ║" + C_MAG + title_1 + C_INFO + "║" + C_RESET)
    print(C_INFO + "  ║" + C_BLUE + title_2 + C_INFO + "║" + C_RESET)
    print(C_INFO + bottom + C_RESET)
    print()


def section(title: str) -> None:
    """Garis atas kotak dengan lebar tetap agar sejajar dengan sisi dan bawah."""
    fill = max(1, MAIN_BOX_WIDTH - 8 - len(title))
    print()
    print(C_INFO + f"  ┌── {title} " + LINE * fill + "┐" + C_RESET)


def section_end() -> None:
    """Garis bawah kotak dengan lebar yang sama persis dengan section()."""
    inner = MAIN_BOX_WIDTH - 4
    print(C_INFO + "  └" + LINE * inner + "┘" + C_RESET)


def _visible_text(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(value))


def _print_box_content(prefix: str, content: str, color=C_RESET) -> None:
    """Cetak satu baris di dalam kotak, termasuk sisi kanan dan padding."""
    visible_length = len(_visible_text(content))
    available = MAIN_BOX_WIDTH - len(_visible_text(prefix)) - 1
    if visible_length > available:
        chunks = textwrap.wrap(
            _visible_text(content), width=available,
            break_long_words=True, break_on_hyphens=False,
        )
        for index, chunk in enumerate(chunks):
            line_prefix = prefix if index == 0 else "  │ " + " " * (len(prefix) - 4)
            padding = max(0, MAIN_BOX_WIDTH - len(line_prefix) - len(chunk) - 1)
            print(f"{line_prefix}{color}{chunk}{C_RESET}{' ' * padding}{C_INFO}│{C_RESET}")
        return
    padding = max(0, MAIN_BOX_WIDTH - len(_visible_text(prefix)) - visible_length - 1)
    print(f"{prefix}{color}{content}{C_RESET}{' ' * padding}{C_INFO}│{C_RESET}")


def info(label: str, value, color=C_RESET) -> None:
    """Cetak label/value dengan kolom tetap dan garis kanan kotak utuh."""
    label_text = str(label)[:MAIN_INFO_LABEL_WIDTH]
    prefix = f"  {C_INFO}│{C_RESET} {label_text:<{MAIN_INFO_LABEL_WIDTH}} : "
    # Prefix berisi kode warna; hitung panjang visual, bukan panjang string ANSI.
    visible_prefix = len(_visible_text(prefix))
    max_value = MAIN_BOX_WIDTH - visible_prefix - 1
    value_text = str(value)
    chunks = textwrap.wrap(
        value_text, width=max(1, max_value),
        break_long_words=True, break_on_hyphens=False,
    ) or [""]
    continuation = "  " + C_INFO + "│" + C_RESET + " " * (MAIN_INFO_LABEL_WIDTH + 4)
    for index, chunk in enumerate(chunks):
        line_prefix = prefix if index == 0 else continuation
        visible_len = len(_visible_text(line_prefix))
        padding = max(0, MAIN_BOX_WIDTH - visible_len - len(chunk) - 1)
        print(f"{line_prefix}{color}{chunk}{C_RESET}{' ' * padding}{C_INFO}│{C_RESET}")


def info_segments(label: str, segments: list) -> None:
    """Cetak satu baris value dengan beberapa warna, membungkus di batas segmen."""
    prefix = f"  {C_INFO}│{C_RESET} {str(label)[:MAIN_INFO_LABEL_WIDTH]:<{MAIN_INFO_LABEL_WIDTH}} : "
    continuation = "  " + C_INFO + "│" + C_RESET + " " * (MAIN_INFO_LABEL_WIDTH + 4)
    max_value = MAIN_BOX_WIDTH - len(_visible_text(prefix)) - 1
    groups = []
    current = []
    current_len = 0
    for segment_text, segment_color in segments:
        segment_text = str(segment_text)
        separator = " | " if current else ""
        if current and current_len + len(separator) + len(segment_text) > max_value:
            groups.append(current)
            current = [(segment_text, segment_color)]
            current_len = len(segment_text)
        else:
            if separator:
                current.append((separator, C_RESET))
                current_len += len(separator)
            current.append((segment_text, segment_color))
            current_len += len(segment_text)
    if current:
        groups.append(current)
    if not groups:
        groups = [[("-", C_RESET)]]

    for index, group in enumerate(groups):
        plain = "".join(item[0] for item in group)
        line_prefix = prefix if index == 0 else continuation
        visible_len = len(_visible_text(line_prefix)) + len(plain)
        padding = max(0, MAIN_BOX_WIDTH - visible_len - 1)
        colored = "".join(f"{color}{part}{C_RESET}" for part, color in group)
        print(f"{line_prefix}{colored}{' ' * padding}{C_INFO}│{C_RESET}")


def box_text(text: str, color=C_RESET) -> None:
    """Cetak teks menu di dalam kotak dengan lebar tetap."""
    _print_box_content("  " + C_INFO + "│" + C_RESET + " ", str(text), color)


def spinner(message: str, seconds: float = 0.8) -> None:
    frames = ["|", "/", "-", "\\"]
    end = time.time() + seconds
    index = 0
    while time.time() < end:
        sys.stdout.write(f"\r  {C_INFO}{frames[index % len(frames)]}{C_RESET} {message}")
        sys.stdout.flush()
        time.sleep(0.08)
        index += 1
    sys.stdout.write(f"\r  {C_OK}OK{C_RESET} {message}   \n")
    sys.stdout.flush()


def fmt_ts(ts_ms) -> str:
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "-"


def fmt_datetime_ts(ts_ms) -> str:
    """Format Unix timestamp (milidetik) memakai zona waktu lokal terminal."""
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000).strftime("%d-%m-%Y %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "-"


def fmt_remaining_ms(ts_ms) -> str:
    """Tampilkan sisa waktu dari timestamp milidetik."""
    try:
        remaining = int((float(ts_ms) - time.time() * 1000) / 1000)
    except (TypeError, ValueError, OverflowError):
        return "-"
    if remaining <= 0:
        return "sudah berakhir"
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} hari")
    if hours:
        parts.append(f"{hours} jam")
    if minutes and not days:
        parts.append(f"{minutes} menit")
    if not days and not hours and not minutes:
        parts.append(f"{seconds} detik")
    return " ".join(parts)


def money(value) -> str:
    try:
        return f"{float(value or 0):.4f} USDT"
    except (TypeError, ValueError):
        return "0.0000 USDT"


def wait_for_main_menu() -> None:
    """Tunggu Enter setelah proses selesai agar menu utama dapat dibuka kembali."""
    try:
        input("\n  Tekan Enter untuk kembali ke menu utama...")
    except EOFError:
        # Jalankan tanpa input interaktif: jangan biarkan proses macet/gagal di sini.
        print()


def enter_pressed() -> bool:
    """Periksa apakah Enter ditekan tanpa menghentikan pembaruan dashboard."""
    if not sys.stdin.isatty():
        return False

    if os.name == "nt":
        import msvcrt

        pressed = False
        while msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                pressed = True
        return pressed

    try:
        import select
        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if readable:
            # Pada terminal POSIX, input tersedia setelah pengguna menekan Enter.
            return bool(sys.stdin.readline())
    except (OSError, ValueError):
        return False
    return False


def wait_with_enter(seconds: float) -> bool:
    """Tunggu selama seconds; True jika pengguna menekan Enter."""
    if not sys.stdin.isatty():
        time.sleep(max(0, seconds))
        return False

    deadline = time.monotonic() + max(0, seconds)
    while True:
        if enter_pressed():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


# ================= SESSION / API =================
def create_session(profile: dict) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "user-agent": profile["user_agent"],
        "x-ct-device": profile["device_id"],
        "content-type": "application/json",
        "x-ct": "1",
        "x-ct-lang": "en",
        "accept": "*/*",
        "origin": BASE_URL,
        "x-requested-with": "qzbr.zpr.pt",
        "referer": f"{BASE_URL}/",
        "accept-language": profile["lang"],
    })
    return session


def create_saved_session(data: dict, saved: dict = None) -> requests.Session:
    session = create_session(data["profile"])
    saved = saved or get_selected_account(data) or {}
    restore_cookies(session, saved.get("cookies", []))
    return session

def login(session: requests.Session, username: str, password: str) -> bool:
    try:
        response = session.post(
            API_LOGIN,
            json={"username": username, "password": password},
            timeout=20,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:160] if exc.response is not None else str(exc)
        print(f"  {C_ERR}Login gagal (HTTP {status}): {body}{C_RESET}")
        return False
    except requests.RequestException as exc:
        print(f"  {C_ERR}Tidak bisa menghubungi server: {exc}{C_RESET}")
        return False

    try:
        result = response.json()
    except ValueError:
        print(f"  {C_ERR}Respons login bukan JSON yang valid.{C_RESET}")
        return False

    if not result.get("ok"):
        print(f"  {C_ERR}Login ditolak: {response.text[:160]}{C_RESET}")
        return False

    if "__Host-ct_s" not in session.cookies:
        print(f"  {C_ERR}Cookie sesi tidak ditemukan pada respons login.{C_RESET}")
        return False

    return True


def get_state(session: requests.Session) -> dict:
    response = session.post(API_STATE, json={}, timeout=20)
    response.raise_for_status()
    return response.json()


def start_trip(session: requests.Session, car_id) -> dict:
    response = session.post(
        API_START_TRIP,
        json={"carId": str(car_id)},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def find_car(state: dict, car_id, preferred_type=None):
    """Cari kendaraan dengan memprioritaskan koleksi yang dipilih user."""
    own, rented = vehicle_collections(state)
    groups = [("OWNED", own), ("RENTAL", rented)]
    preferred = str(preferred_type or "").upper()
    if preferred in {"OWNED", "RENTAL"}:
        groups.sort(key=lambda item: 0 if item[0] == preferred else 1)
    for kind, cars in groups:
        for car in cars:
            if isinstance(car, dict) and str(car.get("id")) == str(car_id):
                result = dict(car)
                result["_ct_source"] = kind
                return result
    return None

def vehicle_collections(state: dict):
    """Kembalikan daftar mobil milik sendiri dan rental sesuai respons API."""
    own = state.get("myCars", []) if isinstance(state, dict) else []
    rented = state.get("rentedCars", []) if isinstance(state, dict) else []
    if not isinstance(own, list):
        own = []
    if not isinstance(rented, list):
        rented = []
    return own, rented


def vehicle_type(state: dict, car_id) -> str:
    """Identifikasi kategori berdasarkan koleksi API, bukan tebakan nama mobil."""
    own, rented = vehicle_collections(state)
    if any(str(item.get("id")) == str(car_id) for item in rented if isinstance(item, dict)):
        return "RENTAL"
    if any(str(item.get("id")) == str(car_id) for item in own if isinstance(item, dict)):
        return "OWNED"
    return "UNKNOWN"


def vehicle_access_label(car: dict) -> str:
    """Terjemahkan status akses API menjadi keterangan singkat untuk terminal."""
    if car.get("broken"):
        return "TIDAK BISA DIGUNAKAN (Kendaraan rusak)"

    trip = car.get("trip")
    if isinstance(trip, dict):
        try:
            if float(trip.get("endsAt", 0)) > time.time() * 1000:
                return f"SEDANG BERJALAN (selesai {fmt_ts(trip.get('endsAt'))})"
        except (TypeError, ValueError):
            pass

    if car.get("canDrive") is True:
        return "BISA DIGUNAKAN"

    block = car.get("block") if isinstance(car.get("block"), dict) else {}
    if car.get("canDrive") is False:
        code = str(block.get("code") or "").strip().lower()
        message = str(block.get("msg") or "").strip()
        quota = car.get("quota") if isinstance(car.get("quota"), dict) else {}

        if code == "shift_ending":
            match = re.search(r"(\d+)\s*(?:min|mins|minute|minutes)\b", message, re.IGNORECASE)
            if match:
                minutes = int(match.group(1))
                return (
                    "TIDAK BISA DIGUNAKAN "
                    f"(Sisa shift {minutes} menit; tidak cukup untuk trip)"
                )
            return "TIDAK BISA DIGUNAKAN (Waktu shift tidak cukup untuk trip)"

        if code == "quota":
            used = quota.get("used")
            limit = quota.get("limit")
            reset_match = re.search(r"reset(?:s)?\s+(?:at\s+)?(\d{1,2}:\d{2})", message, re.IGNORECASE)
            reset_text = f", reset {reset_match.group(1)}" if reset_match else ""
            if used is not None and limit is not None:
                return f"TIDAK BISA DIGUNAKAN (Kuota harian habis: {used}/{limit} trip{reset_text})"
            return f"TIDAK BISA DIGUNAKAN (Kuota harian habis{reset_text})"

        if code in {"broken", "car_broken"}:
            return "TIDAK BISA DIGUNAKAN (Kendaraan rusak)"
        if code in {"not_your_shift", "not-your-shift", "shift_not_yours"} or "not your shift" in message.casefold():
            return "TIDAK BISA DIGUNAKAN (Bukan giliran akun ini)"

        if code:
            readable_code = code.replace("_", " ").strip().capitalize()
            return f"TIDAK BISA DIGUNAKAN ({readable_code})"
        return "TIDAK BISA DIGUNAKAN (Akses belum diberikan server)"

    return "STATUS BELUM DIKETAHUI (Belum dikirim API)"


def vehicle_access_color(car: dict, access_label=None):
    """Merah untuk kerusakan; kuning untuk batas/akses yang bukan kegagalan."""
    access_label = access_label or vehicle_access_label(car)
    if car.get("broken"):
        return C_ERR
    if access_label == "BISA DIGUNAKAN" or access_label.startswith("SEDANG BERJALAN"):
        return C_OK
    if access_label.startswith("TIDAK BISA DIGUNAKAN"):
        return C_WARN
    return C_WARN


def bonus_is_available(quota: dict, now_ms=None) -> bool:
    """Bonus trip dianggap tersedia jika API mengirim jumlah positif dan belum kedaluwarsa."""
    if not isinstance(quota, dict):
        return False
    try:
        bonus_count = float(quota.get("bonus") or 0)
    except (TypeError, ValueError):
        return False
    if bonus_count <= 0:
        return False
    expiry = quota.get("bonusExpiresAt")
    if expiry not in (None, "", 0, "0"):
        try:
            current_ms = float(now_ms if now_ms is not None else time.time() * 1000)
            if float(expiry) <= current_ms:
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def find_contract(state: dict, contract_id):
    if contract_id is None:
        return None
    contracts = state.get("contracts", []) if isinstance(state, dict) else []
    if not isinstance(contracts, list):
        return None
    for contract in contracts:
        if isinstance(contract, dict) and str(contract.get("id")) == str(contract_id):
            return contract
    return None


def shift_summary_lines(state: dict, car: dict, shift_name: str, current_user_id) -> list[str]:
    """Buat ringkasan shift bertingkat tanpa mengulang pesan teknis API."""
    shifts = car.get("shifts") if isinstance(car.get("shifts"), dict) else {}
    shift = shifts.get(shift_name) if isinstance(shifts.get(shift_name), dict) else {}
    me = state.get("me", {}) if isinstance(state, dict) else {}
    current_username = me.get("username") if isinstance(me, dict) else None

    holder_name = shift.get("holderName")
    holder_id = shift.get("holderId")
    if holder_name or holder_id is not None:
        holder = str(holder_name or f"User ID {holder_id}")
        is_current = (
            current_user_id is not None and str(holder_id) == str(current_user_id)
        ) or (
            holder_id is None and current_username and
            str(holder_name).casefold() == str(current_username).casefold()
        )
        holder += " (akun ini)" if is_current else " (akun lain)"
    else:
        holder = "belum ada pemegang"

    contract_id = shift.get("contractId")
    contract = find_contract(state, contract_id)
    start_at = shift.get("contractStartsAt")
    end_at = shift.get("contractEndsAt")
    if contract:
        start_at = start_at or contract.get("startsAt")
        end_at = end_at or contract.get("endsAt")

    if contract_id is None:
        contract_label = "BELUM ADA KONTRAK"
    else:
        if end_at:
            try:
                contract_active = float(end_at) > time.time() * 1000
            except (TypeError, ValueError, OverflowError):
                contract_active = None
        else:
            contract_active = None
        if contract_active is True:
            contract_label = f"KONTRAK {contract_id} AKTIF"
        elif contract_active is False:
            contract_label = f"KONTRAK {contract_id} BERAKHIR"
        else:
            contract_label = f"KONTRAK {contract_id} TERDAFTAR"

    lines = [f"      {shift_name} : {holder} | {contract_label}"]
    if contract_id is None:
        return lines

    if start_at:
        lines.append(f"           Mulai  : {fmt_datetime_ts(start_at)}")
    if end_at:
        lines.append(f"           Sampai : {fmt_datetime_ts(end_at)}")

    daily_trips = shift.get("dailyTrips")
    owner_pct = shift.get("ownerPct")
    if contract:
        if daily_trips is None:
            daily_trips = contract.get("dailyTrips")
        if owner_pct is None:
            owner_pct = contract.get("ownerPct")

    details = []
    if daily_trips is not None:
        details.append(f"Jatah {daily_trips} trip/hari")
    if owner_pct is not None:
        details.append(f"Bagian pemilik {owner_pct}%")
    if details:
        lines.append("           " + " | ".join(details))
    return lines


def quota_display(quota: dict) -> str:
    """Format quota; bonus hanya ditampilkan bila jumlahnya positif."""
    quota = quota if isinstance(quota, dict) else {}
    used = quota.get("used", "-")
    limit = quota.get("limit", "-")
    left = quota.get("left", "tidak dikirim")
    result = f"{used}/{limit} | Sisa {left}"
    try:
        bonus = float(quota.get("bonus") or 0)
    except (TypeError, ValueError):
        bonus = 0
    if bonus > 0:
        bonus_text = str(int(bonus)) if bonus.is_integer() else str(bonus)
        result += f" + {bonus_text} Bonus"
    return result


def quota_display_for_vehicle(state: dict, car: dict, category: str) -> str:
    """Tampilkan batas trip kontrak rental bila API menyediakannya.

    Untuk OWNED, nilai quota API dipakai apa adanya. Untuk RENTAL, dailyTrips
    pada kontrak aktif menjadi batas tampilan yang lebih spesifik daripada
    limit harian generik kendaraan. Logika worker tetap memakai quota mentah API.
    """
    quota = car.get("quota") if isinstance(car.get("quota"), dict) else {}
    display_quota = dict(quota)
    if str(category).upper() != "RENTAL":
        return quota_display(display_quota)

    shifts = car.get("shifts") if isinstance(car.get("shifts"), dict) else {}
    contracts = state.get("contracts", []) if isinstance(state, dict) else []
    if not isinstance(contracts, list):
        contracts = []
    now_ms = state_now_ms(state) or time.time() * 1000
    preferred_shift = str(quota.get("shift") or "").upper()
    ordered_names = ([preferred_shift] if preferred_shift in {"AM", "PM"} else [])
    ordered_names += [name for name in ("AM", "PM") if name not in ordered_names]

    daily_limit = None
    for shift_name in ordered_names:
        shift = shifts.get(shift_name)
        if not isinstance(shift, dict):
            continue
        candidate = shift.get("dailyTrips")
        contract_id = shift.get("contractId")
        contract = None
        if contract_id is not None:
            for item in contracts:
                if isinstance(item, dict) and str(item.get("id")) == str(contract_id):
                    contract = item
                    break
        if candidate is None and contract:
            candidate = contract.get("dailyTrips")
        if candidate is None:
            continue
        try:
            candidate_num = int(candidate)
        except (TypeError, ValueError, OverflowError):
            continue
        if candidate_num <= 0:
            continue

        # Kontrak yang memiliki waktu akhir harus masih aktif.
        end_at = shift.get("contractEndsAt") or (contract.get("endsAt") if contract else None)
        if end_at not in (None, "", 0, "0"):
            try:
                if float(end_at) <= float(now_ms):
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
        # dailyTrips yang melekat pada shift/kontrak rental adalah limit kontrak.
        daily_limit = candidate_num
        break

    if daily_limit is not None:
        try:
            used = int(quota.get("used", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            used = 0
        display_quota["limit"] = daily_limit
        display_quota["left"] = max(0, daily_limit - used)

    return quota_display(display_quota)


def print_vehicle_catalog(state: dict) -> list:
    """Tampilkan OWNED dan RENTAL secara ringkas dalam satu daftar."""
    own_raw, rented_raw = vehicle_collections(state)
    own = [car for car in own_raw if isinstance(car, dict)]
    rented = [car for car in rented_raw if isinstance(car, dict)]
    entries = [("OWNED", car) for car in own]
    entries += [("RENTAL", car) for car in rented]
    me = state.get("me", {}) if isinstance(state, dict) else {}
    current_user_id = me.get("id") if isinstance(me, dict) else None
    username = me.get("username", "-") if isinstance(me, dict) else "-"

    section("KENDARAAN & RENTAL")
    info("Akun", username, C_MAG)
    info("Total kendaraan", len(entries), C_BLUE)
    section_end()

    number = 0
    if own:
        print("\n  MILIK SENDIRI")
        for car in own:
            number += 1
            _print_vehicle_details(number, state, car, "OWNED", current_user_id)
    else:
        print("\n  MILIK SENDIRI: tidak ada")

    if rented:
        print("\n  KENDARAAN RENTAL")
        for car in rented:
            number += 1
            _print_vehicle_details(number, state, car, "RENTAL", current_user_id)
    else:
        print("\n  KENDARAAN RENTAL: tidak ada")
    return entries


def _print_vehicle_details(number: int, state: dict, car: dict,
                           category: str, current_user_id) -> None:
    quota = car.get("quota") if isinstance(car.get("quota"), dict) else {}
    owner_name = car.get("ownerName")
    owner_id = car.get("ownerId")
    if owner_name:
        owner = str(owner_name)
        if owner_id is not None and current_user_id is not None and str(owner_id) == str(current_user_id):
            owner += " (akun ini)"
    elif owner_id is not None and current_user_id is not None and str(owner_id) == str(current_user_id):
        owner = f"akun ini (User ID {owner_id})"
    elif owner_id is not None:
        owner = f"User ID {owner_id}"
    else:
        owner = "tidak dikirim API"

    access = vehicle_access_label(car)
    access_color = vehicle_access_color(car, access)

    print(f"\n  [{number}] {C_MAG}{car.get('name', 'Nama tidak dikirim API')}{C_RESET} [{category}]")
    print(f"      Plate / Car ID : {car.get('plate', '-')} / {car.get('id', '-')}")
    if category == "RENTAL":
        print(f"      Pemilik        : {owner}")
    print(f"      Akses          : {access_color}{access}{C_RESET}")
    print(f"      Quota          : {quota_display_for_vehicle(state, car, category)}")

    bonus = quota.get("bonus") or 0
    try:
        has_bonus = float(bonus) > 0
    except (TypeError, ValueError):
        has_bonus = False
    bonus_expiry = quota.get("bonusExpiresAt")
    if has_bonus and bonus_expiry:
        print(
            f"      Bonus berakhir : {fmt_datetime_ts(bonus_expiry)} "
            f"(sisa {fmt_remaining_ms(bonus_expiry)})"
        )

    shift = quota.get("shift", "-")
    print(f"      Shift aktif    : {shift}")

    shifts = car.get("shifts")
    if isinstance(shifts, dict) and shifts:
        for shift_name in ("AM", "PM"):
            for line in shift_summary_lines(state, car, shift_name, current_user_id):
                print(line)


def state_now_ms(state: dict):
    """Ambil waktu server dari state.now (detik atau milidetik Unix)."""
    if not isinstance(state, dict):
        return None
    raw = state.get("now")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).timestamp() * 1000
        except (TypeError, ValueError, OverflowError):
            return None
    if value >= 1_000_000_000_000:
        return value
    if value >= 1_000_000_000:
        return value * 1000
    return None


def game_datetime(state: dict):
    """Ubah timestamp API ke UTC, sesuai jam game yang ditampilkan website."""
    timestamp = state_now_ms(state)
    if timestamp is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return datetime.now(timezone.utc)


def live_server_now_ms(state: dict, captured_monotonic=None):
    """Interpolasi waktu server dari snapshot terakhir tanpa request API tiap detik."""
    base = state_now_ms(state)
    if base is None:
        return time.time() * 1000
    if captured_monotonic is None:
        return base
    elapsed = max(0.0, time.monotonic() - float(captured_monotonic))
    return base + elapsed * 1000


def extract_api_daily_earning(state: dict):
    """Cari field harian eksplisit bila server memang mengirimkannya."""
    containers = [state] if isinstance(state, dict) else []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = re.sub(r"[^a-z0-9]", "", str(key).lower())
                new_path = f"{path}.{key_norm}" if path else key_norm
                if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                    joined = new_path
                    has_day = "today" in joined or "daily" in joined
                    has_income = any(token in joined for token in ("earn", "earning", "income"))
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        number = None
                    if has_day and has_income and number is not None:
                        return max(0.0, number)
                found = walk(value, new_path)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found = walk(value, f"{path}.{index}")
                if found is not None:
                    return found
        return None

    for container in containers:
        found = walk(container)
        if found is not None:
            return found
    return None


def update_daily_income_tracker(account: dict, state: dict) -> bool:
    """Simpan pendapatan harian secara terpisah untuk setiap akun.

    Jika API tidak menyediakan statistik harian eksplisit, nilai dihitung dari
    kenaikan stats.usdtEarned sejak baseline pertama yang terlihat pada hari game.
    """
    stats = state.get("stats", {}) if isinstance(state, dict) else {}
    if not isinstance(stats, dict):
        stats = {}
    try:
        lifetime_total = float(stats.get("usdtEarned"))
    except (TypeError, ValueError):
        lifetime_total = None

    game_day = game_datetime(state).date().isoformat()
    api_daily = extract_api_daily_earning(state)
    previous = account.get("daily_income_tracker")
    if not isinstance(previous, dict):
        previous = {}

    if api_daily is not None:
        tracker = {
            "date": game_day,
            "value": api_daily,
            "source": "api",
            "last_total": lifetime_total,
        }
    elif lifetime_total is not None:
        if previous.get("date") != game_day or previous.get("source") != "tracked":
            # Baseline dimulai saat script pertama kali melihat akun pada hari game ini.
            tracker = {
                "date": game_day,
                "baseline_total": lifetime_total,
                "last_total": lifetime_total,
                "value": 0.0,
                "source": "tracked",
            }
        else:
            try:
                last_total = float(previous.get("last_total", lifetime_total))
                daily_value = float(previous.get("value", 0.0))
            except (TypeError, ValueError):
                last_total = lifetime_total
                daily_value = 0.0
            if lifetime_total >= last_total:
                daily_value = round(daily_value + (lifetime_total - last_total), 10)
            else:
                # Antisipasi reset/perubahan statistik kumulatif dari server.
                daily_value = 0.0
            tracker = {
                "date": game_day,
                "baseline_total": previous.get("baseline_total", lifetime_total),
                "last_total": lifetime_total,
                "value": daily_value,
                "source": "tracked",
            }
    else:
        return False

    if tracker != account.get("daily_income_tracker"):
        account["daily_income_tracker"] = tracker
        return True
    return False


def selected_account_daily_income(account: dict, state: dict):
    """Ambil pendapatan hari ini hanya dari akun yang sedang dipilih.

    Return (nilai, estimasi). Nilai None berarti tracker untuk tanggal game
    saat ini belum tersedia. Tracker 'tracked' adalah estimasi sejak baseline
    mulai diamati, bukan pendapatan penuh sejak awal hari.
    """
    if not isinstance(account, dict) or not isinstance(state, dict):
        return None, False

    game_day = game_datetime(state).date().isoformat()
    tracker = account.get("daily_income_tracker")
    if not isinstance(tracker, dict) or tracker.get("date") != game_day:
        return None, False

    try:
        value = max(0.0, float(tracker.get("value", 0.0)))
    except (TypeError, ValueError):
        return None, False

    return value, tracker.get("source") != "api"


def format_idr_integer(value) -> str:
    """Rupiah tanpa desimal, pemotongan ke bilangan bulat, pemisah ribuan titik."""
    try:
        number = int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return "--"
    return f"{number:,}".replace(",", ".")


def format_usdt_idr(value, rate):
    """Format USDT empat desimal dan nilai referensi IDR tanpa desimal."""
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    usdt_text = f"{amount:.4f} USDT"
    if rate is None:
        return f"{usdt_text} | Rp --"
    try:
        rupiah = int(amount * Decimal(str(rate)))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return f"{usdt_text} | Rp --"
    return f"{usdt_text} | Rp {format_idr_integer(rupiah)}"


def fetch_usdt_idr_rate(worker: dict):
    """Ambil referensi harga USDT/IDR dan cache 10 menit."""
    cache = worker.setdefault("fx_cache", {})
    now = time.monotonic()
    if cache.get("rate") and now - cache.get("fetched_monotonic", 0) < USDT_IDR_REFRESH:
        return cache.get("rate")
    try:
        response = requests.get(
            USDT_IDR_API,
            params={"quotes": "IDR"},
            timeout=6,
            headers={"accept": "application/json", "user-agent": "TheCryptoTaxiTerminal/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        rate = payload.get("quotes", {}).get("IDR", {}).get("price")
        rate = float(rate)
        if rate <= 0:
            raise ValueError("Harga USDT/IDR tidak valid")
        cache.update({
            "rate": rate,
            "fetched_monotonic": now,
            "last_updated": payload.get("last_updated"),
        })
        return rate
    except (requests.RequestException, ValueError, TypeError, KeyError):
        # Gunakan rate terakhir jika endpoint sedang tidak dapat diakses.
        return cache.get("rate")


def _summary_fetch_account(data: dict, account: dict):
    """Ambil state akun untuk ringkasan tanpa mengubah akun terpilih."""
    session = create_saved_session(data, account)
    try:
        response = session.post(API_STATE, json={}, timeout=8)
        response.raise_for_status()
        state = response.json()
        me = state.get("me", {}) if isinstance(state, dict) else {}
        expected_id = account.get("user_id")
        actual_id = me.get("id") if isinstance(me, dict) else None
        if expected_id is not None and actual_id is not None and str(expected_id) != str(actual_id):
            return "UNKNOWN", None, "User ID respons API tidak cocok dengan akun tersimpan."

        account["cookies"] = serialize_cookies(session)
        update_daily_income_tracker(account, state)
        return "VALID", state, None
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (401, 403):
            return "EXPIRED", None, f"HTTP {status_code}"
        return "UNKNOWN", None, f"HTTP {status_code or '?'}"
    except (requests.RequestException, ValueError, TypeError) as exc:
        return "UNKNOWN", None, str(exc)
    finally:
        session.close()


def refresh_main_summary_cache(data: dict, worker: dict) -> dict:
    """Cache state semua akun; worker aktif menyumbang snapshot tanpa request duplikat."""
    cache = worker.setdefault("summary_cache", {})
    accounts = get_accounts(data)
    snapshot = worker_snapshot(worker) if worker.get("thread") else {}
    active = worker_is_active(worker)
    active_account_id = snapshot.get("account_id") if active else None

    # Snapshot worker adalah state paling baru untuk akun yang sedang menjalankan loop.
    if snapshot.get("account_id") and isinstance(snapshot.get("state"), dict):
        cache[snapshot["account_id"]] = {
            "status": "VALID" if snapshot.get("session_status", "VALID") == "VALID" else snapshot.get("session_status", "UNKNOWN"),
            "state": snapshot.get("state"),
            "state_monotonic": snapshot.get("state_monotonic", time.monotonic()),
        }

    now = time.monotonic()
    missing_cache = any(account.get("id") not in cache for account in accounts)
    last_refresh = worker.get("summary_last_refresh", 0.0)
    should_refresh = missing_cache or now - last_refresh >= SUMMARY_API_REFRESH
    if should_refresh:
        changed = False
        for account in accounts:
            account_id = account.get("id")
            if active_account_id and account_id == active_account_id:
                continue
            status, state, error = _summary_fetch_account(data, account)
            cache[account_id] = {
                "status": status,
                "state": state,
                "error": error,
                "state_monotonic": time.monotonic() if state is not None else None,
            }
            if state is not None:
                changed = True
        worker["summary_last_refresh"] = time.monotonic()
        if changed:
            try:
                save_data(data)
            except RuntimeError:
                pass

    return cache


def vehicle_summary(state: dict, state_monotonic=None):
    """Ringkas kendaraan akun terpilih: berjalan, standby, tidak tersedia, countdown."""
    if not isinstance(state, dict):
        return None
    own, rented = vehicle_collections(state)
    vehicles = []
    seen = set()
    for car in own + rented:
        if not isinstance(car, dict):
            continue
        car_id = str(car.get("id", ""))
        if car_id and car_id in seen:
            continue
        if car_id:
            seen.add(car_id)
        vehicles.append(car)

    counts = {"running": 0, "standby": 0, "unavailable": 0}
    countdowns = []
    now_ms = live_server_now_ms(state, state_monotonic)
    for car in vehicles:
        trip = car.get("trip") if isinstance(car.get("trip"), dict) else None
        try:
            ends_at = float(trip.get("endsAt", 0)) if trip else 0
        except (TypeError, ValueError):
            ends_at = 0

        if trip and ends_at > now_ms:
            counts["running"] += 1
            remaining = max(0, int((ends_at - now_ms + 999) // 1000))
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            countdown = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
            name = str(car.get("name") or f"Mobil {car.get('id', '-')}")
            countdowns.append(f"{name} {countdown}")
        elif car.get("broken") or car.get("canDrive") is not True:
            counts["unavailable"] += 1
        else:
            counts["standby"] += 1

    return counts, countdowns


def check_saved_session(data: dict, saved: dict = None):
    """Kembalikan (status, session, state, pesan) untuk satu akun tersimpan."""
    saved = saved or get_selected_account(data)
    if not saved:
        return "NOT SAVED", None, None, "Belum ada akun tersimpan."

    session = create_saved_session(data, saved)
    try:
        state = get_state(session)
        # Simpan kembali cookie akun terkait jika server memperbarui sesi.
        save_session(data, saved.get("username", ""), session, state)
        return "READY", session, state, "Sesi valid."
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (401, 403):
            return "EXPIRED", session, None, "Sesi kedaluwarsa atau tidak diizinkan."
        return "UNKNOWN", session, None, f"HTTP error: {exc}"
    except (requests.RequestException, ValueError) as exc:
        return "UNKNOWN", session, None, f"Tidak dapat memeriksa sesi: {exc}"

def login_and_save(data: dict) -> bool:
    clear()
    banner()
    section("TAMBAHKAN AKUN BARU")
    username = input(f"  {C_DIM}│{C_RESET} Username : ").strip()
    password = getpass.getpass(f"  {C_DIM}│{C_RESET} Password : ").strip()
    section_end()

    if not username or not password:
        print(f"\n  {C_ERR}Username dan password wajib diisi.{C_RESET}")
        wait_for_main_menu()
        return False

    # Satu profil perangkat konsisten untuk instalasi ini; setiap akun
    # mempunyai cookie/session terpisah. Password tidak pernah disimpan.
    session = create_session(data["profile"])
    spinner("Menghubungi server...", 0.6)
    spinner("Login...", 0.5)

    if not login(session, username, password):
        wait_for_main_menu()
        return False

    try:
        state = get_state(session)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        print(f"  {C_ERR}Login berhasil, tetapi pemeriksaan akun gagal (HTTP {status_code}).{C_RESET}")
        wait_for_main_menu()
        return False
    except (requests.RequestException, ValueError) as exc:
        print(f"  {C_ERR}Gagal mengambil state akun: {exc}{C_RESET}")
        wait_for_main_menu()
        return False

    try:
        previous_ids = {item.get("id") for item in get_accounts(data)}
        save_session(data, username, session, state)
    except RuntimeError as exc:
        print(f"  {C_ERR}{exc}{C_RESET}")
        wait_for_main_menu()
        return False

    me = state.get("me", {})
    saved = get_selected_account(data)
    is_new = saved is not None and saved.get("id") not in previous_ids
    print(f"\n  {C_OK}{'Akun baru berhasil ditambahkan.' if is_new else 'Sesi akun berhasil diperbarui.'}{C_RESET}")
    print(f"  Username : {me.get('username') or username}")
    print(f"  User ID  : {me.get('id', '-')}")
    print(f"  Total akun tersimpan : {len(get_accounts(data))}")
    print(f"  File sesi: {DATA_FILE}")
    print(f"  {C_DIM}Password tidak disimpan. Cookie sesi disimpan terpisah per akun.{C_RESET}")
    wait_for_main_menu()
    return True

def print_trip_progress(trip: dict) -> None:
    """Tampilkan progres trip aktif dan estimasi waktu selesai."""
    if not isinstance(trip, dict):
        return

    try:
        now_ms = int(time.time() * 1000)
        started = float(trip.get("startedAt", now_ms))
        ends = float(trip.get("endsAt", now_ms))
        if ends <= now_ms:
            return

        duration = max(1.0, ends - started)
        done = max(0.0, min(now_ms - started, duration))
        fraction = done / duration
        width = 32
        filled = int(width * fraction)
        bar = "#" * filled + "-" * (width - filled)
        remaining = max(0, int((ends - now_ms + 999) // 1000))

        print(f"\n  TRIP #{trip.get('id', '-')}  [{bar}] {fraction * 100:5.1f}%")
        print(f"  Perkiraan selesai : {fmt_ts(ends)} | Sisa {remaining} detik")
        sys.stdout.flush()
    except (TypeError, ValueError, OverflowError):
        return


def print_account_dashboard(state: dict, status: str, running_car=None,
                            total_trip=0, total_earn=0.0, activity="-",
                            session_status="VALID", trip=None, vehicle_kind=None) -> None:
    me = state.get("me", {})
    balances = state.get("balances", {})
    stats = state.get("stats", {})

    section("ACCOUNT DASHBOARD")
    info("Username", me.get("username", "-"), C_MAG)
    info("User ID", me.get("id", "-"))
    info("Status", status, C_OK if status == "RUNNING" else C_BLUE)
    session_color = C_OK if session_status == "VALID" else C_ERR
    info("Session", session_status, session_color)
    info("Saldo", money(balances.get("usdt", 0)), C_OK)
    info("Total trip akun", stats.get("trips", 0), C_BLUE)
    info("Total earning akun", money(stats.get("usdtEarned", 0)), C_BLUE)
    info("Online", f"{state.get('online', '-')}/{state.get('registered', '-')}")

    if running_car:
        quota = running_car.get("quota", {})
        kind = vehicle_kind or running_car.get("_ct_source") or vehicle_type(state, running_car.get("id"))
        info("Jenis mobil", kind, C_MAG if kind == "RENTAL" else C_BLUE)
        info("Mobil", running_car.get("name", "-"), C_MAG)
        info("Plate", running_car.get("plate", "-"))
        info("Car ID", running_car.get("id", "-"))
        info("Quota", quota_display_for_vehicle(state, running_car, kind), C_WARN)
        info("Shift aktif", quota.get("shift", "-"), C_INFO)
        bonus = quota.get("bonus") or 0
        try:
            has_bonus = float(bonus) > 0
        except (TypeError, ValueError):
            has_bonus = False
        if has_bonus and quota.get("bonusExpiresAt"):
            expiry = quota.get("bonusExpiresAt")
            info("Bonus berakhir", f"{fmt_datetime_ts(expiry)} | sisa {fmt_remaining_ms(expiry)}", C_WARN)
        access = vehicle_access_label(running_car)
        access_color = vehicle_access_color(running_car, access)
        info("Akses", access, access_color)

    if status == "RUNNING":
        info("Trip sesi", total_trip)
        info("Earning sesi", money(total_earn), C_OK)
        info("Aktivitas", activity)
    section_end()

    if trip is None and running_car:
        trip = running_car.get("trip")
    if trip is None and isinstance(state, dict):
        own, rented = vehicle_collections(state)
        for car in own + rented:
            candidate = car.get("trip") if isinstance(car, dict) else None
            if isinstance(candidate, dict):
                try:
                    if float(candidate.get("endsAt", 0)) > time.time() * 1000:
                        trip = candidate
                        break
                except (TypeError, ValueError):
                    continue
    print_trip_progress(trip)

def print_worker_diagnostics(snapshot: dict) -> None:
    """Tampilkan alasan worker terakhir berhenti dan quota/bonus API mentah."""
    reason = snapshot.get("stop_reason") or snapshot.get("activity") or "Tidak ada alasan yang tercatat."
    print("\n  DIAGNOSTIK AUTO LOOP TERAKHIR")
    print(f"  Alasan berhenti : {reason}")

    quota_raw = snapshot.get("quota_raw")
    if not isinstance(quota_raw, dict):
        last_car = snapshot.get("car") or {}
        candidate_quota = last_car.get("quota") if isinstance(last_car, dict) else None
        quota_raw = candidate_quota if isinstance(candidate_quota, dict) else None

    print("  Nilai quota API:")
    if isinstance(quota_raw, dict):
        for field in ("used", "limit", "left", "bonus", "bonusExpiresAt", "shift"):
            if field in quota_raw:
                value = quota_raw[field]
                if field == "bonusExpiresAt" and value:
                    print(f"    {field:<15}: {value!r} ({fmt_datetime_ts(value)})")
                else:
                    print(f"    {field:<15}: {value!r}")
            else:
                print(f"    {field:<15}: <field tidak dikirim API>")
    else:
        print("    Data quota tidak tersedia pada respons API terakhir.")

def worker_is_active(worker: dict) -> bool:
    thread = worker.get("thread")
    status = worker.get("status") or {}
    return bool(
        thread and thread.is_alive()
        and (status.get("running") or status.get("finalizing"))
    )


def worker_snapshot(worker: dict) -> dict:
    lock = worker.get("lock")
    status = worker.get("status") or {}
    if lock:
        with lock:
            return dict(status)
    return dict(status)


def dashboard_loop(data: dict, worker: dict) -> None:
    """Tampilkan dashboard worker aktif atau akun terpilih yang tersimpan."""
    if not get_accounts(data):
        print(f"\n  {C_WARN}Belum ada akun tersimpan. Tambahkan akun terlebih dahulu.{C_RESET}")
        wait_for_main_menu()
        return

    try:
        while True:
            clear()
            banner()
            if worker_is_active(worker):
                snapshot = worker_snapshot(worker)
                if snapshot.get("run_mode") == "ALL":
                    print_all_loop_dashboard(snapshot)
                    print("\n  PILIHAN:")
                    print("  [Enter] Kembali ke menu utama, Auto Loop tetap RUNNING")
                    print("  [S]     Hentikan Auto Loop dan kembali ke menu utama")
                    sys.stdout.flush()
                    choice = read_auto_loop_choice(UI_REFRESH)
                    if choice == "return":
                        return
                    if choice == "stop":
                        stopped = stop_auto_worker(worker)
                        if stopped:
                            print(f"\n  {C_WARN}Auto Loop Semua Kendaraan dihentikan.{C_RESET}")
                        else:
                            print(f"\n  {C_ERR}Worker masih menyelesaikan permintaan aktif. Silakan coba lagi.{C_RESET}")
                        wait_for_main_menu()
                        return
                    continue
                state = snapshot.get("state")
                if state:
                    print_account_dashboard(
                        state,
                        "RUNNING",
                        running_car=snapshot.get("car"),
                        total_trip=snapshot.get("total_trip", 0),
                        total_earn=snapshot.get("total_earn", 0.0),
                        activity=snapshot.get("activity", "Auto Loop berjalan"),
                        session_status=snapshot.get("session_status", "VALID"),
                        trip=snapshot.get("trip"),
                        vehicle_kind=snapshot.get("vehicle_type"),
                    )
                else:
                    section("ACCOUNT DASHBOARD")
                    info("Username", snapshot.get("username", "-"), C_MAG)
                    info("Status", "RUNNING", C_OK)
                    info("Session", snapshot.get("session_status", "VALID"))
                    info("Aktivitas", snapshot.get("activity", "Auto Loop berjalan"))
                    section_end()
                print("\n  PILIHAN:")
                print("  [Enter] Kembali ke menu utama, Auto Loop tetap RUNNING")
                print("  [S]     Hentikan Auto Loop dan kembali ke menu utama")
                sys.stdout.flush()
                choice = read_auto_loop_choice(UI_REFRESH)
                if choice == "return":
                    return
                if choice == "stop":
                    stopped = stop_auto_worker(worker)
                    if stopped:
                        print(f"\n  {C_WARN}Auto Loop dihentikan. Kembali ke menu utama.{C_RESET}")
                    else:
                        print(f"\n  {C_ERR}Worker masih menyelesaikan permintaan aktif. Silakan coba lagi.{C_RESET}")
                    wait_for_main_menu()
                    return
                continue

            selected = get_selected_account(data)
            if selected is None:
                return
            status, _session, state, message = check_saved_session(data, selected)
            if status == "READY":
                set_selected_account(data, get_selected_account(data) or selected)
                print_account_dashboard(state, "READY")
                print(f"\n  {C_DIM}Dashboard diperbarui setiap {DASHBOARD_REFRESH} detik.{C_RESET}")
                print(f"  {C_DIM}Tekan Enter untuk kembali ke menu utama.{C_RESET}")
            else:
                section("ACCOUNT DASHBOARD")
                info("Username", selected.get("username", "-"))
                info("Status", status, C_ERR if status == "EXPIRED" else C_WARN)
                info("Keterangan", message)
                section_end()
                print(f"\n  {C_DIM}Tekan Enter untuk kembali ke menu utama.{C_RESET}")

            if status == "EXPIRED":
                wait_for_main_menu()
                return
            if wait_with_enter(DASHBOARD_REFRESH):
                return
    except KeyboardInterrupt:
        return

def choose_car(state: dict):
    own, rented = vehicle_collections(state)
    entries = [("OWNED", car) for car in own if isinstance(car, dict)]
    entries += [("RENTAL", car) for car in rented if isinstance(car, dict)]
    if not entries:
        print("\n  Tidak ada kendaraan pada myCars maupun rentedCars dari API.")
        wait_for_main_menu()
        return None

    clear()
    banner()
    print_vehicle_catalog(state)
    choice = input(
        f"\n  Pilih kendaraan [1-{len(entries)}] atau Enter untuk kembali: "
    ).strip()
    if not choice or choice == "0":
        return None
    try:
        index = int(choice) - 1
        if index < 0 or index >= len(entries):
            raise IndexError
    except (ValueError, IndexError):
        print(f"  {C_ERR}Pilihan kendaraan tidak valid.{C_RESET}")
        wait_for_main_menu()
        return None

    category, selected = entries[index]
    chosen = dict(selected)
    chosen["_ct_source"] = category
    return chosen

def start_trip_once(data: dict, account: dict, session: requests.Session, car: dict) -> None:
    category = car.get("_ct_source", "OWNED")
    if category == "RENTAL" and car.get("canDrive") is not True:
        print(f"\n  Kendaraan tidak dapat dijalankan: {vehicle_access_label(car)}")
        wait_for_main_menu()
        return

    print()
    spinner("Start trip...", 0.6)
    try:
        result = start_trip(session, car["id"])
        trip = result.get("trip") or result.get("car", {}).get("trip")
        if trip:
            print(
                f"  {C_OK}Trip #{trip.get('id', '-')} berhasil dimulai. "
                f"Selesai {fmt_ts(trip.get('endsAt'))}; "
                f"earning {money(trip.get('earning', 0))}.{C_RESET}"
            )
        else:
            block = (result.get("car") or {}).get("block") or result.get("block") or {}
            print(
                f"  {C_WARN}Tidak bisa start: {block.get('code', '-')} - "
                f"{block.get('msg', 'Tidak ada detail dari server')}{C_RESET}"
            )
        try:
            state = get_state(session)
            save_session(data, account.get("username", ""), session, state)
        except Exception:
            pass
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:160] if exc.response is not None else str(exc)
        print(f"  {C_ERR}HTTP {status_code}: {body}{C_RESET}")
    except requests.RequestException as exc:
        print(f"  {C_ERR}Permintaan gagal: {exc}{C_RESET}")
    except (KeyError, TypeError, ValueError) as exc:
        print(f"  {C_ERR}Respons server tidak sesuai format: {exc}{C_RESET}")

    input("\n  Tekan Enter untuk kembali ke menu utama...")

def read_auto_loop_choice(timeout: float):
    """None=lanjut monitor, 'return'=kembali tanpa stop, 'stop'=hentikan worker."""
    if not sys.stdin.isatty():
        time.sleep(max(0, timeout))
        return None

    deadline = time.monotonic() + max(0, timeout)
    if os.name == "nt":
        import msvcrt

        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\r", "\n"):
                    return "return"
                if char.lower() == "s":
                    return "stop"
                if char == "\x03":
                    raise KeyboardInterrupt
            time.sleep(0.05)
        return None

    import select

    remaining = max(0, deadline - time.monotonic())
    readable, _, _ = select.select([sys.stdin], [], [], remaining)
    if not readable:
        return None
    line = sys.stdin.readline()
    if line.strip().lower() in ("s", "stop"):
        return "stop"
    return "return"


def set_worker_status(status: dict, lock, **values) -> None:
    with lock:
        status.update(values)
        if isinstance(values.get("state"), dict):
            status["state_monotonic"] = time.monotonic()


def auto_loop_worker(data: dict, session: requests.Session, car: dict,
                     interval: int, stop_event: threading.Event,
                     status: dict, lock, stop_on_unavailable: bool = False,
                     manage_running_state: bool = True,
                     worker_context: dict = None) -> None:
    """Worker Auto Loop; rental hanya dijalankan saat API menyatakan canDrive=True.

    Parameter tambahan dipakai hanya oleh Auto Loop Semua Kendaraan agar satu
    kendaraan yang tidak lagi tersedia dapat dilewati tanpa mengubah perilaku
    Auto Loop Pilih Kendaraan.
    """
    username = status.get("username", "-")
    iteration = 0
    try:
        while not stop_event.is_set():
            iteration += 1
            try:
                state = get_state(session)
                if stop_event.is_set():
                    break
                saved_account = find_account(data, status.get("account_id"))
                if saved_account is not None:
                    update_daily_income_tracker(saved_account, state)
                save_session(data, username, session, state)
                current_car = find_car(state, car["id"], preferred_type=car.get("_ct_source"))
                current_kind = (current_car or {}).get("_ct_source") or vehicle_type(state, car["id"])
                if current_car:
                    raw_quota = current_car.get("quota")
                    set_worker_status(
                        status, lock,
                        state=state,
                        car=current_car,
                        vehicle_type=current_kind,
                        quota_raw=dict(raw_quota) if isinstance(raw_quota, dict) else raw_quota,
                    )

                if not current_car:
                    set_worker_status(
                        status, lock, state=state, car=car, trip=None,
                        iteration=iteration,
                        activity="Mobil tidak ditemukan pada state akun",
                        stop_reason=("Kendaraan tidak ditemukan pada state API" if stop_on_unavailable else None),
                    )
                    if stop_on_unavailable:
                        break
                    stop_event.wait(interval)
                    continue

                if current_car.get("broken"):
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        iteration=iteration,
                        activity="Mobil rusak; Auto Loop dihentikan",
                        stop_reason="Mobil ditandai rusak oleh API (broken=True)",
                    )
                    break

                quota = current_car.get("quota", {})
                current_trip = current_car.get("trip")
                now_ms = int(time.time() * 1000)

                if current_trip and current_trip.get("endsAt", 0) > now_ms:
                    set_worker_status(
                        status, lock, state=state, car=current_car,
                        vehicle_type=current_kind,
                        trip=current_trip, iteration=iteration,
                        activity="Menunggu trip selesai",
                    )
                    remaining = (current_trip["endsAt"] - now_ms) / 1000
                    stop_event.wait(min(remaining + 0.5, 2))
                    continue

                bonus_available = bonus_is_available(quota, now_ms)
                if quota.get("left", 0) <= 0 and not bonus_available:
                    raw_used = quota.get("used", "<tidak dikirim>")
                    raw_limit = quota.get("limit", "<tidak dikirim>")
                    raw_left = quota.get("left", "<field left tidak dikirim API>")
                    raw_bonus = quota.get("bonus", "<field bonus tidak dikirim API>")
                    quota_reason = (
                        "Quota dasar habis dan bonus tidak tersedia/kedaluwarsa; "
                        f"nilai API mentah: used={raw_used!r}, limit={raw_limit!r}, "
                        f"left={raw_left!r}, bonus={raw_bonus!r}"
                    )
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        vehicle_type=current_kind,
                        iteration=iteration,
                        activity=(
                            f"Quota dan bonus habis ({raw_used}/{raw_limit}; "
                            f"left={raw_left}; bonus={raw_bonus})"
                        ),
                        stop_reason=quota_reason,
                        quota_raw=dict(quota) if isinstance(quota, dict) else quota,
                    )
                    break

                # Mode semua kendaraan melewati mobil yang kehilangan akses API,
                # lalu beralih ke kendaraan berikutnya. Mode pilihan tetap sama.
                if stop_on_unavailable and current_car.get("canDrive") is not True:
                    block = current_car.get("block") if isinstance(current_car.get("block"), dict) else {}
                    reason = block.get("msg") or block.get("code") or "API tidak mengizinkan kendaraan"
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        vehicle_type=current_kind, iteration=iteration,
                        activity=f"Kendaraan dilewati: {reason}",
                        stop_reason=f"Kendaraan tidak lagi siap: {reason}",
                    )
                    break

                # Rental hanya dapat dijalankan jika API secara eksplisit mengizinkan.
                # Tidak mencoba melewati shift, kontrak, atau block server.
                if current_kind == "RENTAL" and current_car.get("canDrive") is not True:
                    block = current_car.get("block") if isinstance(current_car.get("block"), dict) else {}
                    reason = (
                        f"{block.get('code', 'BLOCKED')} - {block.get('msg', 'canDrive belum true')}"
                        if block else "API belum menyatakan canDrive=true"
                    )
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        vehicle_type=current_kind,
                        iteration=iteration,
                        activity=f"Rental belum tersedia: {reason}",
                        quota_raw=dict(quota) if isinstance(quota, dict) else quota,
                    )
                    stop_event.wait(interval)
                    continue

                if not current_car.get("canDrive") and current_car.get("block"):
                    block = current_car["block"]
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        vehicle_type=current_kind,
                        iteration=iteration,
                        activity=f"Terblokir: {block.get('code', '-')} - {block.get('msg', '-')}",
                    )
                    stop_event.wait(interval)
                    continue

                if stop_event.is_set():
                    break
                set_worker_status(
                    status, lock, state=state, car=current_car, trip=None,
                    vehicle_type=current_kind,
                    iteration=iteration,
                    activity=f"Memulai trip {current_car.get('name', '-')}",
                )
                result = start_trip(session, car["id"])
                new_trip = result.get("trip") or result.get("car", {}).get("trip")

                if new_trip:
                    earning = float(new_trip.get("earning") or 0)
                    with lock:
                        status["total_earn"] = float(status.get("total_earn", 0.0)) + earning
                        status["total_trip"] = int(status.get("total_trip", 0)) + 1
                        status["state"] = state
                        status["car"] = current_car
                        status["vehicle_type"] = current_kind
                        status["trip"] = new_trip
                        status["iteration"] = iteration
                        status["activity"] = (
                            f"Trip #{new_trip.get('id', '-')} dimulai; earning {money(earning)}"
                        )
                    stop_event.wait(interval)
                else:
                    block = (result.get("car") or {}).get("block") or result.get("block") or {}
                    set_worker_status(
                        status, lock, state=state, car=current_car, trip=None,
                        vehicle_type=current_kind,
                        iteration=iteration,
                        activity=f"Start gagal: {block.get('code', '-')} - {block.get('msg', '-')}",
                    )
                    if not stop_event.wait(interval):
                        stop_event.wait(interval)

            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                body = exc.response.text[:160] if exc.response is not None else str(exc)
                if status_code in (401, 403):
                    set_worker_status(
                        status, lock, session_status="EXPIRED",
                        activity=f"Sesi EXPIRED (HTTP {status_code})",
                        stop_reason=f"Sesi ditolak API (HTTP {status_code})",
                    )
                    break
                set_worker_status(status, lock, activity=f"HTTP {status_code}: {body}")
                if not stop_event.wait(interval * 2):
                    stop_event.wait(interval)
            except requests.RequestException as exc:
                set_worker_status(status, lock, activity=f"Koneksi gagal: {exc}")
                if not stop_event.wait(interval * 2):
                    stop_event.wait(interval)
            except (KeyError, TypeError, ValueError) as exc:
                set_worker_status(status, lock, activity=f"Data/API tidak sesuai format: {exc}")
                if not stop_event.wait(interval * 2):
                    stop_event.wait(interval)
    except Exception as exc:
        set_worker_status(
            status, lock,
            activity=f"Worker error: {exc}",
            stop_reason=f"Worker berhenti karena exception: {type(exc).__name__}: {exc}",
        )
    finally:
        completion_snapshot = None
        with lock:
            if stop_event.is_set():
                status["activity"] = "Auto Loop dihentikan oleh user"
                status["stop_reason"] = "Dihentikan oleh user (stop event)"
            if manage_running_state:
                if not status.get("stop_reason"):
                    status["stop_reason"] = status.get(
                        "activity", "Worker berhenti tanpa alasan tercatat"
                    )
                status["running"] = False
                normal_completion = (
                    not stop_event.is_set()
                    and status.get("session_status") != "EXPIRED"
                    and str(status.get("stop_reason") or "").startswith(
                        "Quota dasar habis dan bonus tidak tersedia/kedaluwarsa"
                    )
                )
                if normal_completion and worker_context is not None:
                    status["finalizing"] = True
                    completion_snapshot = dict(status)

        if completion_snapshot is not None:
            try:
                telegram_publish_loop_completion(
                    data, worker_context, completion_snapshot, mode="PICK"
                )
            except Exception as exc:
                worker_context["telegram_last_error"] = (
                    f"Penyelesaian notifikasi Telegram gagal: {type(exc).__name__}: {exc}"
                )
            finally:
                with lock:
                    status["finalizing"] = False

def worker_is_alive(worker: dict) -> bool:
    thread = worker.get("thread")
    return bool(thread and thread.is_alive())


def start_auto_loop_worker(data: dict, account: dict, session: requests.Session,
                           car: dict, worker: dict,
                           interval: int = DEFAULT_INTERVAL) -> bool:
    """Mulai satu worker Auto Loop bersama, dipakai terminal dan Telegram."""
    start_lock = worker.get("start_lock")
    if start_lock is None:
        start_lock = threading.Lock()
        worker["start_lock"] = start_lock

    with start_lock:
        if worker_is_active(worker):
            return False

        stop_event = threading.Event()
        lock = threading.RLock()
        status = {
            "running": True,
            "run_mode": "PICK",
            "account_id": account.get("id"),
            "username": account.get("username", "-"),
            "state": None,
            "car": dict(car),
            "vehicle_type": car.get("_ct_source", "OWNED"),
            "trip": None,
            "iteration": 0,
            "total_trip": 0,
            "total_earn": 0.0,
            "activity": "Memulai Auto Loop",
            "session_status": "VALID",
            "stop_reason": None,
            "quota_raw": None,
        }
        thread = threading.Thread(
            target=auto_loop_worker,
            args=(data, session, dict(car), interval, stop_event, status, lock, False, True, worker),
            name="CryptoTaxiAutoLoop",
            daemon=True,
        )
        worker.update({
            "thread": thread,
            "stop_event": stop_event,
            "status": status,
            "lock": lock,
        })
        thread.start()
        return True


def start_auto_loop_all_worker(data: dict, account: dict, session: requests.Session,
                               state: dict, groups: dict, worker: dict,
                               interval: int = DEFAULT_INTERVAL) -> bool:
    """Mulai satu orchestrator OWNED lalu RENTAL, tanpa worker paralel per mobil."""
    start_lock = worker.get("start_lock")
    if start_lock is None:
        start_lock = threading.Lock()
        worker["start_lock"] = start_lock

    with start_lock:
        if worker_is_active(worker):
            return False

        vehicles = {
            category: [dict(car) for car in groups.get(category, [])]
            for category in ("OWNED", "RENTAL")
        }
        totals = {category: len(vehicles[category]) for category in vehicles}
        stop_event = threading.Event()
        lock = threading.RLock()
        status = {
            "running": True,
            "run_mode": "ALL",
            "account_id": account.get("id"),
            "username": account.get("username", "-"),
            "state": state,
            "car": None,
            "vehicle_type": None,
            "trip": None,
            "iteration": 0,
            "total_trip": 0,
            "total_earn": 0.0,
            "activity": "Memulai pemeriksaan kendaraan",
            "session_status": "VALID",
            "stop_reason": None,
            "quota_raw": None,
            "stage": "PERSIAPAN",
            "stage_vehicle_index": 0,
            "stage_vehicle_total": 0,
            "all_totals": totals,
            "all_done": {"OWNED": 0, "RENTAL": 0},
            "all_skipped": {"OWNED": 0, "RENTAL": 0},
        }
        thread = threading.Thread(
            target=auto_loop_all_worker,
            args=(data, account, session, vehicles, interval, stop_event, status, lock, worker),
            name="CryptoTaxiAutoLoopAll",
            daemon=True,
        )
        worker.update({
            "thread": thread,
            "stop_event": stop_event,
            "status": status,
            "lock": lock,
        })
        thread.start()
        return True


def auto_loop_all_worker(data: dict, account: dict, session: requests.Session,
                         vehicles: dict, interval: int,
                         stop_event: threading.Event, status: dict, lock,
                         worker_context: dict = None) -> None:
    """Proses OWNED lalu RENTAL secara dinamis sampai pemindaian akhir kosong."""
    username = account.get("username", "-")
    account_id = account.get("id")
    completed = {"OWNED": 0, "RENTAL": 0}
    skipped = {"OWNED": 0, "RENTAL": 0}
    skipped_keys = set()
    totals = {"OWNED": 0, "RENTAL": 0}
    processed = set()
    seen_keys = {(kind, str(car.get("id"))) for kind in ("OWNED", "RENTAL")
                 for car in vehicles.get(kind, []) if car.get("id") not in (None, "")}
    attempts = {}
    fatal_error = None
    final_ready = None

    try:
        # Kendaraan awal tetap dipakai sebagai antrean pertama; setelah itu setiap
        # putaran mengambil state API baru sehingga kendaraan READY yang muncul belakangan ikut antre.
        pending = {kind: [dict(c) for c in vehicles.get(kind, [])] for kind in ("OWNED", "RENTAL")}
        while not stop_event.is_set():
            for category in ("OWNED", "RENTAL"):
                if stop_event.is_set() or fatal_error:
                    break
                while pending[category] and not stop_event.is_set():
                    selected_car = pending[category].pop(0)
                    car_id = selected_car.get("id")
                    key = (category, str(car_id))
                    if key in processed:
                        continue
                    attempts[key] = attempts.get(key, 0) + 1
                    set_worker_status(
                        status, lock, stage=category,
                        stage_vehicle_index=completed[category] + skipped[category] + 1,
                        stage_vehicle_total=max(totals[category], completed[category] + skipped[category] + 1),
                        activity=f"Memeriksa ulang {selected_car.get('name', 'kendaraan')}...",
                        stop_reason=None,
                    )
                    try:
                        fresh_state = get_state(session)
                        me = fresh_state.get("me", {}) if isinstance(fresh_state, dict) else {}
                        expected_id = account.get("user_id")
                        actual_id = me.get("id") if isinstance(me, dict) else None
                        if expected_id is not None and actual_id is not None and str(expected_id) != str(actual_id):
                            raise RuntimeError("User ID respons API tidak cocok dengan akun terpilih.")
                        if expected_id is None:
                            expected_username = str(username or "").strip()
                            actual_username = str(me.get("username") or "").strip() if isinstance(me, dict) else ""
                            if expected_username and actual_username and expected_username.casefold() != actual_username.casefold():
                                raise RuntimeError("Username respons API tidak cocok dengan akun terpilih.")
                        saved_account = find_account(data, account_id)
                        if saved_account is not None:
                            update_daily_income_tracker(saved_account, fresh_state)
                        save_session(data, username, session, fresh_state)
                    except requests.HTTPError as exc:
                        code = exc.response.status_code if exc.response is not None else None
                        if code in (401, 403):
                            set_worker_status(status, lock, session_status="EXPIRED", activity=f"Sesi EXPIRED (HTTP {code})", stop_reason=f"Sesi ditolak API (HTTP {code})")
                        else:
                            set_worker_status(status, lock, activity=f"Gagal memeriksa kendaraan (HTTP {code or '?'})", stop_reason=f"Pemeriksaan API gagal (HTTP {code or '?'})")
                        fatal_error = status.get("stop_reason")
                        break

                    current_car = find_car(fresh_state, car_id, preferred_type=category)
                    if not current_car or current_car.get("_ct_source") != category or not vehicle_ready_for_telegram(fresh_state, current_car):
                        skipped_keys.add(key)
                        skipped[category] = sum(1 for item in skipped_keys if item[0] == category)
                        set_worker_status(status, lock, state=fresh_state, car=current_car or selected_car,
                                          vehicle_type=category, all_done=dict(completed), all_skipped=dict(skipped),
                                          activity=f"Dilewati: {selected_car.get('name', 'kendaraan')} tidak lagi READY", stop_reason=None)
                        continue

                    current_car = dict(current_car)
                    current_car["_ct_source"] = category
                    before_trips = int(worker_snapshot({"status": status, "lock": lock}).get("total_trip") or 0)
                    set_worker_status(status, lock, running=True, state=fresh_state, car=current_car,
                                      vehicle_type=category, trip=None, stage=category,
                                      activity=f"Menjalankan {current_car.get('name', 'kendaraan')}", stop_reason=None,
                                      quota_raw=current_car.get("quota") if isinstance(current_car.get("quota"), dict) else None)
                    auto_loop_worker(data, session, current_car, interval, stop_event, status, lock,
                                     stop_on_unavailable=True, manage_running_state=False)
                    if stop_event.is_set():
                        break
                    snap = worker_snapshot({"status": status, "lock": lock})
                    reason = str(snap.get("stop_reason") or "")
                    if snap.get("session_status") == "EXPIRED" or reason.startswith("Worker berhenti karena exception:") or "Pemeriksaan API gagal" in reason or "Sesi ditolak API" in reason:
                        fatal_error = reason or "Sesi akun tidak dapat digunakan."
                        break
                    if reason.startswith("Quota dasar habis dan bonus tidak tersedia/kedaluwarsa"):
                        completed[category] += 1
                        processed.add(key)
                        skipped_keys.discard(key)
                        skipped[category] = sum(1 for item in skipped_keys if item[0] == category)
                        set_worker_status(status, lock, all_done=dict(completed), all_skipped=dict(skipped),
                                          trip=None, stop_reason=None,
                                          activity=f"Selesai menjalankan {current_car.get('name', 'kendaraan')}")
                    else:
                        # Jangan tandai selesai jika kendaraan belum menghabiskan quota/bonus.
                        # Akan diperiksa ulang; jika API tetap mengklaim READY berulang kali,
                        # hentikan sebagai ERROR, bukan mengirim laporan sukses palsu.
                        if attempts[key] >= 3:
                            fatal_error = f"Kendaraan {current_car.get('name', car_id)} masih READY tetapi gagal diselesaikan: {reason or 'status API tidak berubah'}."
                            break
                        skipped_keys.add(key)
                        skipped[category] = sum(1 for item in skipped_keys if item[0] == category)
                        pending[category].append(dict(current_car))
                    if fatal_error:
                        break
                if fatal_error:
                    break

            if fatal_error or stop_event.is_set():
                break

            # Pemindaian segar: tambahkan kendaraan baru yang READY, urut OWNED lalu RENTAL.
            try:
                final_state = get_state(session)
                fresh_groups = collect_ready_vehicle_groups(final_state)
                final_ready = sum(len(fresh_groups[k]) for k in ("OWNED", "RENTAL"))
                for category in ("OWNED", "RENTAL"):
                    for car in fresh_groups[category]:
                        key = (category, str(car.get("id")))
                        seen_keys.add(key)
                        if key not in processed and not any(str(x.get("id")) == str(car.get("id")) for x in pending[category]):
                            pending[category].append(dict(car))
                    totals[category] = sum(1 for item in seen_keys if item[0] == category)
                save_session(data, username, session, final_state)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                fatal_error = f"Sesi ditolak API (HTTP {code})" if code in (401, 403) else f"Pemeriksaan API gagal (HTTP {code or '?'})"
                if code in (401, 403):
                    set_worker_status(status, lock, session_status="EXPIRED")
                break
            if final_ready == 0:
                break
            # Antrean tidak boleh berhenti hanya karena snapshot awal sudah habis.
            if not pending["OWNED"] and not pending["RENTAL"] and final_ready:
                fatal_error = f"Masih ada {final_ready} kendaraan READY yang belum dapat dimasukkan ke antrean."
                break

        if fatal_error:
            set_worker_status(status, lock, activity=fatal_error, stop_reason=fatal_error, stage="ERROR")
        elif stop_event.is_set():
            set_worker_status(status, lock, activity="Auto Loop Semua Kendaraan dihentikan oleh user", stop_reason="Dihentikan oleh user (stop event)")
        else:
            set_worker_status(status, lock, stage="SELESAI", activity="Tidak ada kendaraan READY tersisa", stop_reason="Semua kendaraan READY selesai dijalankan")
    except Exception as exc:
        fatal_error = f"Worker berhenti karena exception: {type(exc).__name__}: {exc}"
        set_worker_status(status, lock, activity=fatal_error, stop_reason=fatal_error, stage="ERROR")
    finally:
        completion_snapshot = None
        with lock:
            status["all_totals"] = dict(totals)
            status["all_done"] = dict(completed)
            status["all_skipped"] = dict(skipped)
            status["final_ready"] = final_ready
            if stop_event.is_set():
                status["activity"] = "Auto Loop Semua Kendaraan dihentikan oleh user"
                status["stop_reason"] = "Dihentikan oleh user (stop event)"
            status["running"] = False
            normal_completion = (not stop_event.is_set() and fatal_error is None
                                 and status.get("stage") == "SELESAI"
                                 and final_ready == 0)
            if normal_completion and worker_context is not None:
                status["finalizing"] = True
                completion_snapshot = dict(status)
        if completion_snapshot is not None:
            try:
                telegram_publish_loop_completion(data, worker_context, completion_snapshot, mode="ALL")
            except Exception as exc:
                worker_context["telegram_last_error"] = f"Penyelesaian notifikasi Telegram gagal: {type(exc).__name__}: {exc}"
            finally:
                with lock:
                    status["finalizing"] = False

def print_all_loop_dashboard(snapshot: dict) -> None:
    """Tampilan ringkas progres Auto Loop Semua Kendaraan."""
    clear()
    banner()
    section("AUTO LOOP SEMUA KENDARAAN")
    info("Akun", snapshot.get("username", "-"), C_MAG)
    info("Tahap", snapshot.get("stage", "PERSIAPAN"), C_BLUE)
    index = snapshot.get("stage_vehicle_index", 0)
    total = snapshot.get("stage_vehicle_total", 0)
    if total:
        info("Kendaraan", f"{index}/{total}")
    elif snapshot.get("stage") == "SELESAI":
        info("Kendaraan", "Semua selesai")
    else:
        info("Kendaraan", "Tidak ada yang siap")

    car = snapshot.get("car")
    state = snapshot.get("state")
    if isinstance(car, dict):
        print(f"\n  {car.get('name', 'Nama kendaraan tidak tersedia')}")
        category = snapshot.get("vehicle_type") or car.get("_ct_source", "OWNED")
        if isinstance(state, dict):
            info("Quota", quota_display_for_vehicle(state, car, category), C_WARN)
        else:
            info("Quota", quota_display(car.get("quota", {})), C_WARN)
    display_status = "RUNNING" if snapshot.get("running") else (
        "DIHENTIKAN" if str(snapshot.get("stop_reason", "")).startswith("Dihentikan")
        else "SELESAI" if snapshot.get("stage") == "SELESAI" else "BERHENTI"
    )
    info("Status", display_status, C_OK if display_status == "RUNNING" else C_BLUE)
    info("Aktivitas", snapshot.get("activity", "-"))
    section_end()

    totals = snapshot.get("all_totals") or {"OWNED": 0, "RENTAL": 0}
    done = snapshot.get("all_done") or {"OWNED": 0, "RENTAL": 0}
    skipped = snapshot.get("all_skipped") or {"OWNED": 0, "RENTAL": 0}
    print("\n  PROGRES KESELURUHAN")
    for category in ("OWNED", "RENTAL"):
        total_count = int(totals.get(category, 0))
        done_count = int(done.get(category, 0))
        skipped_count = int(skipped.get(category, 0))
        if total_count == 0:
            value = "TIDAK ADA"
        elif done_count >= total_count:
            value = "SELESAI"
        else:
            value = f"{done_count}/{total_count} kendaraan"
        if skipped_count:
            value += f" ({skipped_count} dilewati)"
        print(f"  {category:<6}: {value}")


def stop_auto_worker(worker: dict, timeout: float = 45.0) -> bool:
    """Hentikan worker aktif. True jika worker sudah benar-benar berhenti."""
    stop_event = worker.get("stop_event")
    thread = worker.get("thread")
    if not thread:
        return True
    if stop_event:
        stop_event.set()
    if thread.is_alive():
        thread.join(timeout=timeout)
    return not thread.is_alive()


def render_worker_dashboard(worker: dict) -> None:
    snapshot = worker_snapshot(worker)
    if snapshot.get("run_mode") == "ALL":
        print_all_loop_dashboard(snapshot)
        print("\n  PILIHAN:")
        print("  [Enter] Kembali ke menu utama, Auto Loop tetap RUNNING")
        print("  [S]     Hentikan Auto Loop dan kembali ke menu utama")
        sys.stdout.flush()
        return
    clear()
    banner()
    state = snapshot.get("state")
    session_status = snapshot.get("session_status", "VALID")
    display_status = "RUNNING" if snapshot.get("running") else (
        "EXPIRED" if session_status == "EXPIRED" else "READY"
    )
    if state:
        print_account_dashboard(
            state,
            display_status,
            running_car=snapshot.get("car"),
            total_trip=snapshot.get("total_trip", 0),
            total_earn=snapshot.get("total_earn", 0.0),
            activity=snapshot.get("activity", "Memulai Auto Loop"),
            session_status=session_status,
            trip=snapshot.get("trip"),
            vehicle_kind=snapshot.get("vehicle_type"),
        )
    else:
        section("ACCOUNT DASHBOARD")
        info("Username", snapshot.get("username", "-"), C_MAG)
        info("Status", display_status, C_OK if display_status == "RUNNING" else C_BLUE)
        info("Session", session_status)
        info("Aktivitas", snapshot.get("activity", "Memulai Auto Loop"))
        section_end()

    print("\n  PILIHAN:")
    print("  [Enter] Kembali ke menu utama, Auto Loop tetap RUNNING")
    print("  [S]     Hentikan Auto Loop dan kembali ke menu utama")
    sys.stdout.flush()


def auto_loop(data: dict, account: dict, session: requests.Session, car: dict,
              worker: dict, interval: int = DEFAULT_INTERVAL) -> None:
    """Jalankan worker; Enter kembali ke menu tanpa menghentikan loop."""
    if not start_auto_loop_worker(data, account, session, car, worker, interval):
        print(f"\n  {C_WARN}Auto Loop akun ini sudah berjalan.{C_RESET}")
        wait_for_main_menu()
        return

    choice = None
    try:
        while worker_is_alive(worker) and worker_snapshot(worker).get("running"):
            render_worker_dashboard(worker)
            choice = read_auto_loop_choice(UI_REFRESH)
            if choice == "return":
                print(f"\n  {C_OK}Kembali ke menu utama. Auto Loop tetap berjalan.{C_RESET}")
                return
            if choice == "stop":
                stopped = stop_auto_worker(worker)
                if stopped:
                    print(f"\n  {C_WARN}Auto Loop dihentikan. Kembali ke menu utama.{C_RESET}")
                else:
                    print(f"\n  {C_ERR}Worker masih menyelesaikan permintaan aktif. Coba hentikan lagi dari menu utama.{C_RESET}")
                return
    except KeyboardInterrupt:
        stop_auto_worker(worker)
        print(f"\n  {C_WARN}Auto Loop dihentikan melalui Ctrl+C.{C_RESET}")
        return

    snapshot = worker_snapshot(worker)
    clear()
    banner()
    print_account_dashboard(
        snapshot.get("state") or {},
        "EXPIRED" if snapshot.get("session_status") == "EXPIRED" else "READY",
        running_car=snapshot.get("car"),
        total_trip=snapshot.get("total_trip", 0),
        total_earn=snapshot.get("total_earn", 0.0),
        activity=snapshot.get("activity", "Auto Loop selesai"),
        session_status=snapshot.get("session_status", "VALID"),
        vehicle_kind=snapshot.get("vehicle_type"),
    )
    wait_for_main_menu()


def auto_loop_all(data: dict, account: dict, session: requests.Session,
                  state: dict, worker: dict) -> None:
    """Periksa OWNED dan RENTAL, lalu jalankan seluruh kendaraan siap berurutan."""
    fresh_state = get_state(session)
    me = fresh_state.get("me", {}) if isinstance(fresh_state, dict) else {}
    expected_id = account.get("user_id")
    actual_id = me.get("id") if isinstance(me, dict) else None
    if expected_id is not None and actual_id is not None and str(expected_id) != str(actual_id):
        print(f"\n  {C_ERR}User ID API tidak cocok dengan akun terpilih.{C_RESET}")
        wait_for_main_menu()
        return
    save_session(data, account.get("username", ""), session, fresh_state)
    groups = collect_ready_vehicle_groups(fresh_state)
    total_owned = len(groups["OWNED"])
    total_rental = len(groups["RENTAL"])

    clear()
    banner()
    section("PEMERIKSAAN KENDARAAN")
    info("Akun", me.get("username", account.get("username", "-")), C_MAG)
    info("OWNED siap", total_owned, C_OK if total_owned else C_WARN)
    info("RENTAL siap", total_rental, C_OK if total_rental else C_WARN)
    section_end()

    if total_owned + total_rental == 0:
        print(f"\n  {C_WARN}Tidak ada kendaraan OWNED maupun RENTAL yang siap digunakan.{C_RESET}")
        wait_for_main_menu()
        return

    print("\n  URUTAN MENJALANKAN:")
    print("  1. Semua kendaraan OWNED")
    print("  2. Semua kendaraan RENTAL")
    print(f"\n  Interval pemeriksaan Auto Loop: {DEFAULT_INTERVAL} detik")
    print(f"  {C_OK}Memulai Auto Loop Semua Kendaraan...{C_RESET}")

    if not start_auto_loop_all_worker(
        data, account, session, fresh_state, groups, worker, DEFAULT_INTERVAL
    ):
        print(f"\n  {C_WARN}Auto Loop lain masih berjalan.{C_RESET}")
        wait_for_main_menu()
        return

    try:
        while worker_is_alive(worker) and worker_snapshot(worker).get("running"):
            render_worker_dashboard(worker)
            choice = read_auto_loop_choice(UI_REFRESH)
            if choice == "return":
                print(f"\n  {C_OK}Kembali ke menu utama. Auto Loop Semua Kendaraan tetap berjalan.{C_RESET}")
                return
            if choice == "stop":
                stopped = stop_auto_worker(worker)
                if stopped:
                    print(f"\n  {C_WARN}Auto Loop Semua Kendaraan dihentikan.{C_RESET}")
                else:
                    print(f"\n  {C_ERR}Worker masih menyelesaikan permintaan aktif. Coba hentikan lagi.{C_RESET}")
                return
    except KeyboardInterrupt:
        stop_auto_worker(worker)
        print(f"\n  {C_WARN}Auto Loop Semua Kendaraan dihentikan melalui Ctrl+C.{C_RESET}")
        return

    snapshot = worker_snapshot(worker)
    print_all_loop_dashboard(snapshot)
    print(f"\n  Total trip sesi : {snapshot.get('total_trip', 0)}")
    print(f"  Total earning   : {money(snapshot.get('total_earn', 0.0))}")
    wait_for_main_menu()


def choose_saved_account(data: dict):
    accounts = get_accounts(data)
    if not accounts:
        print(f"\n  {C_WARN}Belum ada akun tersimpan. Tambahkan akun terlebih dahulu.{C_RESET}")
        wait_for_main_menu()
        return None

    section("PILIH AKUN TERSIMPAN")
    for index, account in enumerate(accounts, 1):
        selected_mark = "  [TERPILIH]" if account.get("id") == data.get("active_account_id") else ""
        print(
            f"  {C_DIM}│{C_RESET} [{index}] {C_MAG}{account.get('username', '-')}{C_RESET} "
            f"| User ID {account.get('user_id', '-')}"
            f"{selected_mark}"
        )
    section_end()

    raw_choice = input(
        f"\n  Pilih akun [1-{len(accounts)}] atau Enter untuk kembali: "
    ).strip()
    if not raw_choice:
        return None
    try:
        index = int(raw_choice) - 1
        if index < 0 or index >= len(accounts):
            raise IndexError
    except (ValueError, IndexError):
        print(f"  {C_ERR}Pilihan akun tidak valid.{C_RESET}")
        wait_for_main_menu()
        return None

    account = accounts[index]
    set_selected_account(data, account)
    return account


def run_vehicle_for_account(data: dict, account: dict, session: requests.Session,
                            state: dict, worker: dict) -> None:
    """Tampilkan mode terlebih dahulu; pilihan 1/2 baru meminta kendaraan."""
    clear()
    banner()
    section("PILIH MODE KENDARAAN")
    info("Akun", account.get("username", "-"), C_MAG)
    print("  [1] Start Trip Sekali")
    print("  [2] Auto Loop Pilih Kendaraan")
    print("  [3] Auto Loop Semua Kendaraan")
    section_end()

    mode = input("\n  Pilih menu [1-3] atau Enter untuk kembali: ").strip()
    if not mode:
        return
    if mode not in {"1", "2", "3"}:
        print(f"  {C_ERR}Pilihan tidak valid.{C_RESET}")
        wait_for_main_menu()
        return

    # Mode semua kendaraan tidak meminta pilihan kendaraan manual.
    # Pemeriksaan OWNED dan RENTAL dilakukan sekaligus oleh auto_loop_all().
    if mode == "3":
        try:
            auto_loop_all(data, account, session, state, worker)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "?"
            print(f"\n  {C_ERR}Gagal memeriksa kendaraan (HTTP {status_code}).{C_RESET}")
            wait_for_main_menu()
        except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
            print(f"\n  {C_ERR}Gagal memulai Auto Loop Semua Kendaraan: {exc}{C_RESET}")
            wait_for_main_menu()
        return

    # Hanya mode Start Trip Sekali dan Auto Loop Pilih Kendaraan
    # yang membuka katalog untuk meminta satu kendaraan dari pengguna.
    car = choose_car(state)
    if car is None:
        return

    if mode == "1":
        start_trip_once(data, account, session, car)
        return

    category = car.get("_ct_source", "OWNED")
    if category == "RENTAL" and car.get("canDrive") is not True:
        print(f"\n  Kendaraan tidak dapat dijalankan: {vehicle_access_label(car)}")
        wait_for_main_menu()
        return

    raw_interval = input(
        f"  Interval cek dalam detik (default {DEFAULT_INTERVAL}): "
    ).strip()
    try:
        interval = int(raw_interval) if raw_interval else DEFAULT_INTERVAL
        if interval < 1 or interval > 3600:
            raise ValueError
    except ValueError:
        print(f"  {C_WARN}Interval tidak valid; menggunakan {DEFAULT_INTERVAL} detik.{C_RESET}")
        interval = DEFAULT_INTERVAL
    auto_loop(data, account, session, car, worker, interval)


def run_saved_account(data: dict, worker: dict) -> None:
    clear()
    banner()
    if worker_is_active(worker):
        running_name = worker_snapshot(worker).get("username", "akun aktif")
        print(
            f"\n  {C_WARN}Auto Loop {running_name} masih RUNNING. "
            f"Hentikan loop tersebut sebelum menjalankan akun lain.{C_RESET}"
        )
        wait_for_main_menu()
        return

    account = choose_saved_account(data)
    if account is None:
        return

    spinner(f"Memeriksa sesi akun {account.get('username', '-') }...", 0.5)
    status, session, state, message = check_saved_session(data, account)
    if status != "READY":
        print(f"\n  {C_ERR}Status sesi: {status}.{C_RESET}")
        print(f"  {message}")
        if status == "EXPIRED":
            print("  Tambahkan/login kembali dengan akun yang sama untuk memperbarui sesi.")
        wait_for_main_menu()
        return

    account = get_selected_account(data) or account
    run_vehicle_for_account(data, account, session, state, worker)


def open_vehicle_rental_menu(data: dict, worker: dict) -> None:
    """Buka daftar kendaraan untuk akun terpilih; tidak mengganti akun."""
    clear()
    banner()
    if worker_is_active(worker):
        print("\n  Auto Loop sedang berjalan. Gunakan Dashboard Realtime untuk memantaunya.")
        wait_for_main_menu()
        return

    account = get_selected_account(data)
    if account is None:
        print("\n  Belum ada akun terpilih. Tambahkan akun terlebih dahulu.")
        wait_for_main_menu()
        return

    spinner(f"Memeriksa sesi akun {account.get('username', '-') }...", 0.5)
    status, session, state, message = check_saved_session(data, account)
    if status != "READY":
        print(f"\n  {C_ERR}Status sesi: {status}.{C_RESET}")
        print(f"  {message}")
        wait_for_main_menu()
        return
    run_vehicle_for_account(data, account, session, state, worker)

def remove_saved_account(data: dict, worker: dict) -> None:
    clear()
    banner()
    if worker_is_active(worker):
        print(f"\n  {C_WARN}Hentikan Auto Loop terlebih dahulu sebelum menghapus akun.{C_RESET}")
        wait_for_main_menu()
        return

    accounts = get_accounts(data)
    if not accounts:
        print(f"\n  {C_WARN}Tidak ada akun tersimpan untuk dihapus.{C_RESET}")
        wait_for_main_menu()
        return

    section("HAPUS AKUN TERSIMPAN")
    for index, account in enumerate(accounts, 1):
        selected_mark = "  [TERPILIH]" if account.get("id") == data.get("active_account_id") else ""
        print(
            f"  {C_DIM}│{C_RESET} [{index}] {account.get('username', '-')} "
            f"| User ID {account.get('user_id', '-')}{selected_mark}"
        )
    section_end()
    raw_choice = input(f"\n  Pilih akun yang dihapus [1-{len(accounts)}] atau Enter batal: ").strip()
    if not raw_choice:
        return
    try:
        index = int(raw_choice) - 1
        if index < 0 or index >= len(accounts):
            raise IndexError
    except (ValueError, IndexError):
        print(f"  {C_ERR}Pilihan akun tidak valid.{C_RESET}")
        wait_for_main_menu()
        return

    selected = accounts[index]
    confirm = input(
        f"  Hapus sesi lokal '{selected.get('username', '-')}'? [y/N]: "
    ).strip().lower()
    if confirm == "y":
        if delete_saved_account(data, selected.get("id")):
            print(f"\n  {C_OK}Sesi lokal akun berhasil dihapus.{C_RESET}")
            print("  Akun di situs tidak dihapus; hanya cookie sesi lokal yang dihapus.")
    else:
        print(f"\n  {C_DIM}Penghapusan dibatalkan.{C_RESET}")
    wait_for_main_menu()

# ================= TELEGRAM NOTIFICATIONS =================
def telegram_api_request(token: str, method: str, payload: dict = None,
                         timeout: int = 15):
    """Panggil Telegram Bot API tanpa pernah menampilkan token ke terminal."""
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    try:
        response = requests.post(url, json=payload or {}, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Koneksi Telegram gagal ({type(exc).__name__}).") from exc

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Respons Telegram bukan JSON (HTTP {response.status_code}).") from exc

    if not response.ok or not isinstance(result, dict) or not result.get("ok"):
        description = result.get("description", "Telegram API menolak permintaan.") if isinstance(result, dict) else "Telegram API memberi respons tidak valid."
        raise RuntimeError(str(description))
    return result.get("result")


def telegram_validate_connection(token: str, chat_id: str):
    """Validasi token bot dan akses bot ke chat tujuan."""
    me = telegram_api_request(token, "getMe", {}, timeout=12)
    if not isinstance(me, dict) or not me.get("id"):
        raise RuntimeError("Identitas bot tidak dapat diverifikasi.")
    chat = telegram_api_request(token, "getChat", {"chat_id": chat_id}, timeout=12)
    if not isinstance(chat, dict) or chat.get("id") is None:
        raise RuntimeError("Chat ID tidak dapat diverifikasi.")
    return me, chat


def telegram_send_test_message(config: dict):
    """Kirim satu pesan percobaan tanpa mengubah status notifikasi."""
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    if not token:
        raise RuntimeError("Bot Token belum diatur.")
    if not chat_id:
        raise RuntimeError("Chat ID belum diatur.")

    payload = {
        "chat_id": chat_id,
        "text": (
            "THE CRYPTO TAXI BOT\n\n"
            "TEST NOTIFIKASI BERHASIL\n\n"
            "Bot Token: VALID\n"
            "Chat ID: TERHUBUNG\n\n"
            "Notifikasi siap digunakan."
        ),
        "disable_web_page_preview": True,
    }
    result = telegram_api_request(token, "sendMessage", payload, timeout=12)
    if not isinstance(result, dict) or result.get("message_id") is None:
        raise RuntimeError("Telegram tidak mengonfirmasi pengiriman pesan.")
    return result


def telegram_answer_callback(token: str, callback_id: str, message: str):
    try:
        telegram_api_request(
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": message[:180]},
            timeout=10,
        )
    except RuntimeError:
        pass


def telegram_send_callback_reply(token: str, chat_id: str, replied_message_id,
                                 message_text: str):
    """Kirim balasan chat baru yang membalas pesan tombol kendaraan."""
    if not token or not chat_id:
        raise RuntimeError("Bot Token atau Chat ID belum tersedia untuk mengirim balasan.")

    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "disable_web_page_preview": True,
    }
    if replied_message_id is not None:
        payload["reply_parameters"] = {
            "message_id": replied_message_id,
            "allow_sending_without_reply": True,
        }

    result = telegram_api_request(token, "sendMessage", payload, timeout=12)
    if not isinstance(result, dict) or result.get("message_id") is None:
        raise RuntimeError("Telegram tidak mengonfirmasi pengiriman balasan.")
    return result


def telegram_clear_message_keyboard(data: dict):
    config = get_telegram_settings(data)
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    message_id = config.get("message_id")
    if not token or not chat_id or not message_id:
        return
    try:
        telegram_api_request(
            token,
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            },
            timeout=10,
        )
        config["last_signature"] = None
        save_data(data)
    except RuntimeError:
        pass


def _number_greater_than_zero(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def vehicle_ready_for_telegram(state: dict, car: dict) -> bool:
    """Hanya loloskan kendaraan yang API nyatakan benar-benar siap dijalankan."""
    if not isinstance(state, dict) or not isinstance(car, dict):
        return False
    if not car.get("id") or car.get("broken") is True:
        return False
    if car.get("canDrive") is not True:
        return False

    trip = car.get("trip")
    if isinstance(trip, dict) and trip:
        if trip.get("endsAt") in (None, ""):
            return False
        try:
            if float(trip.get("endsAt")) > (state_now_ms(state) or time.time() * 1000):
                return False
        except (TypeError, ValueError, OverflowError):
            return False

    quota = car.get("quota") if isinstance(car.get("quota"), dict) else {}
    now_ms = state_now_ms(state) or time.time() * 1000
    if not _number_greater_than_zero(quota.get("left")) and not bonus_is_available(quota, now_ms):
        return False
    return True


def collect_ready_vehicle_groups(state: dict) -> dict:
    """Ambil kendaraan OWNED dan RENTAL yang benar-benar siap dari satu state API."""
    own, rented = vehicle_collections(state)
    groups = {"OWNED": [], "RENTAL": []}
    seen = set()
    for category, cars in (("OWNED", own), ("RENTAL", rented)):
        for raw_car in cars:
            if not isinstance(raw_car, dict):
                continue
            car_id = raw_car.get("id")
            key = (category, str(car_id))
            if car_id in (None, "") or key in seen:
                continue
            seen.add(key)
            if not vehicle_ready_for_telegram(state, raw_car):
                continue
            car = dict(raw_car)
            car["_ct_source"] = category
            groups[category].append(car)
    return groups


def collect_telegram_ready_vehicles(data: dict, worker: dict,
                                    allow_finalizing: bool = False) -> list:
    """Periksa semua akun; izinkan pemindaian saat worker hanya finalisasi notifikasi."""
    def scan_blocked() -> bool:
        snapshot = worker_snapshot(worker) if worker.get("thread") else {}
        if allow_finalizing and snapshot.get("finalizing") and not snapshot.get("running"):
            return False
        return worker_is_active(worker)

    if scan_blocked():
        return []

    ready = []
    for account in list(get_accounts(data)):
        if scan_blocked():
            return []
        session = create_saved_session(data, account)
        try:
            response = session.post(API_STATE, json={}, timeout=10)
            response.raise_for_status()
            state = response.json()
            if not isinstance(state, dict):
                continue

            me = state.get("me", {})
            if not isinstance(me, dict):
                continue
            expected_id = account.get("user_id")
            actual_id = me.get("id")
            if expected_id is not None and str(expected_id) != str(actual_id):
                continue
            expected_username = str(account.get("username") or "").strip()
            actual_username = str(me.get("username") or expected_username or "-").strip()
            if expected_id is None and expected_username and actual_username.casefold() != expected_username.casefold():
                continue

            own, rented = vehicle_collections(state)
            for category, cars in (("OWNED", own), ("RENTAL", rented)):
                for raw_car in cars:
                    if not isinstance(raw_car, dict) or not vehicle_ready_for_telegram(state, raw_car):
                        continue
                    car = dict(raw_car)
                    car["_ct_source"] = category
                    callback_data = f"run|{account.get('id', '')}|{car.get('id')}|{category}"
                    if len(callback_data.encode("utf-8")) > 64:
                        continue
                    ready.append({
                        "account_id": str(account.get("id", "")),
                        "username": actual_username or "-",
                        "car_id": str(car.get("id")),
                        "car_name": str(car.get("name") or f"Mobil {car.get('id')}"),
                        "category": category,
                        "quota_text": quota_display_for_vehicle(state, car, category),
                        "callback_data": callback_data,
                    })
        except (requests.RequestException, ValueError, TypeError):
            # Akun yang gagal diperiksa tidak dianggap siap; tidak ada tebakan status.
            continue
        finally:
            session.close()
    return ready


def _telegram_message_content(items: list):
    """Buat satu pesan ringkas beserta tombol khusus untuk setiap kendaraan."""
    if not items:
        return (
            "THE CRYPTO TAXI BOT\n\nKENDARAAN SIAP DIGUNAKAN\n\n"
            "Saat ini tidak ada kendaraan yang siap digunakan."
        ), {"inline_keyboard": []}

    lines = ["THE CRYPTO TAXI BOT", "", "KENDARAAN SIAP DIGUNAKAN", ""]
    keyboard = []
    previous_account = None
    number = 0
    truncated = False

    for item in items:
        account_key = item["account_id"]
        account_header = []
        if account_key != previous_account:
            account_header = [f"Akun: {item['username']}", ""]
        number += 1
        block = account_header + [
            f"{number}. {item['car_name']} [{item['category']}]",
            f"Quota: {item['quota_text']}",
            "",
        ]
        candidate = "\n".join(lines + block)
        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            number -= 1
            truncated = True
            break
        lines.extend(block)
        keyboard.append([{
            "text": f"▶ JALANKAN AUTO LOOP #{number}",
            "callback_data": item["callback_data"],
        }])
        previous_account = account_key

    if truncated:
        lines.extend(["... daftar kendaraan lainnya tidak ditampilkan."])
    text = "\n".join(lines).rstrip()
    return text, {"inline_keyboard": keyboard}


def publish_telegram_vehicle_message(data: dict, items: list, force: bool = False):
    """Kirim/perbarui satu pesan kendaraan; force juga mengizinkan pesan daftar kosong."""
    config = get_telegram_settings(data)
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    if not config.get("enabled") or not token or not chat_id:
        return

    if not items and not config.get("message_id") and not force:
        return

    signature_data = [
        (x["account_id"], x["car_id"], x["category"], x["car_name"], x["quota_text"])
        for x in items
    ]
    signature = json.dumps(signature_data, ensure_ascii=False, separators=(",", ":"))
    message_text, reply_markup = _telegram_message_content(items)
    message_id = config.get("message_id")

    if config.get("last_signature") == signature and not force:
        return

    if message_id:
        try:
            telegram_api_request(
                token,
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": message_text,
                    "reply_markup": reply_markup,
                },
                timeout=12,
            )
            config["last_signature"] = signature
            save_data(data)
            return
        except RuntimeError as exc:
            error_text = str(exc).casefold()
            if "message is not modified" in error_text:
                config["last_signature"] = signature
                save_data(data)
                return
            if "message to edit not found" not in error_text and "message_id_invalid" not in error_text:
                # Error jaringan/izin dicoba ulang pada pemindaian berikutnya;
                # jangan kirim pesan baru karena dapat membuat notifikasi ganda.
                raise
            # Pesan lama memang sudah tidak ada; buat pesan aktif yang baru.
            config["message_id"] = None
            config["last_signature"] = None

    if not items and not force:
        save_data(data)
        return

    sent = telegram_api_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": message_text,
            "reply_markup": reply_markup,
            "disable_web_page_preview": True,
        },
        timeout=12,
    )
    if isinstance(sent, dict) and sent.get("message_id") is not None:
        config["message_id"] = sent["message_id"]
        config["last_signature"] = signature
        save_data(data)


def telegram_edit_control_message(data: dict, text: str, keyboard: list = None):
    """Edit satu pesan panel Telegram yang sama; tidak membuat pesan panel duplikat."""
    config = get_telegram_settings(data)
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    message_id = config.get("message_id")
    if not token or not chat_id:
        return False
    markup = {"inline_keyboard": keyboard or []}
    if message_id:
        try:
            telegram_api_request(token, "editMessageText", {
                "chat_id": chat_id, "message_id": message_id,
                "text": text, "reply_markup": markup,
                "parse_mode": "HTML" if text.startswith("<pre>") else None,
                "disable_web_page_preview": True,
            }, timeout=12)
            config["last_signature"] = None
            save_data(data)
            return True
        except RuntimeError as exc:
            if "message is not modified" in str(exc).casefold():
                return True
            if not any(x in str(exc).casefold() for x in ("message to edit not found", "message_id_invalid")):
                raise
            config["message_id"] = None
    sent = telegram_api_request(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "reply_markup": markup,
        "parse_mode": "HTML" if text.startswith("<pre>") else None,
        "disable_web_page_preview": True,
    }, timeout=12)
    if isinstance(sent, dict) and sent.get("message_id") is not None:
        config["message_id"] = sent["message_id"]
        config["last_signature"] = None
        save_data(data)
        return True
    return False


def telegram_control_panel(data: dict):
    text = "THE CRYPTO TAXI BOT\n\nPANEL KONTROL"
    keyboard = [
        [{"text": "CEK STATUS SEMUA AKUN", "callback_data": "panel|status"}],
        [{"text": "JALANKAN AUTO LOOP SEMUA", "callback_data": "panel|run_all"}],
    ]
    return telegram_edit_control_message(data, text, keyboard)


def _telegram_account_state(data: dict, account: dict):
    """Ambil status sesi dan jumlah READY; ERROR tidak disamakan dengan EXPIRED."""
    session = None
    try:
        session = create_saved_session(data, account)
        state = get_state(session)
        if not isinstance(state, dict):
            return {"session": "ERROR", "owned": None, "rental": None}
        me = state.get("me") if isinstance(state.get("me"), dict) else {}
        expected_id = account.get("user_id")
        actual_id = me.get("id")
        expected_name = str(account.get("username") or "").strip()
        actual_name = str(me.get("username") or "").strip()
        if expected_id is not None and str(expected_id) != str(actual_id):
            return {"session": "ERROR", "owned": None, "rental": None}
        if expected_id is None and expected_name and actual_name and expected_name.casefold() != actual_name.casefold():
            return {"session": "ERROR", "owned": None, "rental": None}
        groups = collect_ready_vehicle_groups(state)
        return {"session": "VALID", "owned": len(groups["OWNED"]), "rental": len(groups["RENTAL"]), "state": state}
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else None
        return {"session": "EXPIRED" if code in (401, 403) else "ERROR", "owned": None, "rental": None}
    except (requests.RequestException, ValueError, TypeError, RuntimeError, OSError):
        return {"session": "ERROR", "owned": None, "rental": None}
    finally:
        if session is not None:
            session.close()


def telegram_show_all_account_status(data: dict):
    rows = []
    for account in list(get_accounts(data)):
        result = _telegram_account_state(data, account)
        username = str(account.get("username") or "-")[:16]
        session = result["session"]
        owned = str(result["owned"]) if result["owned"] is not None else "-"
        rental = str(result["rental"]) if result["rental"] is not None else "-"
        rows.append((html.escape(username), session, owned, rental))
    headers = ("AKUN", "SESSION", "OWNED", "RENTAL")
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i]) for i in range(4)]
    def fmt(row):
        return f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:>{widths[2]}}  {row[3]:>{widths[3]}}"
    lines = ["THE CRYPTO TAXI BOT", "", "STATUS SEMUA AKUN", "", fmt(headers), "-" * (sum(widths) + 6)]
    lines.extend(fmt(row) for row in rows)
    if not rows:
        lines.append("Belum ada akun tersimpan.")
    # Telegram membatasi pesan 4096 karakter.
    body = "<pre>" + "\n".join(lines)[:3800] + "</pre>"
    telegram_edit_control_message(data, body, [[{"text": "KEMBALI KE PANEL KONTROL", "callback_data": "panel|home"}]])


def telegram_show_account_picker(data: dict):
    keyboard = []
    lines = ["THE CRYPTO TAXI BOT", "", "PILIH AKUN UNTUK AUTO LOOP SEMUA", ""]
    for account in list(get_accounts(data)):
        result = _telegram_account_state(data, account)
        username = str(account.get("username") or "-")
        if result["session"] == "VALID":
            owned, rental = result["owned"], result["rental"]
            lines.append(f"{username} — OWNED READY: {owned} | RENTAL READY: {rental}")
            callback_data = f"choose|{account.get('id', '')}"
            if len(callback_data.encode("utf-8")) <= 64:
                keyboard.append([{"text": f"▶ {username} ({owned}+{rental} READY)", "callback_data": callback_data}])
        else:
            lines.append(f"{username} — {result['session']}")
    if not get_accounts(data):
        lines.append("Belum ada akun tersimpan.")
    keyboard.append([{"text": "KEMBALI KE PANEL KONTROL", "callback_data": "panel|home"}])
    telegram_edit_control_message(data, "\n".join(lines)[:3900], keyboard)


def handle_telegram_callback(data: dict, worker: dict, callback: dict):
    """Panel Telegram: cek semua akun atau jalankan orchestrator semua kendaraan satu akun."""
    config = get_telegram_settings(data)
    token = str(config.get("bot_token") or "").strip()
    callback_id = str(callback.get("id") or "")
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = str(chat.get("id", ""))
    configured_chat_id = str(config.get("chat_id") or "").strip()
    message_id = message.get("message_id")

    def answer(msg):
        if token and callback_id:
            telegram_answer_callback(token, callback_id, msg)

    if not token or not config.get("enabled"):
        answer("Telegram tidak aktif atau token belum tersedia.")
        return
    if not configured_chat_id or chat_id != configured_chat_id:
        answer("Chat ID tidak diizinkan.")
        return
    if message_id != config.get("message_id"):
        answer("Panel sudah diperbarui. Gunakan pesan panel terbaru.")
        return

    action = str(callback.get("data") or "")
    if action == "panel|home":
        telegram_control_panel(data)
        answer("Panel kontrol")
        return
    if action == "panel|status":
        answer("Memeriksa semua akun...")
        try:
            telegram_show_all_account_status(data)
        except Exception as exc:
            worker["telegram_last_error"] = f"Pemeriksaan status akun gagal: {type(exc).__name__}: {exc}"
            answer("Pemeriksaan status gagal.")
        return
    if action == "panel|run_all":
        if worker_is_active(worker):
            answer("Auto Loop lain masih berjalan.")
            return
        answer("Memuat daftar akun...")
        try:
            telegram_show_account_picker(data)
        except Exception as exc:
            worker["telegram_last_error"] = f"Daftar akun gagal dimuat: {type(exc).__name__}: {exc}"
        return

    if action.startswith("choose|"):
        if worker_is_active(worker):
            answer("Auto Loop lain masih berjalan.")
            return
        account_id = action.split("|", 1)[1]
        account = find_account(data, account_id)
        if account is None:
            answer("Akun tersimpan tidak ditemukan.")
            return
        session = None
        keep_session = False
        try:
            session = create_saved_session(data, account)
            state = get_state(session)
            me = state.get("me", {}) if isinstance(state, dict) else {}
            expected_id = account.get("user_id")
            actual_id = me.get("id") if isinstance(me, dict) else None
            if expected_id is not None and str(expected_id) != str(actual_id):
                raise RuntimeError("Sesi akun tidak cocok.")
            if expected_id is None:
                expected = str(account.get("username") or "").strip()
                actual = str(me.get("username") or "").strip() if isinstance(me, dict) else ""
                if expected and expected.casefold() != actual.casefold():
                    raise RuntimeError("Sesi akun tidak cocok.")
            groups = collect_ready_vehicle_groups(state)
            owned_count, rental_count = len(groups["OWNED"]), len(groups["RENTAL"])
            if not start_auto_loop_all_worker(data, account, session, state, groups, worker, DEFAULT_INTERVAL):
                answer("Auto Loop lain masih berjalan.")
                return
            keep_session = True
            running_text = (
                "THE CRYPTO TAXI BOT\n\n✅ AUTO LOOP BERHASIL DIMULAI\n"
                f"Akun: {account.get('username', '-')}\n"
                "Mode: Auto Loop Semua Kendaraan\n"
                f"OWNED READY: {owned_count}\nRENTAL READY: {rental_count}\nStatus: RUNNING"
            )
            telegram_edit_control_message(data, running_text, [])
            answer("Auto Loop Semua Kendaraan dimulai.")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            answer("Sesi EXPIRED." if code in (401, 403) else f"Gagal cek akun (HTTP {code}).")
            telegram_show_account_picker(data)
        except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
            answer(f"Gagal menjalankan akun: {type(exc).__name__}.")
            telegram_show_account_picker(data)
        finally:
            if session is not None and not keep_session:
                session.close()
        return
    answer("Perintah panel tidak dikenali.")

def telegram_publish_loop_completion(data: dict, worker: dict,
                                      snapshot: dict, mode: str) -> None:
    """Kirim laporan akhir dan pulihkan panel kontrol pada pesan panel yang sama."""
    config = get_telegram_settings(data)
    if not config.get("enabled"):
        return
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    if not token or not chat_id:
        return
    account = find_account(data, snapshot.get("account_id")) or {}
    username = snapshot.get("username") or account.get("username", "-")
    if mode == "PICK":
        car = snapshot.get("car") if isinstance(snapshot.get("car"), dict) else {}
        category = snapshot.get("vehicle_type") or car.get("_ct_source") or "UNKNOWN"
        lines = ["THE CRYPTO TAXI BOT", "", "✅ AUTO LOOP SELESAI", "",
                 f"Akun: {username}",
                 f"Kendaraan: {car.get('name') or 'Kendaraan'} [{category}]",
                 "Mode: Auto Loop Pilih Kendaraan",
                 "Status: Quota dan bonus habis."]
        try:
            telegram_api_request(token, "sendMessage", {"chat_id": chat_id, "text": "\n".join(lines),
                                  "disable_web_page_preview": True}, timeout=12)
        except RuntimeError as exc:
            worker["telegram_last_error"] = f"Pesan selesai gagal dikirim: {exc}"
        try:
            telegram_control_panel(data)
        except RuntimeError as exc:
            worker["telegram_last_error"] = f"Panel Telegram gagal dipulihkan: {exc}"
        return
    lines = ["THE CRYPTO TAXI BOT", "", "✅ AUTO LOOP SELESAI", "",
             f"Akun: {username}", "Mode: Auto Loop Semua Kendaraan"]
    totals = snapshot.get("all_totals") or {"OWNED": 0, "RENTAL": 0}
    done = snapshot.get("all_done") or {"OWNED": 0, "RENTAL": 0}
    skipped = snapshot.get("all_skipped") or {"OWNED": 0, "RENTAL": 0}
    lines.extend([
        f"OWNED: {done.get('OWNED', 0)}/{totals.get('OWNED', 0)} selesai dijalankan",
        f"RENTAL: {done.get('RENTAL', 0)}/{totals.get('RENTAL', 0)} selesai dijalankan",
        "Tidak dijalankan:",
        f"OWNED: {skipped.get('OWNED', 0)} | RENTAL: {skipped.get('RENTAL', 0)}",
        f"Status: {snapshot.get('stop_reason') or 'Selesai'}",
    ])
    if snapshot.get("final_ready", 0) == 0:
        lines.append("Tidak ada kendaraan READY yang tersisa.")
    else:
        lines.append(f"PERHATIAN: {snapshot.get('final_ready')} kendaraan masih READY.")
    try:
        telegram_api_request(token, "sendMessage", {
            "chat_id": chat_id, "text": "\n".join(lines),
            "disable_web_page_preview": True,
        }, timeout=12)
    except RuntimeError as exc:
        worker["telegram_last_error"] = f"Pesan selesai gagal dikirim: {exc}"
    try:
        telegram_control_panel(data)
    except RuntimeError as exc:
        worker["telegram_last_error"] = f"Panel Telegram gagal dipulihkan: {exc}"


def telegram_notification_loop(data: dict, worker: dict, stop_event: threading.Event):
    """Polling tombol Telegram; cek kendaraan hanya saat awal dan setelah loop selesai."""
    offset = None
    last_token = None
    initial_scan_done = False

    while not stop_event.is_set():
        config = get_telegram_settings(data)
        if not config.get("enabled"):
            break
        token = str(config.get("bot_token") or "").strip()
        chat_id = str(config.get("chat_id") or "").strip()
        if not token or not chat_id:
            worker["telegram_last_error"] = "Bot Token atau Chat ID belum diatur."
            stop_event.wait(3)
            continue
        if token != last_token:
            offset = None
            last_token = token
            initial_scan_done = False
        if worker.pop("telegram_initial_scan_requested", False):
            initial_scan_done = False

        # Buat/perbarui hanya satu panel kontrol; tidak mengirim daftar tombol per kendaraan.
        if not initial_scan_done:
            try:
                telegram_control_panel(data)
                worker["telegram_last_error"] = None
                initial_scan_done = True
            except (RuntimeError, requests.RequestException, OSError, ValueError, TypeError) as exc:
                worker["telegram_last_error"] = str(exc)

        if stop_event.is_set():
            break
        try:
            payload = {
                "timeout": TELEGRAM_POLL_TIMEOUT,
                "allowed_updates": ["callback_query"],
            }
            if offset is not None:
                payload["offset"] = offset
            updates = telegram_api_request(
                token,
                "getUpdates",
                payload,
                timeout=TELEGRAM_POLL_TIMEOUT + 6,
            ) or []
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                callback = update.get("callback_query")
                if isinstance(callback, dict):
                    handle_telegram_callback(data, worker, callback)
        except RuntimeError as exc:
            worker["telegram_last_error"] = str(exc)
            stop_event.wait(3)


def start_telegram_service(data: dict, worker: dict):
    """Jalankan satu thread pemantau Telegram jika konfigurasi aktif."""
    config = get_telegram_settings(data)
    if not config.get("enabled"):
        return
    thread = worker.get("telegram_thread")
    if thread and thread.is_alive():
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=telegram_notification_loop,
        args=(data, worker, stop_event),
        name="CryptoTaxiTelegramMonitor",
        daemon=True,
    )
    worker["telegram_stop_event"] = stop_event
    worker["telegram_thread"] = thread
    thread.start()


def stop_telegram_service(worker: dict):
    stop_event = worker.get("telegram_stop_event")
    thread = worker.get("telegram_thread")
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=2)
    if not thread or not thread.is_alive():
        worker["telegram_thread"] = None
        worker["telegram_stop_event"] = None


def restart_telegram_service(data: dict, worker: dict):
    """Minta satu pemeriksaan awal saat konfigurasi Telegram diaktifkan/diubah."""
    worker["telegram_initial_scan_requested"] = True
    start_telegram_service(data, worker)


def telegram_settings_menu(data: dict, worker: dict):
    """Pengaturan Telegram; Bot Token terlihat saat dimasukkan terminal."""
    while True:
        config = get_telegram_settings(data)
        clear()
        banner()
        section("PENGATURAN NOTIFIKASI TELEGRAM")
        info("Status", "AKTIF" if config.get("enabled") else "NONAKTIF",
             C_OK if config.get("enabled") else C_WARN)
        info("Bot Token", "TERSIMPAN" if config.get("bot_token") else "BELUM DIATUR")
        info("Chat ID", "TERSIMPAN" if config.get("chat_id") else "BELUM DIATUR")
        info("Pemeriksaan", "awal program & setelah loop selesai")
        last_error = worker.get("telegram_last_error")
        if last_error:
            info("Error terakhir", last_error, C_WARN)
        section_end()
        print("\n  [1] Aktifkan Notifikasi")
        print("  [2] Nonaktifkan Notifikasi")
        print("  [3] Kirim Pesan Percobaan")
        print("  [4] Atur Bot Token")
        print("  [5] Atur Chat ID")
        print("  [0] Kembali")
        choice = input("\n  Pilih menu [0-5]: ").strip()

        if choice == "0":
            return
        if choice == "1":
            token = str(config.get("bot_token") or "").strip()
            chat_id = str(config.get("chat_id") or "").strip()
            if not token or not chat_id:
                print(f"\n  {C_WARN}Atur Bot Token dan Chat ID terlebih dahulu.{C_RESET}")
                wait_for_main_menu()
                continue
            try:
                me, chat = telegram_validate_connection(token, chat_id)
                config["enabled"] = True
                config["last_signature"] = None
                save_data(data)
                restart_telegram_service(data, worker)
                print(f"\n  {C_OK}Notifikasi aktif: @{me.get('username', 'bot')} → {chat.get('id')}.{C_RESET}")
            except RuntimeError as exc:
                print(f"\n  {C_ERR}Tidak dapat mengaktifkan Telegram: {exc}{C_RESET}")
            wait_for_main_menu()
            continue
        if choice == "2":
            config["enabled"] = False
            config["last_signature"] = None
            save_data(data)
            # Thread akan melihat status NONAKTIF setelah long-poll selesai.
            # Tidak dipaksa dihentikan agar aktivasi ulang tidak membuat dua poller.
            telegram_clear_message_keyboard(data)
            print(f"\n  {C_OK}Notifikasi Telegram dinonaktifkan.{C_RESET}")
            wait_for_main_menu()
            continue
        if choice == "3":
            token = str(config.get("bot_token") or "").strip()
            chat_id = str(config.get("chat_id") or "").strip()
            if not token or not chat_id:
                missing = []
                if not token:
                    missing.append("Bot Token")
                if not chat_id:
                    missing.append("Chat ID")
                print(f"\n  {C_WARN}Atur terlebih dahulu: {', '.join(missing)}.{C_RESET}")
            else:
                try:
                    result = telegram_send_test_message(config)
                    print(
                        f"\n  {C_OK}Pesan percobaan berhasil dikirim. "
                        f"Message ID: {result.get('message_id')}.{C_RESET}"
                    )
                    print("  Periksa chat Telegram tujuan.")
                except RuntimeError as exc:
                    print(f"\n  {C_ERR}Pesan percobaan gagal dikirim: {exc}{C_RESET}")
            wait_for_main_menu()
            continue
        if choice == "4":
            # Input biasa sengaja digunakan agar token terlihat saat ditempel.
            token = input("\n  Bot Token: ").strip()
            if not token:
                print(f"  {C_WARN}Bot Token tidak diubah.{C_RESET}")
                wait_for_main_menu()
                continue
            try:
                me = telegram_api_request(token, "getMe", {}, timeout=12)
                config["bot_token"] = token
                config["message_id"] = None
                config["last_signature"] = None
                save_data(data)
                if config.get("enabled"):
                    restart_telegram_service(data, worker)
                print(f"\n  {C_OK}Bot Token valid: @{me.get('username', 'bot')}.{C_RESET}")
            except RuntimeError as exc:
                print(f"\n  {C_ERR}Bot Token tidak dapat diverifikasi: {exc}{C_RESET}")
            wait_for_main_menu()
            continue
        if choice == "5":
            chat_id = input("\n  Chat ID (kirim /start ke bot terlebih dahulu): ").strip()
            if not chat_id:
                print(f"  {C_WARN}Chat ID tidak diubah.{C_RESET}")
                wait_for_main_menu()
                continue
            token = str(config.get("bot_token") or "").strip()
            try:
                if token:
                    chat = telegram_api_request(token, "getChat", {"chat_id": chat_id}, timeout=12)
                    chat_id = str(chat.get("id", chat_id))
                config["chat_id"] = chat_id
                config["message_id"] = None
                config["last_signature"] = None
                save_data(data)
                if config.get("enabled"):
                    restart_telegram_service(data, worker)
                print(f"\n  {C_OK}Chat ID berhasil disimpan: {chat_id}.{C_RESET}")
            except RuntimeError as exc:
                print(f"\n  {C_ERR}Chat ID tidak dapat diverifikasi: {exc}{C_RESET}")
            wait_for_main_menu()
            continue

        print(f"\n  {C_ERR}Pilihan tidak valid.{C_RESET}")
        time.sleep(1)


def render_main_menu(data: dict, worker: dict) -> bool:
    """Menu utama: pendapatan akun terpilih, saldo semua akun, waktu dan kendaraan."""
    accounts = get_accounts(data)
    selected = get_selected_account(data)
    cache = refresh_main_summary_cache(data, worker)
    snapshot = worker_snapshot(worker) if worker.get("thread") else {}
    active = worker_is_active(worker)

    selected_entry = cache.get(selected.get("id")) if selected else None
    selected_state = selected_entry.get("state") if isinstance(selected_entry, dict) else None
    selected_state_monotonic = selected_entry.get("state_monotonic") if isinstance(selected_entry, dict) else None
    session_status = selected_entry.get("status", "UNKNOWN") if isinstance(selected_entry, dict) else "NO SESSION"

    if selected and snapshot.get("account_id") == selected.get("id") and isinstance(snapshot.get("state"), dict):
        selected_state = snapshot.get("state")
        selected_state_monotonic = snapshot.get("state_monotonic", time.monotonic())
        session_status = snapshot.get("session_status", "VALID")

    if selected is None:
        selected_name = "-"
        status = "NO ACCOUNT"
        session_status = "NO SESSION"
    else:
        selected_name = selected.get("username", "-")
        if active and snapshot.get("account_id") == selected.get("id") and snapshot.get("running"):
            status = "RUNNING"
        elif session_status == "EXPIRED":
            status = "EXPIRED"
        elif session_status == "VALID":
            status = "READY"
        else:
            status = "UNKNOWN"

    # Waktu game diinterpolasi dari state.now; jam tetap bergerak tanpa request tiap detik.
    if selected_state:
        game_now = live_server_now_ms(selected_state, selected_state_monotonic)
        try:
            game_clock = datetime.fromtimestamp(game_now / 1000, tz=timezone.utc).strftime("%I:%M:%S %p")
        except (ValueError, OSError, OverflowError):
            game_clock = "BELUM TERSEDIA"
    else:
        game_clock = "BELUM TERSEDIA"

    # Ringkasan kendaraan hanya untuk akun yang sedang dipilih.
    vehicle_info = vehicle_summary(selected_state, selected_state_monotonic) if selected_state else None

    # Saldo digabung untuk semua akun; pendapatan harian hanya akun terpilih.
    all_states_valid = bool(accounts) and all(
        isinstance(cache.get(account.get("id")), dict)
        and cache[account.get("id")].get("status") == "VALID"
        and isinstance(cache[account.get("id")].get("state"), dict)
        for account in accounts
    )
    wallet_value = None
    if isinstance(selected_state, dict):
        balances = selected_state.get("balances", {})
        if isinstance(balances, dict):
            try:
                wallet_value = float(balances.get("usdt", 0) or 0)
            except (TypeError, ValueError):
                wallet_value = None

    total_balance = None
    # Pendapatan hari ini khusus akun terpilih; tidak dijumlahkan dari akun lain.
    daily_total, daily_is_estimated = selected_account_daily_income(selected, selected_state)
    if all_states_valid:
        try:
            total_balance = sum(
                float(cache[account.get("id")]["state"].get("balances", {}).get("usdt", 0) or 0)
                for account in accounts
            )
        except (TypeError, ValueError, AttributeError):
            total_balance = None

    fx_rate = fetch_usdt_idr_rate(worker)
    clear()
    banner()

    section("ACCOUNT SUMMARY")
    info("Total akun", len(accounts), C_BLUE)
    info("Akun terpilih", selected_name, C_MAG if selected else C_RESET)
    status_color = C_OK if status == "RUNNING" else C_BLUE if status == "READY" else C_ERR if status == "EXPIRED" else C_WARN
    info("Status", status, status_color)
    session_color = C_OK if session_status == "VALID" else C_ERR if session_status == "EXPIRED" else C_WARN
    info("Session", session_status, session_color)
    info("Waktu game", game_clock, C_INFO)

    if vehicle_info is None:
        info("Status kendaraan", "Belum ada data kendaraan", C_WARN)
    else:
        counts, countdowns = vehicle_info
        status_parts = []
        if counts["running"]:
            status_parts.append((f"{counts['running']} berjalan", C_OK))
        if counts["standby"]:
            status_parts.append((f"{counts['standby']} standby", C_WARN))
        if counts["unavailable"]:
            status_parts.append((f"{counts['unavailable']} tidak tersedia", C_WARN))
        if status_parts:
            info_segments("Status kendaraan", status_parts)
        else:
            info("Status kendaraan", "Tidak ada kendaraan", C_WARN)
        if countdowns:
            info("Countdown trip", " | ".join(countdowns), C_WARN)
    section_end()

    section("KEUANGAN")
    if daily_total is None:
        daily_text = "BELUM TERLACAK"
        daily_color = C_WARN
    else:
        daily_text = format_usdt_idr(daily_total, fx_rate)
        # Tanda ~ menandakan akumulasi sejak baseline lokal mulai dipantau.
        if daily_is_estimated:
            daily_text = "~" + daily_text
        daily_color = C_OK if not daily_is_estimated else C_INFO
    info("Pendapatan hari ini", daily_text, daily_color)

    if wallet_value is None:
        wallet_text = "DATA TIDAK TERSEDIA"
        wallet_color = C_WARN
    else:
        wallet_text = format_usdt_idr(wallet_value, fx_rate)
        wallet_color = C_OK
    info("Dompet (akun sekarang)", wallet_text, wallet_color)

    if total_balance is None:
        total_balance_text = "DATA BELUM LENGKAP"
        total_balance_color = C_WARN
    else:
        total_balance_text = format_usdt_idr(total_balance, fx_rate)
        total_balance_color = C_OK
    info("Saldo saat ini (semua akun)", total_balance_text, total_balance_color)
    section_end()

    section("MENU")
    box_text("[1] Tambahkan Akun Baru")
    box_text("[2] Pilih Akun dan Jalankan")
    box_text("[3] Kendaraan & Rental")
    box_text("[4] Dashboard Realtime")
    box_text("[5] Hapus Akun Tersimpan")
    box_text("[6] Pengaturan Notifikasi Telegram")
    box_text("[7] Keluar")
    section_end()
    return True


def read_main_menu_choice(prompt: str, refresh_callback, refresh_active: bool,
                           refresh_interval: float = 1.0) -> str:
    """Baca pilihan menu sambil memperbarui ringkasan saat worker berjalan."""
    if not sys.stdin.isatty():
        return input(prompt).strip()

    if os.name == "nt":
        import msvcrt

        buffer = ""
        next_refresh = time.monotonic() + refresh_interval if refresh_active else None
        sys.stdout.write(prompt)
        sys.stdout.flush()
        while True:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\r", "\n"):
                    sys.stdout.write("\n")
                    return buffer.strip()
                if char == "\x03":
                    raise KeyboardInterrupt
                if char == "\x08":
                    if buffer:
                        buffer = buffer[:-1]
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif char in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                elif char.isprintable():
                    buffer += char
                    sys.stdout.write(char)
                    sys.stdout.flush()
            if next_refresh is not None and time.monotonic() >= next_refresh:
                refresh_active = bool(refresh_callback())
                sys.stdout.write(prompt + buffer)
                sys.stdout.flush()
                next_refresh = time.monotonic() + refresh_interval if refresh_active else None
            time.sleep(0.03)

    # Termux/Linux: cbreak memungkinkan refresh layar tanpa menghilangkan teks
    # yang sudah diketik pada prompt menu utama.
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(fd)
    buffer = ""
    next_refresh = time.monotonic() + refresh_interval if refresh_active else None
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        while True:
            timeout = None
            if next_refresh is not None:
                timeout = max(0.0, next_refresh - time.monotonic())
            readable, _, _ = select.select([fd], [], [], timeout)
            if readable:
                char = os.read(fd, 1).decode("utf-8", errors="ignore")
                if char in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return buffer.strip()
                if char == "\x03":
                    raise KeyboardInterrupt
                if char == "\x04":
                    raise EOFError
                if char in ("\x7f", "\x08"):
                    if buffer:
                        buffer = buffer[:-1]
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif char.isprintable():
                    buffer += char
                    sys.stdout.write(char)
                    sys.stdout.flush()
            elif next_refresh is not None:
                refresh_active = bool(refresh_callback())
                sys.stdout.write(prompt + buffer)
                sys.stdout.flush()
                next_refresh = time.monotonic() + refresh_interval if refresh_active else None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous_settings)


def main() -> None:
    try:
        data = load_data()
    except RuntimeError as exc:
        print(f"{C_ERR}{exc}{C_RESET}")
        sys.exit(1)

    worker = {
        "thread": None,
        "stop_event": None,
        "status": None,
        "lock": None,
        "summary_cache": {},
        "summary_last_refresh": 0.0,
        "fx_cache": {},
        "start_lock": threading.Lock(),
        "telegram_thread": None,
        "telegram_stop_event": None,
        "telegram_last_error": None,
    }
    if get_telegram_settings(data).get("enabled"):
        start_telegram_service(data, worker)
    prompt = f"\n  {C_INFO}Pilih menu [1-7]: {C_RESET}"

    while True:
        refresh_active = render_main_menu(data, worker)
        choice = read_main_menu_choice(
            prompt,
            lambda: render_main_menu(data, worker),
            refresh_active,
            refresh_interval=1.0,
        )
        if choice in {"1", "2", "3", "4", "5", "6", "7"}:
            clear()

        if choice == "1":
            if worker_is_active(worker):
                print(f"\n  {C_WARN}Auto Loop masih berjalan. Hentikan terlebih dahulu sebelum menambahkan akun.{C_RESET}")
                wait_for_main_menu()
            else:
                login_and_save(data)
        elif choice == "2":
            run_saved_account(data, worker)
        elif choice == "3":
            open_vehicle_rental_menu(data, worker)
        elif choice == "4":
            dashboard_loop(data, worker)
        elif choice == "5":
            remove_saved_account(data, worker)
        elif choice == "6":
            telegram_settings_menu(data, worker)
        elif choice == "7":
            if worker_is_active(worker):
                confirm = input(
                    "  Auto Loop masih RUNNING. Ketik Y untuk menghentikan dan keluar, atau Enter untuk batal: "
                ).strip().lower()
                if confirm != "y":
                    continue
                if not stop_auto_worker(worker):
                    print(f"\n  {C_ERR}Worker belum berhenti. Kembali ke menu utama.{C_RESET}")
                    wait_for_main_menu()
                    continue
            stop_telegram_service(worker)
            print(f"\n  {C_INFO}Selesai.{C_RESET}\n")
            return
        else:
            print(f"\n  {C_ERR}Pilihan tidak valid.{C_RESET}")
            time.sleep(1)



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C_INFO}Dibatalkan.{C_RESET}\n")
        sys.exit(0)
