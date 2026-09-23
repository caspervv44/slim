#!/usr/bin/env perl
use strict;
use warnings;
use utf8;

use JSON::PP qw(encode_json decode_json);
use Digest::SHA qw(hmac_sha256 sha256_hex);
use Fcntl qw(:DEFAULT :flock);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use POSIX qw(strftime);

binmode STDOUT, ':encoding(UTF-8)';
binmode STDERR, ':encoding(UTF-8)';

# ---------------------------------------------------------------------------
# Aventus Wekker cloud-opslag
#
# Eén CGI-script voor:
#   - registratie van een nieuwe wekker;
#   - API pull/push met een aparte 256-bit device key;
#   - menselijke beheerpagina met gebruikersnaam + gehasht wachtwoord;
#   - wachtwoord wijzigen.
#
# MyX-tokens/feedlinks horen hier bewust NIET in.
# ---------------------------------------------------------------------------

my $MAX_BODY = 64 * 1024;
my $SESSION_TTL = 30 * 24 * 60 * 60;
my $PBKDF2_ITERATIONS = 100_000;
my $DATA_DIR = $ENV{WEKKER_DATA_DIR} || dirname(__FILE__) . '/.clock-data';
my $PUBLIC_URL = $ENV{WEKKER_PUBLIC_URL} || _detect_public_url();

_init_data_dir();

my $method = uc($ENV{REQUEST_METHOD} || 'GET');
my $content_type = lc($ENV{CONTENT_TYPE} || '');
my $body = '';

if ($method eq 'POST') {
    my $len = int($ENV{CONTENT_LENGTH} || 0);
    _json_error(413, 'request te groot') if $len > $MAX_BODY;
    if ($len > 0) {
        my $read = read(STDIN, $body, $len);
        _json_error(400, 'request kon niet worden gelezen') if !defined $read || $read != $len;
    }
}

if ($method eq 'POST' && $content_type =~ m{application/json}) {
    _handle_api($body);
    exit;
}

my %query = _parse_params($ENV{QUERY_STRING} || '');
my %form = $method eq 'POST' ? _parse_params($body) : ();
my $device_id = $form{d} || $query{d} || '';

if ($method eq 'POST' && ($form{action} || '') eq 'login') {
    _web_login($device_id, \%form);
    exit;
}
if ($method eq 'POST' && ($form{action} || '') eq 'save') {
    _web_save($device_id, \%form);
    exit;
}
if ($method eq 'POST' && ($form{action} || '') eq 'password') {
    _web_change_password($device_id, \%form);
    exit;
}
if ($method eq 'POST' && ($form{action} || '') eq 'logout') {
    _web_logout($device_id);
    exit;
}

_show_management_page($device_id);

# ---------------------------------------------------------------------------
# API

