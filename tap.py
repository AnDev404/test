import requests
import logging
import time
import os
import sys
import getpass
from dotenv import load_dotenv

load_dotenv()

# ================= KONFIGURASI DEFAULT =================
BASE_URL = "https://tapminings.com"

POINTS_PER_CLAIM    = 500
QUESTIONS_PER_CLAIM = 1

DIAMONDS_PER_CLAIM  = 200
MAX_KLAIM           = 5
JEDA_DETIK          = 60
# =======================================================

# ================= WARNA ANSI ==========================
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"
    BRED    = "\033[91m"
    BGREEN  = "\033[92m"
    BYELLOW = "\033[93m"
    BBLUE   = "\033[94m"
    BMAGENTA= "\033[95m"
    BCYAN   = "\033[96m"
    BWHITE  = "\033[97m"
    BG_GREEN   = "\033[42m"
    BG_RED     = "\033[41m"
    BG_MAGENTA = "\033[45m"

def warna(teks, *codes):
    return "".join(codes) + teks + C.RESET

def clear():
    os.system("cls" if os.name == "nt" else "clear")


# ================= BANNER ==============================
def banner():
    clear()
    print(f"""{C.BCYAN}{C.BOLD}
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   {C.BWHITE}  👑 OWNER  : {C.BYELLOW}{C.BOLD}Sains Zama{C.BCYAN}                                  ║
║   {C.BWHITE}  ⚙  VERSION: {C.BWHITE}1.0{C.BCYAN}                                          ║
║   {C.BWHITE}  🌐 TARGET : {C.BWHITE}tapminings.com{C.BCYAN}                                 ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
{C.RESET}""")


# ================= LOGGER WARNA ========================
class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG:    C.CYAN,
        logging.INFO:     C.BGREEN,
        logging.WARNING:  C.BYELLOW,
        logging.ERROR:    C.BRED,
        logging.CRITICAL: C.BMAGENTA,
    }
    ICONS = {
        logging.DEBUG:    "🔧",
        logging.INFO:     "ℹ ",
        logging.WARNING:  "⚠ ",
        logging.ERROR:    "✖ ",
        logging.CRITICAL: "☠ ",
    }
    def format(self, record):
        warna_level = self.COLORS.get(record.levelno, C.WHITE)
        ikon = self.ICONS.get(record.levelno, "•")
        waktu = f"{C.DIM}[{self.formatTime(record, '%H:%M:%S')}]{C.RESET}"
        level = warna(f"{ikon} {record.levelname:<7}", warna_level, C.BOLD)
        pesan = f"{C.BWHITE}{record.getMessage()}{C.RESET}"
        return f"{waktu} {level} │ {pesan}"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColorFormatter())
log = logging.getLogger("tapmining")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False


