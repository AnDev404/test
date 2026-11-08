import requests
import time
import sys
import os
import random
import string
from datetime import datetime

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
BASE_URL       = "https://thecryptotaxi.com"
API_LOGIN      = f"{BASE_URL}/api/auth/login"
API_STATE      = f"{BASE_URL}/api/state"
API_START_TRIP = f"{BASE_URL}/api/trips/start"

# Warna
C_OK    = Fore.GREEN  + Style.BRIGHT
C_ERR   = Fore.RED    + Style.BRIGHT
C_WARN  = Fore.YELLOW + Style.BRIGHT
C_INFO  = Fore.CYAN   + Style.BRIGHT
C_DIM   = Fore.WHITE  + Style.DIM
C_MAG   = Fore.MAGENTA + Style.BRIGHT
C_BLUE  = Fore.BLUE   + Style.BRIGHT
C_RESET = Style.RESET_ALL

LINE = "─"


# ================= RANDOM PROFILE =================
# Kumpulan User-Agent netral (Android, iOS, Windows, macOS) — tidak terkait device pribadi
USER_AGENTS = [
    # Android - Chrome
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; V2116) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    # iOS - Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    # Desktop - Chrome (Windows / Mac)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Desktop - Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,id;q=0.8",
    "es-ES,es;q=0.9,en;q=0.8",
]


def random_device_id() -> str:
    """Generate x-ct-device acak (format menyerupai aslinya)."""
    hex1 = "".join(random.choices("0123456789abcdef", k=32))
    hex2 = "".join(random.choices("0123456789abcdef", k=64))
    return f"{hex1}.{hex2}"


def pick_profile() -> dict:
    """Pilih profil acak (UA + device + lang) yang konsisten untuk satu sesi."""
    return {
        "user_agent": random.choice(USER_AGENTS),
        "device_id":  random_device_id(),
        "lang":       random.choice(ACCEPT_LANGUAGES),
    }


# ================= UI HELPERS =================
def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print()
    print(C_INFO + "  ╔═══════════════════════════════════════════════════╗")
    print(C_INFO + "  ║" + C_MAG  + "          THE CRYPTO TAXI  —  AUTO BOT             " + C_INFO + "║")
    print(C_INFO + "  ║" + C_BLUE + "          Owner : SainsZama                        " + C_INFO + "║")
    print(C_INFO + "  ╚═══════════════════════════════════════════════════╝" + C_RESET)
    print()


def section(title):
    print()
    print(C_INFO + f"  ┌── {title} " + LINE * (44 - len(title)) + "┐" + C_RESET)


def section_end():
    print(C_INFO + "  └" + LINE * 49 + "┘" + C_RESET)


def info(label, value, color=C_RESET):
    print(f"  {C_DIM}│{C_RESET} {label:<14}: {color}{value}{C_RESET}")


def spinner(msg, seconds=1.0):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end = time.time() + seconds
    i = 0
    while time.time() < end:
        sys.stdout.write(f"\r  {C_INFO}{frames[i % len(frames)]}{C_RESET} {msg}")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1
    sys.stdout.write(f"\r  {C_OK}✓{C_RESET} {msg}   \n")
    sys.stdout.flush()


def progress_bar(current, total, width=28, label=""):
    total = max(total, 1)
    frac  = max(0, min(current / total, 1))
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    color = C_OK if frac > 0.5 else (C_WARN if frac > 0.2 else C_ERR)
    sys.stdout.write(
        f"\r  {C_INFO}⏳{C_RESET} {label} "
        f"{color}{bar}{C_RESET} {int(frac*100):3d}%  "
    )
    sys.stdout.flush()


def fmt_ts(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S")


# ================= INPUT =================
def input_config() -> dict:
    banner()
    section("LOGIN")
    username = input(f"  {C_DIM}│{C_RESET} 👤 {C_INFO}Username{C_RESET} : ").strip()
    import getpass
    password = getpass.getpass(f"  {C_DIM}│{C_RESET} 🔑 {C_INFO}Password{C_RESET} : ").strip()
    section_end()
    if not username or not password:
        print(C_ERR + "  ❌ Username & password wajib diisi." + C_RESET)
        sys.exit(1)
    return {"username": username, "password": password}


# ================= SESSION =================
def create_session(profile: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "user-agent":      profile["user_agent"],
        "x-ct-device":     profile["device_id"],
        "content-type":    "application/json",
        "x-ct":            "1",
        "x-ct-lang":       "en",
        "accept":          "*/*",
        "origin":          BASE_URL,
        "x-requested-with": "qzbr.zpr.pt",
        "referer":         f"{BASE_URL}/",
        "accept-language": profile["lang"],
    })
    return s