sub _handle_api {
    my ($raw) = @_;
    my $req;
    eval { $req = decode_json($raw || '{}'); 1 } or _json_error(400, 'ongeldige JSON');
    _json_error(400, 'JSON-object verwacht') if ref($req) ne 'HASH';

    my $action = $req->{action} || '';
    if ($action eq 'register') {
        my $settings = $req->{settings};
        _validate_settings($settings);
        my $device_id = _random_hex(32);
        my $device_key = _random_hex(32);
        my $password = _random_password(16);
        my $salt = _random_hex(16);
        my $record = {
            schema_version => 1,
            device_id => $device_id,
            device_key_hash => sha256_hex($device_key),
            username => 'basis',
            password_salt => $salt,
            password_hash => _pbkdf2_hex($password, $salt, $PBKDF2_ITERATIONS),
            password_iterations => $PBKDF2_ITERATIONS,
            password_changed => JSON::PP::false,
            revision => 1,
            settings => $settings,
            created_at => _iso_now(),
            updated_at => _iso_now(),
            sessions => {},
            failed_logins => 0,
            locked_until => 0,
        };
        _create_record($device_id, $record);
        _json_ok({
            device_id => $device_id,
            device_key => $device_key,
            management_url => "$PUBLIC_URL?d=$device_id",
            username => 'basis',
            initial_password => $password,
            revision => 1,
        });
        return;
    }

    my $device = $ENV{HTTP_X_WEKKER_DEVICE} || '';
    my $key = $ENV{HTTP_X_WEKKER_KEY} || '';
    _valid_device_id($device) or _json_error(401, 'ongeldige device-authenticatie');

    _with_record($device, sub {
        my ($record) = @_;
        my $expected = $record->{device_key_hash} || '';
        _secure_eq(sha256_hex($key), $expected)
            or _json_error(401, 'ongeldige device-authenticatie');

        if ($action eq 'pull') {
            _json_ok({
                settings => $record->{settings},
                revision => int($record->{revision} || 0),
                password_changed => $record->{password_changed} ? JSON::PP::true : JSON::PP::false,
                updated_at => $record->{updated_at},
            });
            return 0;
        }

        if ($action eq 'push') {
            my $settings = $req->{settings};
            _validate_settings($settings);
            my $expected_revision = int($req->{expected_revision} // -1);
            my $current = int($record->{revision} || 0);
            if ($expected_revision != $current) {
                _json_error(409, 'instellingen zijn ondertussen elders gewijzigd');
            }
            $record->{settings} = $settings;
            $record->{revision} = $current + 1;
            $record->{updated_at} = _iso_now();
            _json_ok({ revision => $record->{revision} });
            return 1;
        }

        _json_error(400, 'onbekende API-actie');
    });
}

# ---------------------------------------------------------------------------
# Webbeheer

sub _show_management_page {
    my ($device_id) = @_;
    if (!_valid_device_id($device_id) || !_record_exists($device_id)) {
        _html(404, _page('Wekker niet gevonden', <<'HTML'));
<div class="card"><h1>Wekker niet gevonden</h1>
<p>Controleer de QR-code of de volledige beheerlink op het fysieke scherm.</p></div>
HTML
        return;
    }

    _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        if (!$session) {
            _html(200, _login_page($device_id));
            return 0;
        }
        _html(200, _settings_page($device_id, $record, $session));
        return 0;
    });
}

sub _web_login {
    my ($device_id, $form) = @_;
    (!_valid_device_id($device_id) || !_record_exists($device_id))
        and _html(404, _login_page($device_id, 'Wekker niet gevonden.'));

    _with_record($device_id, sub {
        my ($record) = @_;
        my $now = time();
        if (($record->{locked_until} || 0) > $now) {
            _html(429, _login_page($device_id, 'Te veel mislukte pogingen. Probeer over een minuut opnieuw.'));
            return 1;
        }

        my $username = $form->{username} // '';
        my $password = $form->{password} // '';
        my $salt = $record->{password_salt} || '';
        my $iterations = int($record->{password_iterations} || $PBKDF2_ITERATIONS);
        my $candidate = _pbkdf2_hex($password, $salt, $iterations);
        my $ok = _secure_eq($username, $record->{username} || '')
            && _secure_eq($candidate, $record->{password_hash} || '');

        if (!$ok) {
            $record->{failed_logins} = int($record->{failed_logins} || 0) + 1;
            if ($record->{failed_logins} >= 5) {
                $record->{locked_until} = $now + 60;
                $record->{failed_logins} = 0;
            }
            _html(401, _login_page($device_id, 'Gebruikersnaam of wachtwoord klopt niet.'));
            return 1;
        }

        $record->{failed_logins} = 0;
        $record->{locked_until} = 0;
        my $sid = _random_hex(32);
        my $csrf = _random_hex(24);
        $record->{sessions}{$sid} = {
            expires => $now + $SESSION_TTL,
            csrf => $csrf,
        };
        _prune_sessions($record);
        _redirect("$PUBLIC_URL?d=$device_id", "wekker_session=$sid; Path=/; Max-Age=$SESSION_TTL; Secure; HttpOnly; SameSite=Strict");
        return 1;
    });
}