# ================= HEADERS ==============================
HEADERS_DASAR = {
    "User-Agent": ("Mozilla/5.0 (Linux; Android 12; Infinix X6817 Build/SP1A.210812.016; wv) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                   "Chrome/156.0.8078.47 Mobile Safari/537.36"),
    "Accept": "*/*",
    "X-Requested-With": "qzbr.zpr.pt",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": BASE_URL,
}


# ================= INPUT TERMINAL ======================
def input_credentials():
    """Minta email & password dari user di terminal."""
    print(warna("╭─[ LOGIN AKUN ]──────────────────────────────────────╮", C.BCYAN, C.BOLD))
    email = input(warna("│ 📧 Gmail    : ", C.BYELLOW, C.BOLD)).strip()
    password = getpass.getpass(warna("│ 🔒 Password : ", C.BYELLOW, C.BOLD))
    print(warna("╰─────────────────────────────────────────────────────╯", C.BCYAN))

    if not email or not password:
        print(warna("\n  ✖ Email / password tidak boleh kosong!\n", C.BRED, C.BOLD))
        sys.exit(1)
    return email, password


def input_konfigurasi():
    """Minta konfigurasi klaim dari user."""
    print(warna("╭─[ KONFIGURASI KLAIM ]───────────────────────────────╮", C.BCYAN, C.BOLD))
    try:
        diamonds = int(input(warna("│ 💎 Diamond per claim [200]: ", C.BYELLOW)) or "200")
        jumlah   = int(input(warna("│ 🔁 Jumlah klaim [5]: ",       C.BYELLOW)) or "5")
        jeda     = int(input(warna("│ ⏳ Jeda (detik) [60]: ",      C.BYELLOW)) or "60")
    except ValueError:
        print(warna("│ ⚠  Input tidak valid, pakai default", C.BRED))
        diamonds, jumlah, jeda = 200, 5, 60
    print(warna("╰─────────────────────────────────────────────────────╯", C.BCYAN))

    if diamonds <= 0 or jumlah <= 0:
        print(warna("\n  ✖ Diamond & jumlah klaim harus > 0!\n", C.BRED, C.BOLD))
        sys.exit(1)

    total = jumlah * diamonds
    print(warna(f"\n  ▶ Target: {jumlah}× × {diamonds}💎 = {total}💎 total\n",
                C.BMAGENTA, C.BOLD))
    return diamonds, jumlah, jeda


# ================= API =================================
def login(session, email, password):
    headers = {**HEADERS_DASAR,
               "Content-Type": "application/json",
               "Referer": f"{BASE_URL}/login.html"}
    try:
        r = session.post(
            f"{BASE_URL}/api/auth.php",
            params={"action": "login"},
            headers=headers,
            json={"email": email, "password": password},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error(f"Login error: {e}")
        return None

    token = data.get("token")
    if not token:
        log.error(warna(f"Login gagal: {data}", C.BRED, C.BOLD))
        return None

    user = data.get("user", {})
    log.info(warna(f"Login sukses → id={user.get('id')} name={user.get('name')}",
                   C.BGREEN, C.BOLD))
    return token


def get_notifikasi(session):
    headers = {**HEADERS_DASAR, "Referer": f"{BASE_URL}/home.html"}
    r = session.get(f"{BASE_URL}/api/notif.php",
                    params={"action": "get_all"},
                    headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def klaim_reward(session, token, diamonds, points, questions):
    headers = {**HEADERS_DASAR,
               "Authorization": f"Bearer {token}",
               "Content-Type": "application/json",
               "Referer": f"{BASE_URL}/home.html"}
    r = session.post(
        f"{BASE_URL}/api/user.php",
        params={"action": "add_rewards"},
        headers=headers,
        json={"points": points, "diamonds": diamonds, "questions": questions},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


# ================= RINGKASAN ===========================
def ringkasan(sukses, gagal, total_diamond):
    print(warna("\n╔══════════════ RINGKASAN ══════════════╗", C.BCYAN, C.BOLD))
    print(f"  {warna('✅ Sukses', C.BGREEN, C.BOLD)} : {sukses} klaim")
    print(f"  {warna('❌ Gagal ', C.BRED,   C.BOLD)} : {gagal} klaim")
    print(f"  {warna('💎 Total ', C.BYELLOW, C.BOLD)} : {total_diamond} diamond")
    print(warna("╚═══════════════════════════════════════╝", C.BCYAN, C.BOLD))
    print(warna(f"  👑 Owner: Sains Zama\n", C.BMAGENTA, C.BOLD))


# ================= MAIN ================================
def main():
    banner()

    # 1) Input kredensial
    email, password = input_credentials()

    # 2) Input konfigurasi
    diamonds, jumlah, jeda = input_konfigurasi()

    # 3) Mulai sesi
    with requests.Session() as s:
        token = login(s, email, password)
        if not token:
            return

        # Ambil notifikasi (opsional)
        try:
            notif = get_notifikasi(s)
            log.info(f"Notifikasi aktif: {len(notif.get('items', []))}")
            for n in notif.get("items", [])[:3]:
                print(f"     {warna('📢', C.BYELLOW)} {warna(n['title'], C.BWHITE)}")
        except Exception as e:
            log.warning(f"Gagal ambil notifikasi: {e}")

        sukses = gagal = 0

        for i in range(1, jumlah + 1):
            print(warna(f"\n─── Klaim {i}/{jumlah} ───", C.BCYAN, C.BOLD))
            try:
                resp = klaim_reward(s, token,
                                    diamonds=diamonds,
                                    points=POINTS_PER_CLAIM,
                                    questions=QUESTIONS_PER_CLAIM)
                if resp.get("ok"):
                    sukses += 1
                    log.info(warna(f"+{diamonds}💎 diterima", C.BGREEN, C.BOLD))
                else:
                    gagal += 1
                    log.warning(f"Respon: {resp}")
            except Exception as e:
                gagal += 1
                log.error(f"Error: {e}")

            if i < jumlah:
                for sisa in range(jeda, 0, -1):
                    print(f"\r   {warna('⏳', C.BYELLOW)} Tunggu {sisa:>3}s ...",
                          end="", flush=True)
                    time.sleep(1)
                print()

        ringkasan(sukses, gagal, sukses * diamonds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(warna("\n\n  ⛔ Dibatalkan oleh user.\n", C.BRED, C.BOLD))