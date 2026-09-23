#! C:/Perl64/bin/perl.exe
use strict;
use warnings;
use utf8;

use JSON::PP qw(encode_json decode_json);
use Digest::SHA qw(hmac_sha256 sha256_hex);
use Fcntl qw(:DEFAULT :flock);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Spec;
use MIME::Base64 qw(decode_base64);
use POSIX qw(strftime);

binmode STDOUT, ':encoding(UTF-8)';
binmode STDERR, ':encoding(UTF-8)';

# WaveSync cloudbeheer.
# Bewaart WaveSync-instellingen per apparaat. Een MyX-feedlink wordt alleen
# tijdelijk bewaard totdat de gekoppelde Pi hem via HTTPS heeft opgehaald en
# bevestigd; daarna wordt de URL uit het serverrecord verwijderd.

my $MAX_BODY = 64 * 1024;
my $SESSION_TTL = 30 * 24 * 60 * 60;
my $PBKDF2_ITERATIONS = 60_000;
my $PUBLIC_URL = $ENV{WEKKER_PUBLIC_URL} || _detect_public_url();
my $DATA_DIR = _choose_data_dir();

my $method = uc($ENV{REQUEST_METHOD} || 'GET');
my $content_type = lc($ENV{CONTENT_TYPE} || '');
my $body = '';

if ($method eq 'POST') {
    my $len = int($ENV{CONTENT_LENGTH} || 0);
    _json_error(413, 'request te groot') if $len > $MAX_BODY;
    if ($len > 0) {
        my $read = read(STDIN, $body, $len);
        _json_error(400, 'request kon niet worden gelezen')
            if !defined($read) || $read != $len;
    }
}

# Diagnose via browser: https://.../test2.pl?health=1
my %query = _parse_params($ENV{QUERY_STRING} || '');
if ($method eq 'GET' && ($query{health} || '') eq '1') {
    _json_ok({
        service => 'wavesync',
        version => 5,
        storage_writable => JSON::PP::true,
        storage_backend => 'file-per-device',
    });
}

if ($method eq 'POST' && $content_type =~ m{application/json}) {
    _handle_api($body);
}

my %form = $method eq 'POST' ? _parse_params($body) : ();
my $device_id = $form{d} || $query{d} || '';

if ($method eq 'POST' && ($form{action} || '') eq 'login') {
    _web_login($device_id, \%form);
}
if ($method eq 'POST' && ($form{action} || '') eq 'save') {
    _web_save($device_id, \%form);
}
if ($method eq 'POST' && ($form{action} || '') eq 'password') {
    _web_change_password($device_id, \%form);
}
if ($method eq 'POST' && ($form{action} || '') eq 'logout') {
    _web_logout($device_id);
}

_show_management_page($device_id);

# ---------------------------------------------------------------------------
# API