sub _web_save {
    my ($device_id, $form) = @_;
    _valid_device_id($device_id) or _html(400, _page('Fout', '<div class="card">Ongeldige wekker-ID.</div>'));
    _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        _require_csrf($session, $form->{csrf});

        my $settings = $record->{settings};
        $settings->{alarm}{time} = _valid_time($form->{alarm_time}) ? $form->{alarm_time} : $settings->{alarm}{time};
        $settings->{alarm}{enabled} = $form->{alarm_enabled} ? JSON::PP::true : JSON::PP::false;
        $settings->{alarm}{snooze_minutes} = _clamp_int($form->{snooze_minutes}, 1, 60, 9);
        $settings->{lamp}{duration_after_button} = _clamp_int($form->{lamp_duration}, 1, 3600, 30);
        $settings->{display}{brightness} = _clamp_int($form->{brightness}, 0, 100, 80);

        my %zones = map { $_ => 1 } qw(Europe/Amsterdam Europe/Paris Europe/London Europe/Berlin UTC);
        $settings->{locale}{timezone} = $zones{$form->{timezone} || ''} ? $form->{timezone} : 'Europe/Amsterdam';
        $settings->{locale}{time_format} = ($form->{time_format} || '') eq '12h' ? '12h' : '24h';

        _validate_settings($settings);
        $record->{settings} = $settings;
        $record->{revision} = int($record->{revision} || 0) + 1;
        $record->{updated_at} = _iso_now();
        _redirect("$PUBLIC_URL?d=$device_id&saved=1");
        return 1;
    });
}

sub _web_change_password {
    my ($device_id, $form) = @_;
    _valid_device_id($device_id) or _html(400, _page('Fout', '<div class="card">Ongeldige wekker-ID.</div>'));
    _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        _require_csrf($session, $form->{csrf});

        my $new = $form->{new_password} // '';
        my $confirm = $form->{confirm_password} // '';
        if (length($new) < 12 || length($new) > 128 || $new ne $confirm) {
            _html(400, _settings_page($device_id, $record, $session, 'Wachtwoord moet 12–128 tekens zijn en beide velden moeten gelijk zijn.'));
            return 0;
        }
        my $salt = _random_hex(16);
        $record->{password_salt} = $salt;
        $record->{password_hash} = _pbkdf2_hex($new, $salt, $PBKDF2_ITERATIONS);
        $record->{password_iterations} = $PBKDF2_ITERATIONS;
        $record->{password_changed} = JSON::PP::true;
        # Andere browsers worden uitgelogd; deze sessie blijft bestaan.
        my $keep = $record->{sessions}{$sid};
        $record->{sessions} = { $sid => $keep };
        $record->{updated_at} = _iso_now();
        _redirect("$PUBLIC_URL?d=$device_id&password=1");
        return 1;
    });
}

sub _web_logout {
    my ($device_id) = @_;
    if (_valid_device_id($device_id) && _record_exists($device_id)) {
        _with_record($device_id, sub {
            my ($record) = @_;
            my ($sid) = _current_session($record);
            delete $record->{sessions}{$sid} if $sid;
            _redirect("$PUBLIC_URL?d=$device_id", "wekker_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict");
            return 1;
        });
    }
    _redirect($PUBLIC_URL, "wekker_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict");
}

# ---------------------------------------------------------------------------
# HTML

sub _login_page {
    my ($device_id, $error) = @_;
    my $msg = $error ? '<div class="notice bad">' . _h($error) . '</div>' : '';
    return _page('Inloggen', qq{
<div class="shell small-shell">
  <div class="brand">Aventus Wekker</div>
  <div class="card">
    <h1>Online beheer</h1>
    <p class="muted">Log in met de gegevens die op het scherm van je wekker staan.</p>
    $msg
    <form method="post" autocomplete="on">
      <input type="hidden" name="action" value="login">
      <input type="hidden" name="d" value="@{[_h($device_id)]}">
      <label>Gebruikersnaam<input name="username" autocomplete="username" required></label>
      <label>Wachtwoord<input type="password" name="password" autocomplete="current-password" required></label>
      <button class="primary" type="submit">Inloggen</button>
    </form>
  </div>
</div>});
}

