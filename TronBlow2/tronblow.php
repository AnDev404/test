<?php
error_reporting(0);
date_default_timezone_set('Asia/Jakarta');

// ======================= KONFIGURASI =======================
$CONFIG_FILE   = __DIR__ . "/tronblow_config.json";
$LAST_RESPONSE = __DIR__ . "/last_response.html";

$UA = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36';

// ======================= WARNA =======================
const GOLD          = "\033[38;5;220m";
const L_GOLD        = "\033[1;33m";
const GREEN         = "\033[1;32m";
const CYAN          = "\033[1;36m";
const RED           = "\033[1;31m";
const WHITE         = "\033[1;37m";
const ORANGE        = "\033[38;5;208m";
const L_ORANGE      = "\033[1;38;5;208m";
const YELLOW        = "\033[1;33m";
const BRIGHT_YELLOW = "\033[38;5;226m"; // Kuning Terang
const PASTEL_GREEN  = "\033[38;5;120m"; // Hijau Pastel Soft (Diperbarui)
const SOFT_WHITE    = "\033[0;37m";     // Putih Soft
const RESET         = "\033[0m";
const BOLD          = "\033[1m";

// ======================= FUNGSI UI =======================
// UBAH ANGKA 25000 DI BAWAH INI UNTUK MENGATUR KECEPATAN KETIK
function typewrite($text, $speed = 25000) {
    $len = mb_strlen($text);
    for ($i = 0; $i < $len; $i++) {
        echo mb_substr($text, $i, 1);
        @ob_flush(); @flush();
        usleep($speed);
    }
    echo "\n";
}

function clear() {
    (PHP_OS == "Linux") ? system('clear') : pclose(popen('cls', 'w'));
}

// Fungsi bantuan buat nengahin teks
function center_text($text, $width = 39) {
    // Hapus kode warna buat ngitung panjang teks asli
    $clean_text = preg_replace('/\x1b\[[0-9;]*m/', '', $text);
    $text_len = mb_strlen($clean_text);
    $spaces = floor(($width - $text_len) / 2);
    return str_repeat(" ", max(0, $spaces)) . $text;
}

function hacker_intro() {
    clear();
    echo CYAN;
    typewrite("[+] Initializing TronBlow Protocol...");
    typewrite("[+] Bypassing LiteSpeed Security...");
    typewrite("[+] System Ready & Online!");
    echo RESET . "\n";
}

function banner() {
    clear();
    echo "\n";
    
    // Banner ASCII TRON (Gradasi Cyan)
    $lines = [
        "   ████████╗██████╗  ██████╗ ███╗   ██╗",
        "   ╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║",
        "      ██║   ██████╔╝██║   ██║██╔██╗ ██║",
        "      ██║   ██╔══██╗██║   ██║██║╚██╗██║",
        "      ██║   ██║  ██║╚██████╔╝██║ ╚████║",
        "      ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"
    ];
    
    $colors = ["\033[38;5;30m", "\033[38;5;36m", "\033[38;5;44m", "\033[38;5;51m"];
    
    foreach ($lines as $line) {
        $len = mb_strlen($line);
        for ($i = 0; $i < $len; $i++) {
            $char = mb_substr($line, $i, 1);
            if ($char === ' ') {
                echo $char;
            } else {
                $color_idx = (int)floor(($i / $len) * (count($colors) - 1));
                echo $colors[$color_idx] . $char;
            }
        }
        echo RESET . "\n";
    }
    
    echo "\n";
    // Lebar banner ASCII di atas adalah 39 karakter
    echo center_text("\033[1;36mTRON BLOW AUTO FAUCET\033[0m", 39) . "\n";
    echo center_text("\033[1;37mMod by \033[1;33mJendela Semesta \033[1;31mREBORN\033[0m", 39) . "\n";
    echo center_text("\033[1;37mJoin my Group Telegram\033[0m", 39) . "\n";
    echo center_text("\033[1;33mhttps://t.me/jendelasemesta\033[0m", 39) . "\n";
    
    echo "\033[38;5;30m  ───────────────────────────────────────\033[0m\n\n";
}