sub _handle_api {
    my ($raw) = @_;
    my $req;
    eval { $req = decode_json($raw || '{}'); 1 }
        or _json_error(400, 'ongeldige JSON');
    _json_error(400, 'JSON-object verwacht') if ref($req) ne 'HASH';

    my $action = $req->{action} || '';

    if ($action eq 'register') {
        my $settings = $req->{settings};
        _validate_settings($settings);

        # v2: de Pi maakt deze geheimen lokaal aan zodat QR/login ook zichtbaar
        # zijn als de server bij de eerste boot even offline is.
        my $device_id = $req->{device_id} || _random_hex(32);
        my $device_key = $req->{device_key} || _random_hex(32);
        my $username = $req->{username} || 'basis';
        my $password = $req->{initial_password} || _random_password(16);

        _valid_device_id($device_id) or _json_error(400, 'ongeldige device-ID');
        $device_key =~ /\A[0-9a-f]{64}\z/
            or _json_error(400, 'ongeldige device key');
        $username eq 'basis' or _json_error(400, 'ongeldige gebruikersnaam');
        length($password) >= 12 && length($password) <= 128
            or _json_error(400, 'ongeldig startwachtwoord');

        if (_record_exists($device_id)) {
            # Idempotente registratie: alleen accepteren als dezelfde key hoort
            # bij dit device. Zo is een retry na een time-out veilig.
            my $same = _with_record($device_id, sub {
                my ($record) = @_;
                return _secure_eq(
                    sha256_hex($device_key),
                    $record->{device_key_hash} || ''
                ) ? 1 : 0;
            });
            $same or _json_error(409, 'device-ID bestaat al');
            _json_ok({
                management_url => "$PUBLIC_URL?d=$device_id",
                username => $username,
                revision => 1,
            });
        }

        my $salt = _random_hex(16);
        my $record = {
            schema_version => 5,
            device_id => $device_id,
            device_key_hash => sha256_hex($device_key),
            username => $username,
            password_salt => $salt,
            password_hash => _pbkdf2_hex($password, $salt, $PBKDF2_ITERATIONS),
            password_iterations => $PBKDF2_ITERATIONS,
            password_changed => JSON::PP::false,
            revision => 1,
            settings => $settings,
            myx_feed_configured => JSON::PP::false,
            pending_myx_feed => undef,
            created_at => _iso_now(),
            updated_at => _iso_now(),
            sessions => {},
            failed_logins => 0,
            locked_until => 0,
        };
        _create_record($device_id, $record);
        _json_ok({
            management_url => "$PUBLIC_URL?d=$device_id",
            username => $username,
            revision => 1,
        });
    }

    my $device = $ENV{HTTP_X_WEKKER_DEVICE} || '';
    my $key = $ENV{HTTP_X_WEKKER_KEY} || '';
    _valid_device_id($device)
        or _json_error(401, 'ongeldige device-authenticatie');

    if ($action eq 'pull') {
        my $reply;
        eval {
            $reply = _with_record($device, sub {
                my ($record) = @_;
                _require_device_key($record, $key);
                my $feed_update;
                if (ref($record->{pending_myx_feed}) eq 'HASH') {
                    my $pending = $record->{pending_myx_feed};
                    $feed_update = {
                        id => $pending->{id} || '',
                        action => $pending->{action} || '',
                    };
                    if (($pending->{action} || '') eq 'set') {
                        $feed_update->{url} = $pending->{url} || '';
                    }
                }
                return {
                    settings => $record->{settings},
                    revision => int($record->{revision} || 0),
                    password_changed => $record->{password_changed}
                        ? JSON::PP::true : JSON::PP::false,
                    myx_feed_configured => $record->{myx_feed_configured}
                        ? JSON::PP::true : JSON::PP::false,
                    (defined($feed_update)
                        ? (myx_feed_update => $feed_update)
                        : ()),
                    updated_at => $record->{updated_at},
                };
            });
            1;
        } or _api_exception($@);
        _json_ok($reply);
    }

    if ($action eq 'ack_feed') {
        my $update_id = $req->{update_id} || '';
        $update_id =~ /\A[0-9a-f]{32}\z/
            or _json_error(400, 'ongeldige feed update-id');

        my $reply;
        eval {
            $reply = _update_record($device, sub {
                my ($record) = @_;
                _require_device_key($record, $key);
                my $pending = $record->{pending_myx_feed};
                if (ref($pending) eq 'HASH'
                    && ($pending->{id} || '') eq $update_id) {
                    $record->{pending_myx_feed} = undef;
                    $record->{updated_at} = _iso_now();
                }
                return { revision => int($record->{revision} || 0) };
            });
            1;
        } or _api_exception($@);
        _json_ok($reply);
    }

    if ($action eq 'push') {
        my $settings = $req->{settings};
        _validate_settings($settings);
        my $expected_revision = int($req->{expected_revision} // -1);

        my $reply;
        eval {
            $reply = _update_record($device, sub {
                my ($record) = @_;
                _require_device_key($record, $key);
                my $current = int($record->{revision} || 0);
                $expected_revision == $current
                    or _signal_error(409, 'instellingen zijn ondertussen elders gewijzigd');
                $record->{settings} = $settings;
                $record->{revision} = $current + 1;
                $record->{updated_at} = _iso_now();
                return { revision => $record->{revision} };
            });
            1;
        } or _api_exception($@);
        _json_ok($reply);
    }

    _json_error(400, 'onbekende API-actie');
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
    }

    my $result = _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        return { record => $record, sid => $sid, session => $session };
    });

    if (!$result->{session}) {
        _html(200, _login_page($device_id));
    }
    _html(200, _settings_page(
        $device_id, $result->{record}, $result->{session}
    ));
}