sub _settings_page {
    my ($device_id, $r, $session, $error) = @_;
    my $s = $r->{settings};
    my $csrf = _h($session->{csrf} || '');
    my $checked = $s->{alarm}{enabled} ? ' checked' : '';
    my $saved = ($ENV{QUERY_STRING} || '') =~ /(?:^|&)saved=1(?:&|$)/
        ? '<div class="notice ok">Instellingen opgeslagen. De wekker haalt ze automatisch op.</div>' : '';
    my $pw = ($ENV{QUERY_STRING} || '') =~ /(?:^|&)password=1(?:&|$)/
        ? '<div class="notice ok">Wachtwoord gewijzigd.</div>' : '';
    my $err = $error ? '<div class="notice bad">' . _h($error) . '</div>' : '';

    my @zones = (
        ['Europe/Amsterdam', 'Amsterdam · CET/CEST'],
        ['Europe/Paris', 'Parijs · CET/CEST'],
        ['Europe/London', 'Londen · GMT/BST'],
        ['Europe/Berlin', 'Berlijn · CET/CEST'],
        ['UTC', 'UTC'],
    );
    my $zone_options = join '', map {
        my ($value, $label) = @$_;
        my $selected = ($s->{locale}{timezone} || '') eq $value ? ' selected' : '';
        '<option value="' . _h($value) . '"' . $selected . '>' . _h($label) . '</option>'
    } @zones;
    my $fmt24 = ($s->{locale}{time_format} || '24h') eq '24h' ? ' selected' : '';
    my $fmt12 = ($s->{locale}{time_format} || '') eq '12h' ? ' selected' : '';

    return _page('Instellingen', qq{
<div class="shell">
<header><div><div class="brand">Aventus Wekker</div><div class="muted">Veilig online beheer</div></div>
<form method="post"><input type="hidden" name="action" value="logout"><input type="hidden" name="d" value="@{[_h($device_id)]}"><button>Uitloggen</button></form></header>
$saved$pw$err
<div class="grid">
<section class="card">
<h2>Wekker</h2>
<form method="post">
<input type="hidden" name="action" value="save"><input type="hidden" name="d" value="@{[_h($device_id)]}"><input type="hidden" name="csrf" value="$csrf">
<label>Wektijd<input type="time" name="alarm_time" value="@{[_h($s->{alarm}{time} || '07:30')]}" required></label>
<label class="check"><input type="checkbox" name="alarm_enabled" value="1"$checked> Alarm ingeschakeld</label>
<label>Snooze (minuten)<input type="number" min="1" max="60" name="snooze_minutes" value="@{[int($s->{alarm}{snooze_minutes} || 9)]}"></label>
<label>Lampduur na knop (seconden)<input type="number" min="1" max="3600" name="lamp_duration" value="@{[int($s->{lamp}{duration_after_button} || 30)]}"></label>
<label>Schermhelderheid<input type="range" min="0" max="100" name="brightness" value="@{[int($s->{display}{brightness} || 80)]}"></label>
<label>Tijdzone<select name="timezone">$zone_options</select></label>
<label>Tijdweergave<select name="time_format"><option value="24h"$fmt24>24 uur · 20:41</option><option value="12h"$fmt12>12 uur · 8:41 PM</option></select></label>
<button class="primary" type="submit">Instellingen opslaan</button>
</form>
</section>

<section class="card">
<h2>Beveiliging</h2>
<p class="muted">Je beheerlink bevat een willekeurige 256-bit ID en is niet oplopend. Daarnaast is altijd je gebruikersnaam en wachtwoord nodig.</p>
<form method="post">
<input type="hidden" name="action" value="password"><input type="hidden" name="d" value="@{[_h($device_id)]}"><input type="hidden" name="csrf" value="$csrf">
<label>Nieuw wachtwoord<input type="password" name="new_password" minlength="12" maxlength="128" autocomplete="new-password" required></label>
<label>Herhaal wachtwoord<input type="password" name="confirm_password" minlength="12" maxlength="128" autocomplete="new-password" required></label>
<button type="submit">Wachtwoord wijzigen</button>
</form>
<div class="security-note">MyX-feedlinks, Bearer-tokens en andere accountgeheimen worden niet op deze server opgeslagen.</div>
</section>
</div>
<footer>Laatste wijziging: @{[_h($r->{updated_at} || 'onbekend')]} · revisie @{[int($r->{revision} || 0)]}</footer>
</div>});
}