def login(s: requests.Session, username: str, password: str) -> bool:
    try:
        r = s.post(API_LOGIN, json={"username": username, "password": password}, timeout=15)
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"  {C_ERR}❌ Login gagal (HTTP {e.response.status_code}): "
              f"{e.response.text[:120]}{C_RESET}")
        return False
    if not r.json().get("ok"):
        print(f"  {C_ERR}❌ Login ditolak: {r.text[:120]}{C_RESET}")
        return False
    if "__Host-ct_s" not in s.cookies:
        print(f"  {C_ERR}❌ Cookie tidak diterima.{C_RESET}")
        return False
    return True


# ================= API =================
def get_state(s):
    r = s.post(API_STATE, json={}, timeout=15)
    r.raise_for_status()
    return r.json()


def start_trip(s, car_id):
    r = s.post(API_START_TRIP, json={"carId": str(car_id)}, timeout=15)
    r.raise_for_status()
    return r.json()


def find_car(state, car_id):
    for c in state.get("myCars", []) + state.get("rentedCars", []):
        if str(c.get("id")) == str(car_id):
            return c
    return None


# ================= AUTO LOOP =================
def auto_loop(s, car_id, interval=5):
    print()
    print(C_INFO + "  ┌─────────────────────────────────────────────────┐")
    print(C_INFO + "  │" + C_MAG + "   🔁 AUTO LOOP AKTIF — Ctrl+C untuk berhenti    " + C_INFO + "│")
    print(C_INFO + "  └─────────────────────────────────────────────────┘" + C_RESET)
    print()

    total_earn = 0.0
    total_trip = 0
    n = 0

    while True:
        n += 1
        try:
            mobil = find_car(get_state(s), car_id)

            if not mobil:
                print(f"  {C_ERR}[{n}] ❌ Mobil tidak ditemukan.{C_RESET}")
                time.sleep(interval)
                continue

            if mobil.get("broken"):
                print(f"  {C_ERR}[{n}] ⚠️  Mobil rusak. STOP.{C_RESET}")
                break

            trip  = mobil.get("trip")
            now   = int(time.time() * 1000)
            quota = mobil.get("quota", {})

            if trip and trip.get("endsAt", 0) > now:
                total = trip["endsAt"] - trip["startedAt"]
                done  = now - trip["startedAt"]
                label = f"🚖 Trip #{trip['id']}  (selesai {fmt_ts(trip['endsAt'])})"
                progress_bar(done, total, label=label)
                sisa = (trip["endsAt"] - now) / 1000
                time.sleep(min(sisa + 0.5, 2))
                continue

            if quota.get("left", 0) <= 0:
                print(f"\n  {C_WARN}[{n}] ❌ Quota habis "
                      f"({quota.get('used')}/{quota.get('limit')}). STOP.{C_RESET}")
                break

            if not mobil.get("canDrive") and mobil.get("block"):
                blk = mobil["block"]
                print(f"  {C_WARN}[{n}] 🚫 {blk.get('code')}: {blk.get('msg')}{C_RESET}")
                time.sleep(interval)
                continue

            print()
            print(f"  {C_INFO}[{n}] ▶️  Start trip {mobil['name']} ({mobil['plate']})...{C_RESET}")

            res = start_trip(s, car_id)
            t   = res.get("trip") or res.get("car", {}).get("trip")
            if t:
                earn = float(t.get("earning") or 0)
                total_earn += earn
                total_trip += 1
                print(f"       {C_OK}✅ Trip #{t['id']}  "
                      f"selesai {fmt_ts(t['endsAt'])}  "
                      f"+{earn:.4f} USDT{C_RESET}")
                print(f"       {C_DIM}Quota: {quota.get('used',0)+1}/{quota.get('limit')} "
                      f"| Total: {total_trip} trip | {total_earn:.4f} USDT{C_RESET}")
            else:
                blk = (res.get("car") or {}).get("block") or res.get("block") or {}
                print(f"       {C_WARN}⚠️  Gagal: {blk.get('code')} - {blk.get('msg')}{C_RESET}")
                time.sleep(interval)

        except requests.HTTPError as e:
            print(f"\n  {C_ERR}[{n}] ❌ HTTP {e.response.status_code}: "
                  f"{e.response.text[:150]}{C_RESET}")
            if e.response.status_code in (401, 403):
                print(f"  {C_WARN}⚠️  Sesi expired — jalankan ulang script.{C_RESET}")
                break
            time.sleep(interval * 2)

        except KeyboardInterrupt:
            print(f"\n\n  {C_INFO}👋 Dihentikan user.{C_RESET}")
            print(f"  {C_OK}📊 Total: {total_trip} trip | {total_earn:.4f} USDT{C_RESET}\n")
            return

        except Exception as e:
            print(f"\n  {C_ERR}[{n}] ❌ Error: {e}{C_RESET}")
            time.sleep(interval * 2)

        time.sleep(interval)