function timer($seconds, $text = "Next claim") {
    $frames = ["0101", "1010", "1100", "0011"];
    $start = time();
    $i = 0;
    while (time() - $start < $seconds) {
        $remaining = $seconds - (time() - $start);
        echo "\r" . WHITE . $text . " (" . $remaining . "s) " . CYAN . $frames[$i % 4] . RESET . "   ";
        usleep(250000);
        $i++;
    }
    // Log waktu siap claim pakai warna Cyan
    echo "\r" . WHITE . "[" . date("H:i:s") . "] " . CYAN . "🌱 Siap claim lagi! " . str_repeat(" ", 40) . RESET . "\n";
}

// ======================= CURL =======================
function fetch_page($url, $ua, $raw_cookie) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_SSL_VERIFYHOST => false,
        CURLOPT_USERAGENT      => $ua,
        CURLOPT_HTTPHEADER     => [
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language: en-US,en;q=0.9,id-ID;q=0.8,id;q=0.7',
            'Cache-Control: no-cache',
            'Pragma: no-cache',
            'Cookie: ' . $raw_cookie
        ],
    ]);
    $html = curl_exec($ch);
    curl_close($ch);
    return $html ?: '';
}

function submit_claim($url, $email, $csrf, $ans, $ua, $raw_cookie) {
    $postData = http_build_query([
        'action'      => 'claim',
        'csrf_token'  => $csrf,
        'website'     => '',
        'email'       => $email,
        'math_answer' => $ans,
    ]);

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $postData,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_SSL_VERIFYHOST => false,
        CURLOPT_USERAGENT      => $ua,
        CURLOPT_HTTPHEADER     => [
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Content-Type: application/x-www-form-urlencoded',
            'Origin: ' . rtrim($url, '/'),
            'Referer: ' . $url,
            'Cookie: ' . $raw_cookie
        ],
    ]);

    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    return ['body' => $body ?: '', 'code' => $code];
}

// ======================= PARSER =======================
function extract_csrf_token(string $html): ?string {
    if (preg_match('/name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']/i', $html, $m)) {
        return $m[1];
    }
    return null;
}