sub _web_login {
    my ($device_id, $form) = @_;
    (!_valid_device_id($device_id) || !_record_exists($device_id))
        and _html(404, _login_page($device_id, 'Wekker niet gevonden.'));

    my $result;
    eval {
        $result = _update_record($device_id, sub {
            my ($record) = @_;
            my $now = time();
            if (($record->{locked_until} || 0) > $now) {
                return { status => 429, error => 'Te veel mislukte pogingen. Probeer over een minuut opnieuw.' };
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
                return { status => 401, error => 'Gebruikersnaam of wachtwoord klopt niet.' };
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
            return { status => 302, sid => $sid };
        });
        1;
    } or do {
        _html(500, _page('Serverfout', '<div class="card">Login kon niet worden verwerkt.</div>'));
    };

    if (($result->{status} || 500) != 302) {
        _html($result->{status}, _login_page($device_id, $result->{error}));
    }
    _redirect(
        "$PUBLIC_URL?d=$device_id",
        "wavesync_session=$result->{sid}; Path=/; Max-Age=$SESSION_TTL; Secure; HttpOnly; SameSite=Strict"
    );
}

sub _web_save {
    my ($device_id, $form) = @_;
    _valid_device_id($device_id)
        or _html(400, _page('Fout', '<div class="card">Ongeldige wekker-ID.</div>'));

    my $result;
    eval {
        $result = _update_record($device_id, sub {
            my ($record) = @_;
            my ($sid, $session) = _current_session($record);
            _require_csrf_or_signal($session, $form->{csrf});

            my $settings = $record->{settings};

            $settings->{alarm}{time} = _valid_time($form->{alarm_time})
                ? $form->{alarm_time} : $settings->{alarm}{time};
            $settings->{alarm}{enabled} = $form->{alarm_enabled}
                ? JSON::PP::true : JSON::PP::false;
            $settings->{alarm}{snooze_minutes} =
                _clamp_int($form->{snooze_minutes}, 1, 60, 9);
            $settings->{alarm}{sound} = _clean_text(
                $form->{sound}, 1, 64, 'beep'
            );
            $settings->{alarm}{volume} =
                _clamp_int($form->{volume}, 0, 100, 70);
            $settings->{alarm}{speaker_enabled} = $form->{speaker_enabled}
                ? JSON::PP::true : JSON::PP::false;
            $settings->{alarm}{lamp_brightness} =
                _clamp_int($form->{alarm_lamp_brightness}, 0, 100, 100);
            $settings->{alarm}{lamp_blink} = $form->{lamp_blink}
                ? JSON::PP::true : JSON::PP::false;

            my %blink = map { $_ => 1 } qw(steady blink pulse);
            $settings->{alarm}{blink_pattern} =
                $blink{$form->{blink_pattern} || ''}
                    ? $form->{blink_pattern} : 'blink';
            $settings->{alarm}{ramp_up_seconds} =
                _clamp_int($form->{ramp_up_seconds}, 0, 3600, 30);

            $settings->{lamp}{duration_after_button} =
                _clamp_int($form->{lamp_duration}, 1, 3600, 30);
            $settings->{lamp}{on_with_alarm} = $form->{lamp_on_with_alarm}
                ? JSON::PP::true : JSON::PP::false;

            $settings->{display}{brightness} =
                _clamp_int($form->{brightness}, 0, 100, 80);
            $settings->{display}{on_duration_seconds} =
                _clamp_int($form->{display_on_duration}, 1, 600, 30);

            my %night = map { $_ => 1 } qw(off dim);
            $settings->{display}{night_mode} =
                $night{$form->{night_mode} || ''}
                    ? $form->{night_mode} : 'dim';
            $settings->{display}{night_start} =
                _valid_time($form->{night_start}) ? $form->{night_start} : '23:00';
            $settings->{display}{night_end} =
                _valid_time($form->{night_end}) ? $form->{night_end} : '07:00';

            my @visible;
            for my $field (qw(time next_alarm first_lesson teacher room last_lesson day_agenda)) {
                push @visible, $field if $form->{"visible_$field"};
            }
            @visible = qw(time next_alarm first_lesson teacher room) if !@visible;
            $settings->{display}{visible_fields} = \@visible;

            my %zones = map { $_ => 1 } qw(
                Europe/Amsterdam Europe/Paris Europe/London Europe/Berlin
                Europe/Brussels Europe/Madrid Europe/Rome UTC
            );
            $settings->{locale}{timezone} =
                $zones{$form->{timezone} || ''}
                    ? $form->{timezone} : 'Europe/Amsterdam';
            $settings->{locale}{time_format} =
                ($form->{time_format} || '') eq '12h' ? '12h' : '24h';
            my $region = uc($form->{region} || 'NL');
            $settings->{locale}{region} =
                $region =~ /\A[A-Z]{2}\z/ ? $region : 'NL';

            $settings->{agenda} ||= {};
            my %providers = map { $_ => 1 } qw(mock magister somtoday osiris myx);
            $settings->{agenda}{provider} =
                $providers{$form->{agenda_provider} || ''}
                    ? $form->{agenda_provider}
                    : ($settings->{agenda}{provider} || 'myx');
            $settings->{agenda}{auto_sync_minutes} =
                _clamp_int($form->{auto_sync_minutes}, 0, 1440, 15);

            my $feed = $form->{myx_feed} // '';
            $feed =~ s/^\s+|\s+$//g;
            if ($form->{clear_myx_feed}) {
                $record->{pending_myx_feed} = {
                    id => _random_hex(16),
                    action => 'clear',
                };
                $record->{myx_feed_configured} = JSON::PP::false;
            }
            elsif ($feed ne '') {
                my $normalized = _normalize_myx_feed($feed);
                $record->{pending_myx_feed} = {
                    id => _random_hex(16),
                    action => 'set',
                    url => $normalized,
                };
                $record->{myx_feed_configured} = JSON::PP::true;
                $settings->{agenda}{provider} = 'myx';
            }

            _validate_settings($settings);
            $record->{settings} = $settings;
            $record->{revision} = int($record->{revision} || 0) + 1;
            $record->{updated_at} = _iso_now();
            return 1;
        });
        1;
    } or do {
        my $e = $@;
        if (ref($e) eq 'WaveSync::Error') {
            my $r = _with_record($device_id, sub {
                my ($record) = @_;
                my (undef, $session) = _current_session($record);
                return { record => $record, session => $session };
            });
            _html($e->{code}, _settings_page(
                $device_id, $r->{record}, $r->{session}, $e->{message}
            ));
        }
        die $e;
    };

    _redirect("$PUBLIC_URL?d=$device_id&saved=1");
}

sub _web_change_password {
    my ($device_id, $form) = @_;
    _valid_device_id($device_id)
        or _html(400, _page('Fout', '<div class="card">Ongeldige wekker-ID.</div>'));

    my $result;
    eval {
        $result = _update_record($device_id, sub {
            my ($record) = @_;
            my ($sid, $session) = _current_session($record);
            _require_csrf_or_signal($session, $form->{csrf});

            my $new = $form->{new_password} // '';
            my $confirm = $form->{confirm_password} // '';
            if (length($new) < 12 || length($new) > 128 || $new ne $confirm) {
                _signal_error(400, 'Wachtwoord moet 12–128 tekens zijn en beide velden moeten gelijk zijn.');
            }
            my $salt = _random_hex(16);
            $record->{password_salt} = $salt;
            $record->{password_hash} =
                _pbkdf2_hex($new, $salt, $PBKDF2_ITERATIONS);
            $record->{password_iterations} = $PBKDF2_ITERATIONS;
            $record->{password_changed} = JSON::PP::true;
            my $keep = $record->{sessions}{$sid};
            $record->{sessions} = { $sid => $keep };
            $record->{updated_at} = _iso_now();
            return 1;
        });
        1;
    } or do {
        my $e = $@;
        if (ref($e) eq 'WaveSync::Error') {
            my $r = _with_record($device_id, sub {
                my ($record) = @_;
                my (undef, $session) = _current_session($record);
                return { record => $record, session => $session };
            });
            _html($e->{code}, _settings_page(
                $device_id, $r->{record}, $r->{session}, $e->{message}
            ));
        }
        die $e;
    };
    _redirect("$PUBLIC_URL?d=$device_id&password=1");
}

sub _web_logout {
    my ($device_id) = @_;
    if (_valid_device_id($device_id) && _record_exists($device_id)) {
        _update_record($device_id, sub {
            my ($record) = @_;
            my ($sid) = _current_session($record);
            delete $record->{sessions}{$sid} if $sid;
            return 1;
        });
    }
    _redirect(
        _valid_device_id($device_id) ? "$PUBLIC_URL?d=$device_id" : $PUBLIC_URL,
        "wavesync_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"
    );
}

# ---------------------------------------------------------------------------
# HTML

sub _login_page {
    my ($device_id, $error) = @_;
    my $msg = $error
        ? '<div class="notice bad">' . _h($error) . '</div>' : '';
    return _page('Inloggen', qq{
<div class="shell small-shell">
  <div class="brand">WaveSync</div>
  <div class="card">
    <h1>Online beheer</h1>
    <p class="muted">Log in met de gegevens op het scherm van je WaveSync.</p>
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
    my $saved = ($ENV{QUERY_STRING} || '') =~ /(?:^|&)saved=1(?:&|$)/
        ? '<div class="notice ok">Opgeslagen. Je WaveSync neemt de wijziging meestal binnen 30 seconden over.</div>' : '';
    my $pw = ($ENV{QUERY_STRING} || '') =~ /(?:^|&)password=1(?:&|$)/
        ? '<div class="notice ok">Wachtwoord gewijzigd.</div>' : '';
    my $err = $error
        ? '<div class="notice bad">' . _h($error) . '</div>' : '';

    my @zones = (
        ['Europe/Amsterdam', 'Amsterdam · CET/CEST'],
        ['Europe/Brussels', 'Brussel · CET/CEST'],
        ['Europe/Berlin', 'Berlijn · CET/CEST'],
        ['Europe/Paris', 'Parijs · CET/CEST'],
        ['Europe/London', 'Londen · GMT/BST'],
        ['Europe/Madrid', 'Madrid · CET/CEST'],
        ['Europe/Rome', 'Rome · CET/CEST'],
        ['UTC', 'UTC'],
    );
    my $zone_options = join '', map {
        my ($value, $label) = @$_;
        my $selected =
            ($s->{locale}{timezone} || '') eq $value ? ' selected' : '';
        '<option value="' . _h($value) . '"' . $selected . '>'
            . _h($label) . '</option>'
    } @zones;

    my $fmt24 =
        ($s->{locale}{time_format} || '24h') eq '24h' ? ' selected' : '';
    my $fmt12 =
        ($s->{locale}{time_format} || '') eq '12h' ? ' selected' : '';

    my $alarm_checked = $s->{alarm}{enabled} ? ' checked' : '';
    my $speaker_checked = $s->{alarm}{speaker_enabled} ? ' checked' : '';
    my $blink_checked = $s->{alarm}{lamp_blink} ? ' checked' : '';
    my $lamp_alarm_checked = $s->{lamp}{on_with_alarm} ? ' checked' : '';

    my %visible = map { $_ => 1 } @{$s->{display}{visible_fields} || []};
    my $vc = sub {
        my ($name) = @_;
        return $visible{$name} ? ' checked' : '';
    };

    my $night_off = ($s->{display}{night_mode} || '') eq 'off' ? ' selected' : '';
    my $night_dim = ($s->{display}{night_mode} || 'dim') eq 'dim' ? ' selected' : '';

    my $blink_pattern = $s->{alarm}{blink_pattern} || 'blink';
    my $blink_options = join '', map {
        my $sel = $blink_pattern eq $_ ? ' selected' : '';
        '<option value="' . $_ . '"' . $sel . '>' .
            ($_ eq 'steady' ? 'Constant' : $_ eq 'pulse' ? 'Pulseren' : 'Knipperen')
            . '</option>'
    } qw(steady blink pulse);

    my $provider = $s->{agenda}{provider} || 'myx';
    my @providers = (
        ['myx', 'MyX / Xedule'],
        ['mock', 'Voorbeelddata'],
        ['osiris', 'OSIRIS'],
        ['magister', 'Magister'],
        ['somtoday', 'Somtoday'],
    );
    my $provider_options = join '', map {
        my ($value, $label) = @$_;
        my $sel = $provider eq $value ? ' selected' : '';
        '<option value="' . _h($value) . '"' . $sel . '>' . _h($label) . '</option>'
    } @providers;

    my $feed_status = $r->{myx_feed_configured}
        ? '<span class="pill ok">MyX-feed gekoppeld</span>'
        : '<span class="pill">Nog geen MyX-feed</span>';

    return _page('Instellingen', qq{
<div class="shell">
<header>
  <div><div class="brand">WaveSync</div><div class="muted">Online beheer</div></div>
  <form method="post">
    <input type="hidden" name="action" value="logout">
    <input type="hidden" name="d" value="@{[_h($device_id)]}">
    <button>Uitloggen</button>
  </form>
</header>
$saved$pw$err

<form method="post" class="settings-form">
<input type="hidden" name="action" value="save">
<input type="hidden" name="d" value="@{[_h($device_id)]}">
<input type="hidden" name="csrf" value="$csrf">

<div class="grid">
<section class="card">
<h2>Alarm</h2>
<label>Wektijd<input type="time" name="alarm_time" value="@{[_h($s->{alarm}{time} || '07:30')]}" required></label>
<label class="check"><input type="checkbox" name="alarm_enabled" value="1"$alarm_checked> Alarm ingeschakeld</label>
<label>Snooze (minuten)<input type="number" min="1" max="60" name="snooze_minutes" value="@{[int($s->{alarm}{snooze_minutes} || 9)]}"></label>
<label>Geluid<input name="sound" maxlength="64" value="@{[_h($s->{alarm}{sound} || 'beep')]}"></label>
<label>Volume <span class="value-note">@{[int($s->{alarm}{volume} // 70)]}%</span>
<input type="range" min="0" max="100" name="volume" value="@{[int($s->{alarm}{volume} // 70)]}"></label>
<label class="check"><input type="checkbox" name="speaker_enabled" value="1"$speaker_checked> Speaker bij alarm</label>
<label>Lampsterkte bij alarm <span class="value-note">@{[int($s->{alarm}{lamp_brightness} // 100)]}%</span>
<input type="range" min="0" max="100" name="alarm_lamp_brightness" value="@{[int($s->{alarm}{lamp_brightness} // 100)]}"></label>
<label class="check"><input type="checkbox" name="lamp_blink" value="1"$blink_checked> Lamp-effect gebruiken</label>
<label>Lamp-effect<select name="blink_pattern">$blink_options</select></label>
<label>Rustig opbouwen (seconden)<input type="number" min="0" max="3600" name="ramp_up_seconds" value="@{[int($s->{alarm}{ramp_up_seconds} // 30)]}"></label>
</section>

<section class="card">
<h2>Scherm &amp; tijd</h2>
<label>Schermhelderheid <span class="value-note">@{[int($s->{display}{brightness} // 80)]}%</span>
<input type="range" min="0" max="100" name="brightness" value="@{[int($s->{display}{brightness} // 80)]}"></label>
<label>Scherm actief na bediening (seconden)<input type="number" min="1" max="600" name="display_on_duration" value="@{[int($s->{display}{on_duration_seconds} // 30)]}"></label>
<label>Nachtmodus<select name="night_mode"><option value="dim"$night_dim>Dimmen</option><option value="off"$night_off>Scherm uit</option></select></label>
<div class="split"><label>Nacht start<input type="time" name="night_start" value="@{[_h($s->{display}{night_start} || '23:00')]}"></label>
<label>Nacht einde<input type="time" name="night_end" value="@{[_h($s->{display}{night_end} || '07:00')]}"></label></div>
<label>Tijdzone<select name="timezone">$zone_options</select></label>
<label>Tijdweergave<select name="time_format"><option value="24h"$fmt24>24 uur · 20:41</option><option value="12h"$fmt12>12 uur · 8:41 PM</option></select></label>
<label>Regio<input name="region" maxlength="2" value="@{[_h($s->{locale}{region} || 'NL')]}"></label>
</section>

<section class="card">
<h2>Lamp &amp; scherminformatie</h2>
<label>Lampduur na fysieke knop (seconden)<input type="number" min="1" max="3600" name="lamp_duration" value="@{[int($s->{lamp}{duration_after_button} || 30)]}"></label>
<label class="check"><input type="checkbox" name="lamp_on_with_alarm" value="1"$lamp_alarm_checked> Lamp aan bij alarm</label>
<div class="field-title">Informatie op de klok</div>
<label class="check"><input type="checkbox" name="visible_time" value="1"@{[$vc->('time')]}> Tijd</label>
<label class="check"><input type="checkbox" name="visible_next_alarm" value="1"@{[$vc->('next_alarm')]}> Volgend alarm</label>
<label class="check"><input type="checkbox" name="visible_first_lesson" value="1"@{[$vc->('first_lesson')]}> Eerste les</label>
<label class="check"><input type="checkbox" name="visible_teacher" value="1"@{[$vc->('teacher')]}> Docent</label>
<label class="check"><input type="checkbox" name="visible_room" value="1"@{[$vc->('room')]}> Lokaal</label>
<label class="check"><input type="checkbox" name="visible_last_lesson" value="1"@{[$vc->('last_lesson')]}> Laatste les</label>
<label class="check"><input type="checkbox" name="visible_day_agenda" value="1"@{[$vc->('day_agenda')]}> Dagsamenvatting</label>
</section>

<section class="card">
<h2>Rooster / MyX</h2>
<div class="status-row">$feed_status</div>
<label>Agenda-provider<select name="agenda_provider">$provider_options</select></label>
<label>Automatisch synchroniseren (minuten)<input type="number" min="0" max="1440" name="auto_sync_minutes" value="@{[int($s->{agenda}{auto_sync_minutes} // 15)]}"></label>
<label>MyX iCalendar / Feed-link
<input name="myx_feed" autocomplete="off" spellcheck="false" placeholder="webcal://aventus.myx.nl/api/InternetCalendar/feed/…"></label>
<p class="muted">Plak hier de Feed-link uit MyX. De URL wordt na ophalen door je Raspberry Pi weer uit de serveropslag verwijderd.</p>
<label class="check danger-check"><input type="checkbox" name="clear_myx_feed" value="1"> MyX-feed van deze WaveSync verwijderen</label>
</section>
</div>

<div class="savebar"><button class="primary save" type="submit">Alle instellingen opslaan</button></div>
</form>

<div class="grid lower-grid">
<section class="card">
<h2>Beveiliging</h2>
<p class="muted">Iedere WaveSync gebruikt een willekeurige 256-bit beheer-ID en een aparte 256-bit device key.</p>
<form method="post">
<input type="hidden" name="action" value="password">
<input type="hidden" name="d" value="@{[_h($device_id)]}">
<input type="hidden" name="csrf" value="$csrf">
<label>Nieuw wachtwoord<input type="password" name="new_password" minlength="12" maxlength="128" autocomplete="new-password" required></label>
<label>Herhaal wachtwoord<input type="password" name="confirm_password" minlength="12" maxlength="128" autocomplete="new-password" required></label>
<button type="submit">Wachtwoord wijzigen</button>
</form>
<div class="security-note">De MyX-feedlink wordt alleen tijdelijk op de server bewaard totdat de gekoppelde Pi hem heeft opgehaald.</div>
</section>

<section class="card">
<h2>Status</h2>
<p class="muted">Laatste wijziging: <b>@{[_h($r->{updated_at} || 'onbekend')]}</b></p>
<p class="muted">Revisie: <b>@{[int($r->{revision} || 0)]}</b></p>
<p class="muted">Wijzigingen worden normaal binnen ongeveer 30 seconden door de klok opgehaald.</p>
</section>
</div>
<footer>WaveSync · apparaat @{[_h(substr($device_id, 0, 10))]}…</footer>
</div>});
}

sub _page {
    my ($title, $content) = @_;
    return qq{<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>@{[_h($title)]} · WaveSync</title>
<style>
:root{color-scheme:light;--b:#2563eb;--ink:#172033;--muted:#667085;--line:#e4e8ef;--bg:#f4f7fb;--card:#fff;--ok:#17795a;--bad:#b42318;font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}
.shell{max-width:900px;margin:auto;padding:24px}.small-shell{max-width:440px;padding-top:8vh}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.brand{font-size:1.5rem;font-weight:850;color:#1d4ed8;letter-spacing:-.03em}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 7px 24px rgba(24,39,75,.06)}
h1,h2{margin-top:0}h1{font-size:1.45rem}h2{font-size:1.1rem}
form{display:grid;gap:12px}label{display:grid;gap:6px;font-size:.88rem;font-weight:650}
.check{display:flex;align-items:center;gap:8px}.check input{width:auto}
.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.field-title{font-size:.86rem;font-weight:800;margin-top:4px}.value-note{float:right;color:var(--muted);font-weight:500}
.status-row{margin-bottom:8px}.pill{display:inline-flex;padding:5px 9px;border-radius:999px;background:#eef2f7;color:var(--muted);font-size:.78rem;font-weight:800}
.pill.ok{background:#eaf8f2;color:var(--ok)}.savebar{position:sticky;bottom:0;padding:14px 0;background:linear-gradient(transparent,var(--bg) 28%)}
.save{width:100%;padding:13px}.lower-grid{margin-top:16px}.danger-check{color:var(--bad)}
input,select,button{font:inherit;border:1px solid #cfd6e2;border-radius:11px;padding:10px 12px;background:white}
button{cursor:pointer;font-weight:700}.primary{background:var(--b);color:white;border-color:var(--b)}
.muted{color:var(--muted);font-size:.9rem}.notice{padding:11px 13px;border-radius:10px;margin-bottom:14px}
.ok{background:#eaf8f2;color:var(--ok)}.bad{background:#fff0ef;color:var(--bad)}
.security-note{margin-top:18px;padding:12px;background:#f7f9fc;border-radius:10px;color:var(--muted);font-size:.84rem;line-height:1.45}
footer{color:var(--muted);font-size:.78rem;margin-top:16px}
\@media(max-width:700px){.grid,.split{grid-template-columns:1fr}.shell{padding:14px}.savebar{bottom:0}}
</style></head><body>$content</body></html>};
}

# ---------------------------------------------------------------------------
# Opslag

sub _choose_data_dir {
    # De oude, werkende test.pl gebruikt:
    #   C:/wamp64/www/veendomain/klok/data
    #
    # We bewaren WaveSync-records in een eigen submap zodat de oude
    # variabelensets niet worden vermengd met de nieuwe JSON-records.
    #
    # WEKKER_DATA_DIR heeft altijd voorrang als je later buiten de
    # DocumentRoot wilt opslaan.
    my @candidates;

    push @candidates, $ENV{WEKKER_DATA_DIR}
        if defined $ENV{WEKKER_DATA_DIR} && $ENV{WEKKER_DATA_DIR} ne '';

    push @candidates, 'C:/wamp64/www/veendomain/klok/data/wavesync';
    push @candidates, dirname(__FILE__) . '/data/wavesync';
    push @candidates, dirname(__FILE__) . '/.wavesync-data';

    push @candidates, "$ENV{HOME}/.wavesync-data"
        if defined $ENV{HOME} && $ENV{HOME} ne '';

    my @errors;

    for my $dir (@candidates) {
        next if !defined $dir || $dir eq '';

        my $ok = eval {
            if (!-d $dir) {
                make_path($dir);
            }

            die "directory bestaat niet na aanmaken"
                if !-d $dir;

            my $probe = File::Spec->catfile(
                $dir,
                ".wavesync-write-test-$$-" . _random_hex(4)
            );

            open my $fh, '>:raw', $probe
                or die "niet schrijfbaar: $!";

            print {$fh} "ok\n";

            close $fh
                or die "testbestand kon niet worden gesloten: $!";

            unlink $probe;

            _write_htaccess($dir);

            1;
        };

        return $dir if $ok;

        my $error = $@ || 'onbekende fout';
        $error =~ s/\s+\z//;
        push @errors, "$dir: $error";
    }

    die "WaveSync data-directory is niet schrijfbaar. "
      . "Geprobeerd: " . join(' | ', @errors);
}

sub _write_htaccess {
    my ($dir) = @_;
    my $ht = "$dir/.htaccess";
    return if -e $ht;
    if (open my $fh, '>', $ht) {
        print {$fh} "Require all denied\n<IfModule mod_access_compat.c>\nDeny from all\n</IfModule>\n";
        close $fh;
        chmod 0600, $ht;
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
    _record_exists($id) or _signal_error(404, 'wekker niet gevonden');
    my $path = _path_for($id);
    my $lock_path = "$path.lock";
    open my $lock, '>>', $lock_path
        or _signal_error(500, 'lock kon niet worden geopend');
    flock($lock, LOCK_SH)
        or _signal_error(500, 'lock kon niet worden verkregen');

    open my $in, '<', $path
        or _signal_error(500, 'opslag kon niet worden gelezen');
    local $/;
    my $raw = <$in>;
    close $in;

    my $record;
    eval { $record = decode_json($raw); 1 }
        or _signal_error(500, 'opslagbestand is beschadigd');
    my $result = $callback->($record);
    close $lock;
    return $result;
}

sub _update_record {
    my ($id, $callback) = @_;
    _record_exists($id) or _signal_error(404, 'wekker niet gevonden');
    my $path = _path_for($id);
    my $lock_path = "$path.lock";
    open my $lock, '>>', $lock_path
        or _signal_error(500, 'lock kon niet worden geopend');
    flock($lock, LOCK_EX)
        or _signal_error(500, 'lock kon niet worden verkregen');

    open my $in, '<', $path
        or _signal_error(500, 'opslag kon niet worden gelezen');
    local $/;
    my $raw = <$in>;
    close $in;

    my $record;
    eval { $record = decode_json($raw); 1 }
        or _signal_error(500, 'opslagbestand is beschadigd');

    my $result = $callback->($record);

    my $tmp = "$path.tmp.$$." . _random_hex(4);
    sysopen(my $out, $tmp, O_WRONLY | O_CREAT | O_EXCL, 0600)
        or _signal_error(500, 'tijdelijk opslagbestand kon niet worden gemaakt');
    print {$out} encode_json($record);
    close $out;
    rename $tmp, $path
        or _signal_error(500, 'opslag kon niet atomair worden vervangen');
    chmod 0600, $path;
    close $lock;
    return $result;
}

# ---------------------------------------------------------------------------
# Authenticatie

sub _require_device_key {
    my ($record, $key) = @_;
    my $expected = $record->{device_key_hash} || '';
    _secure_eq(sha256_hex($key || ''), $expected)
        or _signal_error(401, 'ongeldige device-authenticatie');
}

sub _current_session {
    my ($record) = @_;
    _prune_sessions($record);
    my %cookies = _parse_cookies($ENV{HTTP_COOKIE} || '');
    my $sid = $cookies{wavesync_session} || '';
    return ('', undef) if $sid !~ /\A[0-9a-f]{64}\z/;
    my $session = $record->{sessions}{$sid};
    return ($sid, undef)
        if !$session || int($session->{expires} || 0) < time();
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

sub _require_csrf_or_signal {
    my ($session, $given) = @_;
    (!$session || !_secure_eq($session->{csrf} || '', $given || ''))
        and _signal_error(403, 'Sessie verlopen. Log opnieuw in.');
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

    die "ongeldig aantal random bytes"
        if !defined($count) || $count !~ /^\d+$/ || $count < 1 || $count > 4096;

    # Linux / Raspberry Pi / Unix.
    if (-r '/dev/urandom') {
        open my $fh, '<:raw', '/dev/urandom'
            or die "kan /dev/urandom niet openen: $!";

        my $buf = '';
        my $offset = 0;

        while ($offset < $count) {
            my $got = read($fh, my $chunk, $count - $offset);
            die "fout bij lezen van /dev/urandom: $!"
                if !defined $got;
            die "te weinig random bytes uit /dev/urandom"
                if $got == 0;

            $buf .= $chunk;
            $offset += $got;
        }

        close $fh;
        return $buf;
    }

    # Windows/WAMP:
    # gebruik de cryptografisch veilige RNG van .NET via PowerShell.
    #
    # We geven de bytes als Base64 terug om problemen met binaire output,
    # CR/LF en Windows-pipes te vermijden.
    if ($^O eq 'MSWin32') {
        my $ps = join '',
            '$b = New-Object byte[] ', $count, '; ',
            '$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); ',
            '$rng.GetBytes($b); ',
            '$rng.Dispose(); ',
            '[Console]::Out.Write([Convert]::ToBase64String($b));';

        # Geen gebruikersinvoer komt in $ps terecht: $count is hierboven
        # strikt gevalideerd als klein geheel getal.
        my $encoded = qx{powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ps"};
        my $exit = $? >> 8;

        die "Windows random generator (PowerShell) is mislukt"
            if $exit != 0 || !defined($encoded) || $encoded eq '';

        $encoded =~ s/\s+\z//;
        my $buf = decode_base64($encoded);

        die "Windows random generator gaf onjuiste lengte terug"
            if length($buf) != $count;

        return $buf;
    }

    die "geen cryptografisch veilige random generator beschikbaar op dit platform";
}

sub _random_hex {
    my ($bytes) = @_;
    return unpack('H*', _random_bytes($bytes));
}

sub _random_password {
    my ($length) = @_;
    my $alphabet =
        'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
    my $raw = _random_bytes($length);
    my $out = '';
    for my $i (0 .. $length - 1) {
        $out .= substr(
            $alphabet,
            ord(substr($raw, $i, 1)) % length($alphabet),
            1
        );
    }
    return $out;
}

# ---------------------------------------------------------------------------
# Validatie

sub _validate_settings {
    my ($s) = @_;
    ref($s) eq 'HASH'
        or _json_error(400, 'settings-object verwacht');

    my %sections = map { $_ => 1 } qw(alarm lamp display agenda locale);
    for my $section (keys %$s) {
        $sections{$section}
            or _json_error(400, "onbekende settings-sectie: $section");
        ref($s->{$section}) eq 'HASH'
            or _json_error(400, "settings-sectie $section moet object zijn");
    }

    my %keys = (
        alarm => { map { $_ => 1 } qw(
            time enabled snooze_minutes sound volume speaker_enabled
            lamp_brightness lamp_blink blink_pattern ramp_up_seconds
        ) },
        lamp => { map { $_ => 1 } qw(duration_after_button on_with_alarm) },
        display => { map { $_ => 1 } qw(
            brightness on_duration_seconds night_mode night_start
            night_end visible_fields
        ) },
        agenda => { map { $_ => 1 } qw(provider auto_sync_minutes) },
        locale => { map { $_ => 1 } qw(timezone region time_format) },
    );

    for my $section (keys %$s) {
        for my $key (keys %{$s->{$section}}) {
            $keys{$section}{$key}
                or _json_error(
                    400,
                    "onbekende settings-sleutel: $section.$key"
                );
        }
    }

    length(encode_json($s)) <= $MAX_BODY
        or _json_error(413, 'settings te groot');
}

sub _clean_text {
    my ($value, $min, $max, $fallback) = @_;
    $value = '' if !defined $value;
    $value =~ s/[\x00-\x1F\x7F]//g;
    $value =~ s/^\s+|\s+$//g;
    return $fallback if length($value) < $min || length($value) > $max;
    return $value;
}

sub _normalize_myx_feed {
    my ($value) = @_;
    $value = '' if !defined $value;
    $value =~ s/^\s+|\s+$//g;
    $value =~ s/^webcal:\/\//https:\/\//i;

    # Accepteer uitsluitend de vaste Aventus MyX InternetCalendar-feed.
    $value =~ m{\Ahttps://aventus\.myx\.nl/api/InternetCalendar/feed/
        ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/
        ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\z}x
        or _signal_error(400, 'Ongeldige MyX-feedlink. Gebruik de webcal-link uit MyX.');

    return 'https://aventus.myx.nl/api/InternetCalendar/feed/' . lc($1) . '/' . lc($2);
}

sub _valid_device_id {
    my ($id) = @_;
    return defined($id) && $id =~ /\A[0-9a-f]{64}\z/;
}

sub _valid_time {
    my ($v) = @_;
    return defined($v)
        && $v =~ /\A(?:[01]\d|2[0-3]):[0-5]\d\z/;
}

sub _clamp_int {
    my ($v, $min, $max, $fallback) = @_;
    return $fallback if !defined($v) || $v !~ /\A\d+\z/;
    my $n = int($v);
    return $min if $n < $min;
    return $max if $n > $max;
    return $n;
}

# ---------------------------------------------------------------------------
# HTTP helpers

sub _detect_public_url {
    my $scheme =
        (($ENV{HTTPS} || '') eq 'on'
        || ($ENV{HTTP_X_FORWARDED_PROTO} || '') eq 'https')
        ? 'https' : 'http';
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
        $out{$k} = $v if defined($k) && defined($v);
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

sub _json_ok {
    my ($payload) = @_;
    my %out = (ok => JSON::PP::true, %{$payload || {}});
    my $json = encode_json(\%out);
    print "Status: 200 OK\r\n";
    print "Content-Type: application/json; charset=utf-8\r\n";
    print "Cache-Control: no-store\r\n";
    print "X-Content-Type-Options: nosniff\r\n\r\n";
    print $json;
    exit;
}

sub _json_error {
    my ($code, $message) = @_;
    my $json = encode_json({
        ok => JSON::PP::false,
        error => "$message",
    });
    print "Status: $code " . _status_text($code) . "\r\n";
    print "Content-Type: application/json; charset=utf-8\r\n";
    print "Cache-Control: no-store\r\n";
    print "X-Content-Type-Options: nosniff\r\n\r\n";
    print $json;
    exit;
}

sub _html {
    my ($code, $html) = @_;
    print "Status: $code " . _status_text($code) . "\r\n";
    print "Content-Type: text/html; charset=utf-8\r\n";
    print "Cache-Control: no-store\r\n";
    print "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'\r\n";
    print "X-Frame-Options: DENY\r\n";
    print "X-Content-Type-Options: nosniff\r\n";
    print "Referrer-Policy: no-referrer\r\n\r\n";
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

sub _status_text {
    my ($code) = @_;
    my %names = (
        200 => 'OK', 302 => 'Found', 400 => 'Bad Request',
        401 => 'Unauthorized', 403 => 'Forbidden', 404 => 'Not Found',
        409 => 'Conflict', 413 => 'Payload Too Large',
        429 => 'Too Many Requests', 500 => 'Internal Server Error',
    );
    return $names{$code} || 'Error';
}

{
    package WaveSync::Error;
    sub new {
        my ($class, $code, $message) = @_;
        return bless { code => $code, message => $message }, $class;
    }
}

sub _api_exception {
    my ($e) = @_;
    if (ref($e) eq 'WaveSync::Error') {
        _json_error($e->{code}, $e->{message});
    }
    _json_error(500, 'interne serverfout');
}

sub _signal_error {
    my ($code, $message) = @_;
    die WaveSync::Error->new($code, $message);
}
