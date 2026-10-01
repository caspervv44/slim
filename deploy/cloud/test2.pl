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

# WakeSync cloudbeheer.
# Bewaart WakeSync-instellingen per apparaat. Een MyX-feedlink wordt alleen
# tijdelijk bewaard totdat de gekoppelde Pi hem via HTTPS heeft opgehaald en
# bevestigd; daarna wordt de URL uit het serverrecord verwijderd.

my $MAX_BODY = 64 * 1024;
my $SESSION_TTL = 30 * 24 * 60 * 60;
my $PBKDF2_ITERATIONS = 60_000;
my $PUBLIC_URL = $ENV{WEKKER_PUBLIC_URL} || _detect_public_url();
my $DATA_DIR = _choose_data_dir();
my $LOGO_DATA_URI = 'data:image/png;base64,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';

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
        service => 'wakesync',
        version => 10,
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
            schema_version => 10,
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

    # A3: toon nooit instellingen/formulierdata zonder geldige sessie.
    # CSRF wordt daarna afzonderlijk binnen de mutatie gecontroleerd.
    my $auth = _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        return { sid => $sid, session => $session };
    });
    if (!$auth->{session}) {
        _html(401, _login_page(
            $device_id,
            'Sessie verlopen. Log opnieuw in.'
        ));
    }

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

            # v10 bewaart meerdere alarmprofielen. De webpagina beheert bewust
            # het primaire alarm; spiegel de legacyvelden daarom ook naar
            # alarms[0] zodat een cloudpull de wijziging niet terugdraait.
            if (ref($settings->{alarm}{alarms}) ne 'ARRAY') {
                $settings->{alarm}{alarms} = [];
            }
            if (!@{$settings->{alarm}{alarms}}) {
                push @{$settings->{alarm}{alarms}}, { id => 'alarm-1' };
            }
            my $primary = $settings->{alarm}{alarms}[0];
            if (ref($primary) ne 'HASH') {
                $primary = { id => 'alarm-1' };
                $settings->{alarm}{alarms}[0] = $primary;
            }
            $primary->{id} ||= 'alarm-1';
            for my $key (qw(
                time enabled snooze_minutes sound volume speaker_enabled
                lamp_brightness lamp_blink blink_pattern ramp_up_seconds
            )) {
                $primary->{$key} = $settings->{alarm}{$key};
            }

            $settings->{lamp}{duration_after_button} =
                _clamp_int($form->{lamp_duration}, 1, 3600, 30);
            $settings->{lamp}{on_with_alarm} = $form->{lamp_on_with_alarm}
                ? JSON::PP::true : JSON::PP::false;

            $settings->{display}{brightness} =
                _clamp_int($form->{brightness}, 0, 100, 80);
            my %themes = map { $_ => 1 } qw(midnight ocean light amber);
            $settings->{display}{theme} =
                $themes{$form->{theme} || ''}
                    ? $form->{theme}
                    : ($settings->{display}{theme} || 'midnight');
            $settings->{display}{on_duration_seconds} =
                _clamp_int($form->{display_on_duration}, 1, 600, 30);
            $settings->{display}{sleep_after_seconds} =
                _clamp_int($form->{sleep_after_seconds}, 0, 3600, 60);
            my %sleep_views = map { $_ => 1 } qw(
                logo logo_time logo_time_date
            );
            $settings->{display}{sleep_view} =
                $sleep_views{$form->{sleep_view} || ''}
                    ? $form->{sleep_view}
                    : ($settings->{display}{sleep_view} || 'logo_time_date');
            my %sleep_effects = map { $_ => 1 } qw(
                off soft_glow pulse_glow aurora liquid_motion
            );
            $settings->{display}{sleep_effect} =
                $sleep_effects{$form->{sleep_effect} || ''}
                    ? $form->{sleep_effect}
                    : ($settings->{display}{sleep_effect} || 'soft_glow');
            $settings->{display}{sleep_glow_intensity} =
                _clamp_int($form->{sleep_glow_intensity}, 0, 100, 65);

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
        if (ref($e) eq 'WakeSync::Error') {
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

    # A3: toon nooit instellingen/formulierdata zonder geldige sessie.
    # CSRF wordt daarna afzonderlijk binnen de mutatie gecontroleerd.
    my $auth = _with_record($device_id, sub {
        my ($record) = @_;
        my ($sid, $session) = _current_session($record);
        return { sid => $sid, session => $session };
    });
    if (!$auth->{session}) {
        _html(401, _login_page(
            $device_id,
            'Sessie verlopen. Log opnieuw in.'
        ));
    }

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
        if (ref($e) eq 'WakeSync::Error') {
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
  <img class="login-logo" src="$LOGO_DATA_URI" alt="WakeSync">
  <div class="card">
    <h1 class="login-title">Online beheer</h1>
    <p class="muted login-copy">Log in met de gegevens op het scherm van je WakeSync.</p>
    <div class="public-feature-tabs" aria-label="Wat je kunt beheren">
      <div class="public-feature"><b>Alarm</b><span>Wektijd, snooze, volume, speaker en lampgedrag.</span></div>
      <div class="public-feature"><b>Weergave</b><span>Thema, tijdzone, slaapmodus en glow-effect.</span></div>
      <div class="public-feature"><b>Rooster</b><span>MyX/iCalendar, synchronisatie en zichtbare lesinformatie.</span></div>
      <div class="public-feature"><b>Systeem</b><span>Status, beveiliging en synchronisatie met je WakeSync.</span></div>
    </div>
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
        ? '<div class="notice ok">Opgeslagen. Je WakeSync neemt de wijziging meestal binnen 30 seconden over.</div>' : '';
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

    my $theme = $s->{display}{theme} || 'midnight';
    my @themes = (
        ['midnight', 'Midnight'],
        ['ocean', 'Ocean'],
        ['light', 'Light'],
        ['amber', 'Amber'],
    );
    my $theme_options = join '', map {
        my ($value, $label) = @$_;
        my $sel = $theme eq $value ? ' selected' : '';
        '<option value="' . $value . '"' . $sel . '>' . $label . '</option>'
    } @themes;

    my $sleep_after = int($s->{display}{sleep_after_seconds} // 60);
    my @sleep_delays = (
        [0, 'Nooit'],
        [30, '30 seconden'],
        [60, '1 minuut'],
        [300, '5 minuten'],
        [900, '15 minuten'],
    );
    my $sleep_delay_options = join '', map {
        my ($value, $label) = @$_;
        my $sel = $sleep_after == $value ? ' selected' : '';
        '<option value="' . $value . '"' . $sel . '>' . $label . '</option>'
    } @sleep_delays;

    my $sleep_view = $s->{display}{sleep_view} || 'logo_time_date';
    my @sleep_views = (
        ['logo', 'Alleen logo'],
        ['logo_time', 'Logo + tijd'],
        ['logo_time_date', 'Logo + tijd + datum'],
    );
    my $sleep_view_options = join '', map {
        my ($value, $label) = @$_;
        my $sel = $sleep_view eq $value ? ' selected' : '';
        '<option value="' . $value . '"' . $sel . '>' . $label . '</option>'
    } @sleep_views;

    my $sleep_effect = $s->{display}{sleep_effect} || 'soft_glow';
    my @sleep_effects = (
        ['off', 'Geen effect'],
        ['soft_glow', 'Zachte gloed'],
        ['pulse_glow', 'Pulserende gloed'],
        ['aurora', 'Aurora'],
        ['liquid_motion', 'Liquid Motion'],
    );
    my $sleep_effect_options = join '', map {
        my ($value, $label) = @$_;
        my $sel = $sleep_effect eq $value ? ' selected' : '';
        '<option value="' . $value . '"' . $sel . '>' . $label . '</option>'
    } @sleep_effects;

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
<div class="shell theme-@{[_h($theme)]}">
<header>
  <div class="brand-wrap">
    <img class="brand-logo" src="$LOGO_DATA_URI" alt="WakeSync">
    <div><div class="muted">Online beheer</div><div class="muted">WakeSync v10</div></div>
  </div>
  <form method="post">
    <input type="hidden" name="action" value="logout">
    <input type="hidden" name="d" value="@{[_h($device_id)]}">
    <button>Uitloggen</button>
  </form>
</header>
$saved$pw$err

<div class="manager">
<nav class="tabbar" aria-label="Beheeronderdelen">
  <button type="button" class="tabbtn active" data-tab="alarm">Alarm</button>
  <button type="button" class="tabbtn" data-tab="display">Weergave</button>
  <button type="button" class="tabbtn" data-tab="agenda">Rooster</button>
  <button type="button" class="tabbtn" data-tab="system">Systeem</button>
</nav>

<div class="panel-stack">
<form method="post" class="settings-form" id="settingsForm">
<input type="hidden" name="action" value="save">
<input type="hidden" name="d" value="@{[_h($device_id)]}">
<input type="hidden" name="csrf" value="$csrf">

<section class="settings-panel active" data-panel="alarm">
  <p class="panel-intro">Bewerk hier het primaire alarm. Extra alarmen voeg je op WakeSync zelf toe; lamp en speakerhardware kunnen later worden aangesloten.</p>
  <div class="panel-grid one">
    <section class="card">
      <h2>Primair alarm</h2>
      <div class="split">
        <label>Wektijd<input type="time" name="alarm_time" value="@{[_h($s->{alarm}{time} || '07:30')]}" required></label>
        <label>Snooze (minuten)<input type="number" min="1" max="60" name="snooze_minutes" value="@{[int($s->{alarm}{snooze_minutes} || 9)]}"></label>
      </div>
      <label class="check"><input type="checkbox" name="alarm_enabled" value="1"$alarm_checked> Alarm ingeschakeld</label>
      <label>Geluid<input name="sound" maxlength="64" value="@{[_h($s->{alarm}{sound} || 'beep')]}"></label>
      <label>Volume <span class="value-note">@{[int($s->{alarm}{volume} // 70)]}%</span>
      <input type="range" min="0" max="100" name="volume" value="@{[int($s->{alarm}{volume} // 70)]}"></label>
      <label class="check"><input type="checkbox" name="speaker_enabled" value="1"$speaker_checked> Speaker bij alarm</label>
      <label>Lampsterkte bij alarm <span class="value-note">@{[int($s->{alarm}{lamp_brightness} // 100)]}%</span>
      <input type="range" min="0" max="100" name="alarm_lamp_brightness" value="@{[int($s->{alarm}{lamp_brightness} // 100)]}"></label>
      <label class="check"><input type="checkbox" name="lamp_blink" value="1"$blink_checked> Lamp-effect gebruiken</label>
      <div class="split">
        <label>Lamp-effect<select name="blink_pattern">$blink_options</select></label>
        <label>Rustig opbouwen (seconden)<input type="number" min="0" max="3600" name="ramp_up_seconds" value="@{[int($s->{alarm}{ramp_up_seconds} // 30)]}"></label>
      </div>
    </section>
  </div>
</section>

<section class="settings-panel" data-panel="display">
  <p class="panel-intro">Pas tijdweergave, thema en het geanimeerde slaapbeeld aan.</p>
  <div class="panel-grid">
    <section class="card">
      <h2>Scherm &amp; tijd</h2>
      <label>Schermhelderheid <span class="value-note">@{[int($s->{display}{brightness} // 80)]}%</span>
      <input type="range" min="0" max="100" name="brightness" value="@{[int($s->{display}{brightness} // 80)]}"></label>
      <label>Thema<select name="theme">$theme_options</select></label>
      <label>Scherm actief na bediening (seconden)<input type="number" min="1" max="600" name="display_on_duration" value="@{[int($s->{display}{on_duration_seconds} // 30)]}"></label>
      <label>Slaapmodus na inactiviteit<select name="sleep_after_seconds">$sleep_delay_options</select></label>
      <label>Slaapweergave<select name="sleep_view">$sleep_view_options</select></label>
      <label>Slaapeffect<select name="sleep_effect">$sleep_effect_options</select></label>
      <label>Gloedsterkte <span class="value-note">@{[int($s->{display}{sleep_glow_intensity} // 65)]}%</span>
      <input type="range" min="0" max="100" name="sleep_glow_intensity" value="@{[int($s->{display}{sleep_glow_intensity} // 65)]}"></label>
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
      <label class="check"><input type="checkbox" name="visible_room" value="1"@{[$vc->('room')]}> Lokaal (alleen als MyX/iCalendar dit levert)</label>
      <label class="check"><input type="checkbox" name="visible_last_lesson" value="1"@{[$vc->('last_lesson')]}> Laatste les</label>
      <label class="check"><input type="checkbox" name="visible_day_agenda" value="1"@{[$vc->('day_agenda')]}> Dagsamenvatting</label>
    </section>
  </div>
</section>

<section class="settings-panel" data-panel="agenda">
  <p class="panel-intro">Beheer de MyX/Xedule-feed en hoe vaak WakeSync het rooster ververst.</p>
  <div class="panel-grid one">
    <section class="card">
      <h2>Rooster / MyX</h2>
      <div class="status-row">$feed_status</div>
      <label>Agenda-provider<select name="agenda_provider">$provider_options</select></label>
      <label>Automatisch synchroniseren (minuten)<input type="number" min="0" max="1440" name="auto_sync_minutes" value="@{[int($s->{agenda}{auto_sync_minutes} // 15)]}"></label>
      <label>MyX iCalendar / Feed-link
      <input name="myx_feed" autocomplete="off" spellcheck="false" placeholder="webcal://aventus.myx.nl/api/InternetCalendar/feed/…"></label>
      <p class="muted">De feed-URL wordt na ophalen door de Raspberry Pi weer uit de tijdelijke serveropslag verwijderd.</p>
      <label class="check danger-check"><input type="checkbox" name="clear_myx_feed" value="1"> MyX-feed van deze WakeSync verwijderen</label>
    </section>
  </div>
</section>

<div class="savebar" id="settingsSavebar"><button class="primary save" type="submit">Wijzigingen opslaan</button></div>
</form>

<section class="settings-panel" data-panel="system">
  <p class="panel-intro">Systeemstatus en beveiliging. Deze informatie verandert geen privé-instellingen zonder geldige sessie.</p>
  <div class="panel-grid">
    <section class="card">
      <h2>Status</h2>
      <p class="muted">Laatste wijziging: <b>@{[_h($r->{updated_at} || 'onbekend')]}</b></p>
      <p class="muted">Revisie: <b>@{[int($r->{revision} || 0)]}</b></p>
      <p class="muted">Wijzigingen worden normaal binnen ongeveer 30 seconden door de klok opgehaald.</p>
      <p class="muted"><b>Tijd:</b> WakeSync gebruikt lokaal de Raspberry Pi-systeemklok. Internet is niet nodig om de lopende klok te blijven tonen.</p>
    </section>
    <section class="card">
      <h2>Beveiliging</h2>
      <p class="muted">Iedere WakeSync gebruikt een willekeurige 256-bit beheer-ID en een aparte 256-bit device key.</p>
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
  </div>
</section>
</div>
</div>

<footer>WakeSync · apparaat @{[_h(substr($device_id, 0, 10))]}…</footer>
</div>

<script>
(function(){
  var buttons = document.querySelectorAll('[data-tab]');
  var panels = document.querySelectorAll('[data-panel]');
  var savebar = document.getElementById('settingsSavebar');
  function activate(name){
    buttons.forEach(function(button){
      button.classList.toggle('active', button.getAttribute('data-tab') === name);
    });
    panels.forEach(function(panel){
      panel.classList.toggle('active', panel.getAttribute('data-panel') === name);
    });
    if(savebar){ savebar.style.display = name === 'system' ? 'none' : 'block'; }
    try{ history.replaceState(null, '', '#'+name); }catch(e){}
  }
  buttons.forEach(function(button){
    button.addEventListener('click', function(){ activate(button.getAttribute('data-tab')); });
  });
  var requested = (location.hash || '#alarm').slice(1);
  if(!document.querySelector('[data-tab="'+requested+'"]')){ requested = 'alarm'; }
  activate(requested);
})();
</script>});
}

sub _page {
    my ($title, $content) = @_;
    return qq{<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>@{[_h($title)]} · WakeSync</title>
<style>
:root{
  color-scheme:light;--b:#1d73ea;--b2:#0f4fa8;--ink:#102033;--muted:#667085;
  --line:#dfe6ef;--bg:#f3f6fb;--card:#fff;--ok:#17795a;--bad:#b42318;
  --navy:#0b2346;--cyan:#24a7ff;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif
}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink)}
button,input,select{font:inherit}button{cursor:pointer}
.shell{max-width:1180px;margin:auto;padding:24px}.small-shell{max-width:520px;padding-top:5vh}
header{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:18px}
.brand-wrap{display:flex;align-items:center;gap:12px}.brand-logo{width:172px;height:auto;display:block}
.brand-text{font-size:1.3rem;font-weight:900;color:var(--navy);letter-spacing:-.03em}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 8px 28px rgba(20,42,80,.06)}
h1,h2{margin-top:0}h1{font-size:1.5rem}h2{font-size:1.08rem}
form{display:grid;gap:12px}label{display:grid;gap:6px;font-size:.9rem;font-weight:700}
.check{display:flex;align-items:center;gap:9px}.check input{width:auto}
.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.field-title{font-size:.86rem;font-weight:850;margin-top:4px}.value-note{float:right;color:var(--muted);font-weight:550}
.status-row{margin-bottom:8px}.pill{display:inline-flex;padding:6px 10px;border-radius:999px;background:#eef2f7;color:var(--muted);font-size:.78rem;font-weight:850}
.pill.ok{background:#eaf8f2;color:var(--ok)}
input,select,button{border:1px solid #cbd5e1;border-radius:12px;padding:10px 12px;background:white;color:var(--ink)}
input:focus,select:focus,button:focus{outline:3px solid rgba(36,167,255,.18);border-color:var(--cyan)}
.primary{background:var(--b);color:white;border-color:var(--b);font-weight:800}
.muted{color:var(--muted);font-size:.9rem}.notice{padding:11px 13px;border-radius:12px;margin-bottom:14px}
.ok{background:#eaf8f2;color:var(--ok)}.bad{background:#fff0ef;color:var(--bad)}
.security-note{margin-top:18px;padding:12px;background:#f7f9fc;border-radius:12px;color:var(--muted);font-size:.84rem;line-height:1.5}
footer{color:var(--muted);font-size:.78rem;margin-top:18px}
.savebar{position:sticky;bottom:0;z-index:20;padding:14px 0;background:linear-gradient(transparent,var(--bg) 24%)}
.save{width:100%;padding:14px}.lower-grid{margin-top:16px}.danger-check{color:var(--bad)}

.manager{display:grid;grid-template-columns:220px minmax(0,1fr);gap:18px;align-items:start}
.tabbar{position:sticky;top:14px;display:flex;flex-direction:column;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:10px;box-shadow:0 8px 24px rgba(20,42,80,.05)}
.tabbtn{border:0;background:transparent;text-align:left;padding:12px 13px;border-radius:12px;font-weight:800;color:#526176}
.tabbtn:hover,.tabbtn.active{background:#eaf2ff;color:#0f4fa8}
.panel-stack{min-width:0}.settings-panel{display:none}.settings-panel.active{display:block}
.panel-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.panel-grid.one{grid-template-columns:1fr}
.panel-intro{margin:0 0 14px;color:var(--muted);font-size:.9rem}
.public-feature-tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0 18px}
.public-feature{border:1px solid var(--line);border-radius:14px;padding:11px;background:#f8fbff}
.public-feature b{display:block;color:var(--navy);font-size:.88rem}.public-feature span{display:block;color:var(--muted);font-size:.75rem;margin-top:3px;line-height:1.35}
.login-logo{display:block;width:210px;max-width:70%;margin:0 auto 18px}
.login-title{text-align:center}.login-copy{text-align:center}

\@media(max-width:760px){
  .shell{padding:12px}.small-shell{padding:18px 12px}.brand-logo{width:145px}
  header{align-items:flex-start}.grid,.split,.panel-grid{grid-template-columns:1fr}
  .manager{display:block}.tabbar{top:0;z-index:30;flex-direction:row;overflow-x:auto;border-radius:0;margin:0 -12px 12px;padding:8px 12px;box-shadow:0 5px 18px rgba(20,42,80,.08)}
  .tabbtn{white-space:nowrap;text-align:center;min-width:max-content;padding:10px 12px}
  .card{padding:16px;border-radius:16px}.savebar{bottom:0}
  .public-feature-tabs{grid-template-columns:1fr 1fr}
}
\@media(max-width:430px){
  .public-feature-tabs{grid-template-columns:1fr}.brand-logo{width:132px}
  h1{font-size:1.32rem}
}
</style></head><body>$content</body></html>};
}

# ---------------------------------------------------------------------------
# Opslag

sub _choose_data_dir {
    # De oude, werkende test.pl gebruikt:
    #   C:/wamp64/www/veendomain/klok/data
    #
    # We bewaren WakeSync-records in een eigen submap zodat de oude
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

    die "WakeSync data-directory is niet schrijfbaar. "
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
            lamp_brightness lamp_blink blink_pattern ramp_up_seconds alarms
        ) },
        lamp => { map { $_ => 1 } qw(duration_after_button on_with_alarm) },
        display => { map { $_ => 1 } qw(
            brightness theme on_duration_seconds sleep_after_seconds sleep_view
            sleep_effect sleep_glow_intensity night_mode night_start night_end visible_fields
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

    if (exists $s->{alarm}{alarms}) {
        ref($s->{alarm}{alarms}) eq 'ARRAY'
            or _json_error(400, 'alarm.alarms moet een lijst zijn');
        scalar(@{$s->{alarm}{alarms}}) <= 12
            or _json_error(400, 'maximaal 12 alarmen toegestaan');
        my %alarm_keys = map { $_ => 1 } qw(
            id time enabled snooze_minutes sound volume speaker_enabled
            lamp_brightness lamp_blink blink_pattern ramp_up_seconds
        );
        my %ids;
        for my $alarm (@{$s->{alarm}{alarms}}) {
            ref($alarm) eq 'HASH'
                or _json_error(400, 'alarmprofiel moet een object zijn');
            for my $key (keys %$alarm) {
                $alarm_keys{$key}
                    or _json_error(400, "onbekende alarmprofielsleutel: $key");
            }
            defined($alarm->{id}) && $alarm->{id} =~ /\A[A-Za-z0-9._:-]{1,64}\z/
                or _json_error(400, 'ongeldig alarm-id');
            !$ids{$alarm->{id}}++
                or _json_error(400, 'dubbel alarm-id');
            _valid_time($alarm->{time})
                or _json_error(400, 'ongeldige alarmtijd');
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
    package WakeSync::Error;
    sub new {
        my ($class, $code, $message) = @_;
        return bless { code => $code, message => $message }, $class;
    }
}

sub _api_exception {
    my ($e) = @_;
    if (ref($e) eq 'WakeSync::Error') {
        _json_error($e->{code}, $e->{message});
    }
    _json_error(500, 'interne serverfout');
}

sub _signal_error {
    my ($code, $message) = @_;
    die WakeSync::Error->new($code, $message);
}