# ================= MAIN =================
def main():
    clear()
    cfg = input_config()

    # Profil acak tiap kali run (UA + device + lang)
    profile = pick_profile()
    s = create_session(profile)

    print()
    spinner("Menghubungi server...", 0.8)
    spinner("Login...", 0.6)

    if not login(s, cfg["username"], cfg["password"]):
        sys.exit(1)

    cookie_preview = s.cookies.get("__Host-ct_s", "")[:16]
    print(f"  {C_OK}✅ Login sukses{C_RESET}  {C_DIM}(cookie: {cookie_preview}...){C_RESET}")
    print(f"  {C_DIM}🆔 Device ID : {profile['device_id'][:24]}...{C_RESET}")

    spinner("Mengambil state akun...", 0.6)

    try:
        state = get_state(s)
    except requests.HTTPError as e:
        print(f"  {C_ERR}❌ Gagal /api/state: {e.response.status_code}{C_RESET}")
        sys.exit(1)

    me    = state.get("me", {})
    bal   = state.get("balances", {})
    stats = state.get("stats", {})

    section("PROFIL")
    info("👤 Username", me.get("username"), C_MAG)
    info("🆔 User ID",  me.get("id"),      C_RESET)
    info("💰 Saldo",    f"{bal.get('usdt', 0)} USDT", C_OK)
    info("🏆 Total trip", f"{stats.get('trips')} trip  "
                          f"({stats.get('usdtEarned')} USDT)", C_BLUE)
    info("🌐 Online",   f"{state.get('online')} / {state.get('registered')}", C_RESET)
    section_end()

    my_cars = state.get("myCars", [])
    if not my_cars:
        print(f"  {C_ERR}❌ Tidak ada mobil di akun ini.{C_RESET}")
        sys.exit(1)

    section("MOBIL")
    if len(my_cars) == 1:
        chosen = my_cars[0]
        q = chosen.get("quota", {})
        info("🚖 Nama",  f"{chosen['name']} ({chosen['plate']})", C_MAG)
        info("🆔 Car ID", chosen["id"], C_RESET)
        info("📊 Quota", f"{q.get('used')}/{q.get('limit')}  shift {q.get('shift')}", C_WARN)
    else:
        for i, c in enumerate(my_cars, 1):
            q = c.get("quota", {})
            print(f"  {C_DIM}│{C_RESET} {i}. {C_MAG}{c['name']}{C_RESET} "
                  f"({c['plate']}) id={c['id']} "
                  f"| quota {q.get('used')}/{q.get('limit')}")
        idx = input(f"  {C_DIM}│{C_RESET} Pilih mobil [1-{len(my_cars)}]: ").strip()
        try:
            chosen = my_cars[int(idx) - 1]
        except (ValueError, IndexError):
            print(f"  {C_ERR}❌ Pilihan tidak valid.{C_RESET}")
            sys.exit(1)
    section_end()

    car_id = str(chosen["id"])

    print()
    print(C_INFO + "  ┌─────────────────────────────────────────────────┐")
    print(C_INFO + "  │" + C_OK  + "   1. " + C_RESET + "▶️   Start trip SEKALI                     " + C_INFO + "│")
    print(C_INFO + "  │" + C_MAG + "   2. " + C_RESET + "🔁  AUTO loop (start terus-menerus)       " + C_INFO + "│")
    print(C_INFO + "  │" + C_ERR + "   3. " + C_RESET + "🚪  Keluar                                " + C_INFO + "│")
    print(C_INFO + "  └─────────────────────────────────────────────────┘" + C_RESET)
    mode = input(f"\n  {C_INFO}➤ Pilihan [1/2/3]{C_RESET}: ").strip()

    if mode == "1":
        print()
        spinner("Start trip...", 0.6)
        try:
            res  = start_trip(s, car_id)
            trip = res.get("trip")
            if trip:
                print(f"  {C_OK}✅ Trip #{trip['id']}  selesai {fmt_ts(trip['endsAt'])}  "
                      f"+{trip['earning']} USDT{C_RESET}\n")
            else:
                blk = (res.get("car") or {}).get("block") or {}
                print(f"  {C_WARN}⚠️  Tidak bisa start: {blk.get('code')} - {blk.get('msg')}{C_RESET}\n")
        except Exception as e:
            print(f"  {C_ERR}❌ {e}{C_RESET}\n")

    elif mode == "2":
        try:
            interval = int(input(f"  {C_DIM}Interval cek (detik, default 5): {C_RESET}").strip() or "5")
        except ValueError:
            interval = 5
        auto_loop(s, car_id, interval)

    else:
        print(f"\n  {C_INFO}👋 Bye!{C_RESET}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C_INFO}👋 Dibatalkan.{C_RESET}\n")
        sys.exit(0)