sub _page {
    my ($title, $content) = @_;
    return qq{<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>@{[_h($title)]} · Aventus Wekker</title>
<style>
:root{color-scheme:light;--b:#2563eb;--ink:#172033;--muted:#667085;--line:#e4e8ef;--bg:#f4f7fb;--card:#fff;--ok:#17795a;--bad:#b42318;font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}.shell{max-width:900px;margin:auto;padding:24px}.small-shell{max-width:440px;padding-top:8vh}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.brand{font-size:1.35rem;font-weight:800;color:#1d4ed8}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 5px 18px rgba(24,39,75,.05)}h1,h2{margin-top:0}h1{font-size:1.45rem}h2{font-size:1.1rem}
form{display:grid;gap:12px}label{display:grid;gap:6px;font-size:.88rem;font-weight:650}.check{display:flex;align-items:center;gap:8px}
input,select,button{font:inherit;border:1px solid #cfd6e2;border-radius:10px;padding:10px 12px;background:white}button{cursor:pointer;font-weight:700}.primary{background:var(--b);color:white;border-color:var(--b)}
.muted{color:var(--muted);font-size:.9rem}.notice{padding:11px 13px;border-radius:10px;margin-bottom:14px}.ok{background:#eaf8f2;color:var(--ok)}.bad{background:#fff0ef;color:var(--bad)}
.security-note{margin-top:18px;padding:12px;background:#f7f9fc;border-radius:10px;color:var(--muted);font-size:.84rem;line-height:1.45}footer{color:var(--muted);font-size:.78rem;margin-top:16px}
\@media(max-width:700px){.grid{grid-template-columns:1fr}.shell{padding:14px}}
</style></head><body>$content</body></html>};
}

# ---------------------------------------------------------------------------
# Opslag + authenticatie helpers

sub _init_data_dir {
    if (!-d $DATA_DIR) {
        make_path($DATA_DIR, { mode => 0700 });
    }
    chmod 0700, $DATA_DIR;
    # Extra vangnet als de directory per ongeluk onder DocumentRoot staat.
    my $ht = "$DATA_DIR/.htaccess";
    if (!-e $ht) {
        if (open my $fh, '>', $ht) {
            print {$fh} "Require all denied\nDeny from all\n";
            close $fh;
            chmod 0600, $ht;
        }
    }
}

sub _path_for {
    my ($id) = @_;
    die "bad id" if !_valid_device_id($id);
    return "$DATA_DIR/device_$id.json";
}

sub _record_exists {
    my ($id) = @_;
    return _valid_device_id($id) && -f _path_for($id);
}

sub _create_record {
    my ($id, $record) = @_;
    my $path = _path_for($id);
    sysopen(my $fh, $path, O_WRONLY | O_CREAT | O_EXCL, 0600)
        or _json_error(500, 'opslag kon niet worden aangemaakt');
    print {$fh} encode_json($record);
    close $fh;
    chmod 0600, $path;
}

sub _with_record {
    my ($id, $callback) = @_;
    _record_exists($id) or _json_error(404, 'wekker niet gevonden');
    my $path = _path_for($id);
    my $lock_path = "$path.lock";
    open my $lock, '>>', $lock_path or _json_error(500, 'lock kon niet worden geopend');
    flock($lock, LOCK_EX) or _json_error(500, 'lock kon niet worden verkregen');

    open my $in, '<', $path or _json_error(500, 'opslag kon niet worden gelezen');
    local $/;
    my $raw = <$in>;
    close $in;
    my $record;
    eval { $record = decode_json($raw); 1 } or _json_error(500, 'opslagbestand is beschadigd');

    my $changed = $callback->($record);
    if ($changed) {
        my $tmp = "$path.tmp.$$." . _random_hex(4);
        sysopen(my $out, $tmp, O_WRONLY | O_CREAT | O_EXCL, 0600)
            or _json_error(500, 'tijdelijk opslagbestand kon niet worden gemaakt');
        print {$out} encode_json($record);
        close $out;
        rename $tmp, $path or _json_error(500, 'opslag kon niet atomair worden vervangen');
        chmod 0600, $path;
    }
    close $lock;
}

sub _current_session {
    my ($record) = @_;
    _prune_sessions($record);
    my %cookies = _parse_cookies($ENV{HTTP_COOKIE} || '');
    my $sid = $cookies{wekker_session} || '';
    return ('', undef) if $sid !~ /\A[0-9a-f]{64}\z/;
    my $session = $record->{sessions}{$sid};
    return ($sid, undef) if !$session || int($session->{expires} || 0) < time();
    return ($sid, $session);
}

sub _prune_sessions {
    my ($record) = @_;
    my $now = time();
    $record->{sessions} ||= {};
    for my $sid (keys %{$record->{sessions}}) {
        delete $record->{sessions}{$sid}
            if int($record->{sessions}{$sid}{expires} || 0) < $now;
    }
}

sub _require_csrf {
    my ($session, $given) = @_;
    (!$session || !_secure_eq($session->{csrf} || '', $given || ''))
        and _html(403, _page('Sessie verlopen', '<div class="card"><h1>Sessie verlopen</h1><p>Scan de QR-code opnieuw en log opnieuw in.</p></div>'));
}

sub _pbkdf2_hex {
    my ($password, $salt_hex, $iterations) = @_;
    my $salt = pack('H*', $salt_hex);
    my $u = hmac_sha256($salt . pack('N', 1), $password);
    my $t = $u;
    for (2 .. $iterations) {
        $u = hmac_sha256($u, $password);
        $t ^= $u;
    }
    return unpack('H*', $t);
}

sub _secure_eq {
    my ($a, $b) = @_;
    $a = '' if !defined $a;
    $b = '' if !defined $b;
    my $len = length($a) > length($b) ? length($a) : length($b);
    my $diff = length($a) ^ length($b);
    for my $i (0 .. $len - 1) {
        my $ca = $i < length($a) ? ord(substr($a, $i, 1)) : 0;
        my $cb = $i < length($b) ? ord(substr($b, $i, 1)) : 0;
        $diff |= $ca ^ $cb;
    }
    return $diff == 0;
}

sub _random_bytes {
    my ($count) = @_;
    open my $fh, '<:raw', '/dev/urandom' or die "kan /dev/urandom niet openen";
    my $buf = '';
    my $got = read($fh, $buf, $count);
    close $fh;
    die "te weinig random bytes" if !defined $got || $got != $count;
    return $buf;
}

sub _random_hex {
    my ($bytes) = @_;
    return unpack('H*', _random_bytes($bytes));
}

sub _random_password {
    my ($length) = @_;
    # Geen 0/O/1/l/I: prettiger om van het fysieke scherm over te typen.
    my $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
    my $raw = _random_bytes($length);
    my $out = '';
    for my $i (0 .. $length - 1) {
        $out .= substr($alphabet, ord(substr($raw, $i, 1)) % length($alphabet), 1);
    }
    return $out;
}

# ---------------------------------------------------------------------------
# Validatie / HTTP helpers

sub _validate_settings {
    my ($s) = @_;
    ref($s) eq 'HASH' or _json_error(400, 'settings-object verwacht');
    my %sections = map { $_ => 1 } qw(alarm lamp display locale);
    for my $section (keys %$s) {
        $sections{$section} or _json_error(400, "onbekende settings-sectie: $section");
        ref($s->{$section}) eq 'HASH' or _json_error(400, "settings-sectie $section moet object zijn");
    }
    my %keys = (
        alarm => { map { $_ => 1 } qw(time enabled snooze_minutes sound volume speaker_enabled lamp_brightness lamp_blink blink_pattern ramp_up_seconds) },
        lamp => { map { $_ => 1 } qw(duration_after_button on_with_alarm) },
        display => { map { $_ => 1 } qw(brightness on_duration_seconds night_mode night_start night_end visible_fields) },
        locale => { map { $_ => 1 } qw(timezone region time_format) },
    );
    for my $section (keys %$s) {
        for my $key (keys %{$s->{$section}}) {
            $keys{$section}{$key} or _json_error(400, "onbekende settings-sleutel: $section.$key");
        }
    }
    my $size = length(encode_json($s));
    $size <= $MAX_BODY or _json_error(413, 'settings te groot');
}

sub _valid_device_id {
    my ($id) = @_;
    return defined($id) && $id =~ /\A[0-9a-f]{64}\z/;
}

sub _valid_time {
    my ($v) = @_;
    return defined($v) && $v =~ /\A(?:[01]\d|2[0-3]):[0-5]\d\z/;
}

sub _clamp_int {
    my ($v, $min, $max, $fallback) = @_;
    return $fallback if !defined($v) || $v !~ /\A\d+\z/;
    my $n = int($v);
    return $min if $n < $min;
    return $max if $n > $max;
    return $n;
}

sub _detect_public_url {
    my $scheme = (($ENV{HTTPS} || '') eq 'on' || ($ENV{HTTP_X_FORWARDED_PROTO} || '') eq 'https') ? 'https' : 'http';
    my $host = $ENV{HTTP_HOST} || 'veendomain.nl';
    my $script = $ENV{SCRIPT_NAME} || '/klok/test2.pl';
    return "$scheme://$host$script";
}

sub _parse_params {
    my ($raw) = @_;
    my %out;
    for my $pair (split /&/, $raw) {
        next if $pair eq '';
        my ($k, $v) = split /=/, $pair, 2;
        $k = _url_decode($k // '');
        $v = _url_decode($v // '');
        $out{$k} = $v;
    }
    return %out;
}

sub _url_decode {
    my ($s) = @_;
    $s =~ tr/+/ /;
    $s =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    return $s;
}

sub _parse_cookies {
    my ($raw) = @_;
    my %out;
    for my $part (split /;\s*/, $raw) {
        my ($k, $v) = split /=/, $part, 2;
        $out{$k} = $v if defined $k && defined $v;
    }
    return %out;
}

sub _iso_now {
    return strftime('%Y-%m-%dT%H:%M:%SZ', gmtime(time()));
}

sub _h {
    my ($s) = @_;
    $s = '' if !defined $s;
    $s =~ s/&/&amp;/g;
    $s =~ s/</&lt;/g;
    $s =~ s/>/&gt;/g;
    $s =~ s/"/&quot;/g;
    $s =~ s/'/&#39;/g;
    return $s;
}

sub _status_text {
    my ($code) = @_;
    return {
        200 => 'OK', 302 => 'Found', 400 => 'Bad Request', 401 => 'Unauthorized',
        403 => 'Forbidden', 404 => 'Not Found', 409 => 'Conflict',
        413 => 'Payload Too Large', 429 => 'Too Many Requests', 500 => 'Internal Server Error',
    }->{$code} || 'OK';
}

sub _json_ok {
    my ($payload) = @_;
    my %out = (ok => JSON::PP::true, %{$payload || {}});
    my $json = encode_json(\%out);
    print "Status: 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n$json";
    exit;
}

sub _json_error {
    my ($code, $message) = @_;
    my $json = encode_json({ ok => JSON::PP::false, error => "$message" });
    print "Status: $code " . _status_text($code) . "\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n$json";
    exit;
}

sub _html {
    my ($code, $html) = @_;
    print "Status: $code " . _status_text($code) . "\r\n";
    print "Content-Type: text/html; charset=utf-8\r\n";
    print "Cache-Control: no-store\r\n";
    print "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'\r\n";
    print "X-Frame-Options: DENY\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n\r\n";
    print $html;
    exit;
}

sub _redirect {
    my ($location, $cookie) = @_;
    print "Status: 302 Found\r\nLocation: $location\r\n";
    print "Set-Cookie: $cookie\r\n" if defined $cookie;
    print "Cache-Control: no-store\r\n\r\n";
    exit;
}