function extract_math_question(string $html): ?array {
    if (!preg_match('/<div\s+class=["\'][^"\']*captcha-q[^"\']*["\'][^>]*>(.*?)<\/div>/is', $html, $m)) {
        return null;
    }
    $text = strip_tags($m[1]);
    $text = html_entity_decode($text, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = str_replace(['−', '–', '—', '‐', '‑', '‒', '&minus;'], '-', $text);
    $text = str_replace(['×', '&times;'], '*', $text);
    $text = str_replace(['÷', '&divide;'], '/', $text);

    if (preg_match('/what\s+is\s+(-?\d+)\s*([+\-*\/%])\s*(-?\d+)\s*=\s*\?/i', $text, $m)) {
        return ['q1' => (int)$m[1], 'op' => $m[2], 'q2' => (int)$m[3]];
    }
    return null;
}

function solve_math(array $math): int {
    switch ($math['op']) {
        case '+': return $math['q1'] + $math['q2'];
        case '-': return $math['q1'] - $math['q2'];
        case '*': return $math['q1'] * $math['q2'];
        case '/': return $math['q2'] != 0 ? (int)($math['q1'] / $math['q2']) : 0;
        case '%': return $math['q2'] != 0 ? $math['q1'] % $math['q2'] : 0;
        default:  return 0;
    }
}

function extract_cooldown_end(string $html): ?int {
    if (preg_match('/var\s+endAt\s*=\s*(\d{10,})\s*\*\s*1000/i', $html, $m)) {
        return (int)$m[1];
    }
    return null;
}

// ======================= MAIN =======================
hacker_intro();
banner();

$config = file_exists($CONFIG_FILE) ? (json_decode(file_get_contents($CONFIG_FILE), true) ?: []) : [];
$config['base_url'] = $config['base_url'] ?? 'https://tronblow.site';

// 1. Input Email
if (empty($config['email'])) {
    echo WHITE . "Masukkan Email FaucetPay: " . RESET;
    $config['email'] = trim(fgets(STDIN));
}

// 2. Input Cookie
if (empty($config['raw_cookie'])) {
    echo "\n" . YELLOW . "=====================================================" . RESET . "\n";
    echo YELLOW . "⚠️  WEB DILINDUNGI BOT VERIFICATION (LiteSpeed) ⚠️" . RESET . "\n";
    echo WHITE . "1. Buka tronblow.site di Chrome HP." . RESET . "\n";
    echo WHITE . "2. Centang 'I'm not a robot' sampai halaman utama muncul." . RESET . "\n";
    echo WHITE . "3. Copy Header 'Cookie' dari aplikasi Cookie Editor." . RESET . "\n";
    echo YELLOW . "=====================================================" . RESET . "\n";
    echo CYAN . "Paste Cookie di sini: \n" . RESET;
    echo "> ";
    $config['raw_cookie'] = trim(fgets(STDIN));
}

file_put_contents($CONFIG_FILE, json_encode($config, JSON_PRETTY_PRINT));

echo "\n" . WHITE . " Account  : " . "\033[38;5;51m" . $config['email'] . RESET . "\n";
echo WHITE . " Cookie   : " . PASTEL_GREEN . "[ Tersimpan ]" . RESET . "\n\n";

$total_claims = 0;

while (true) {
    // GET halaman pakai cookie
    $html = fetch_page($config['base_url'], $UA, $config['raw_cookie']);

    // Cek apakah masih kena tembok Bot Verification
    if (strpos($html, 'Bot Verification') !== false || strpos($html, 'lsrecaptcha-form') !== false) {
        file_put_contents($LAST_RESPONSE, $html);
        typewrite(RED . "🛑 Cookie Expired / Kena Tembok reCAPTCHA!");
        typewrite(YELLOW . "Silakan buka Chrome, centang recaptcha, copy Cookie barunya, lalu HAPUS file tronblow_config.json dan jalankan script ini lagi.");
        exit(1);
    }

    // Cek Cooldown
    $pre_cd = extract_cooldown_end($html);
    if ($pre_cd && $pre_cd > time()) {
        $wait = $pre_cd - time();
        typewrite(CYAN . "⏳ Cooldown aktif. Menunggu {$wait}s (dari server)...");
        timer($wait, "Cooldown");
        typewrite(SOFT_WHITE . "--------------------------------------------------------------");
        continue;
    }

    $csrf = extract_csrf_token($html);
    $math = extract_math_question($html);

    if (!$csrf || !$math) {
        file_put_contents($LAST_RESPONSE, $html);
        typewrite(RED . "❌ Gagal parse CSRF/captcha. Cek last_response.html");
        sleep(5);
        continue;
    }

    $ans = solve_math($math);
    $log = WHITE . "[" . date("H:i:s") . "] ";
    
    // Log Captcha (Kuning Terang)
    typewrite($log . BRIGHT_YELLOW . "Bot belajar Berhitung  {$math['q1']} {$math['op']} {$math['q2']} = {$ans}😁" . RESET);

    // POST Claim
    $result = submit_claim($config['base_url'], $config['email'], $csrf, $ans, $UA, $config['raw_cookie']);
    $body = strtolower($result['body']);

    if (strpos($body, 'alert-success') !== false || strpos($body, 'sent to your faucetpay') !== false) {
        $total_claims++;
        // Log Sukses 1 & 2 (Hijau Pastel Soft)
        typewrite($log . PASTEL_GREEN . "✅ BERHASIL!! Total: {$total_claims}" . RESET);
        // Geser kiri 1 spasi (sekarang cuma pakai 1 spasi setelah emoji)
        typewrite($log . PASTEL_GREEN . "✅ 0.00001000 Dikirim ke FaucetPay" . RESET);
        
        $post_cd = extract_cooldown_end($result['body']);
        if ($post_cd && $post_cd > time()) {
            timer($post_cd - time(), "Next claim");
        } else {
            timer(65, "Next claim");
        }
        
        // Garis pemisah (Putih Soft)
        typewrite(SOFT_WHITE . "--------------------------------------------------------------");
    } 
    elseif (strpos($body, 'security token expired') !== false) {
        typewrite($log . YELLOW . "⚠ Token expired, retry..." . RESET);
        usleep(500000); // Jeda 0.5 detik
    }
    else {
        typewrite($log . RED . "❌ Gagal claim. Cek last_response.html" . RESET);
        file_put_contents($LAST_RESPONSE, $result['body']);
        sleep(5);
    }
}