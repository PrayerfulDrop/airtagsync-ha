# AirTagSync (Home Assistant integration)

Track your Apple AirTags in Home Assistant without a phone, without the Find My web app, and without third-party clouds. AirTagSync runs **inside** Home Assistant, reaches over SSH to a Mac signed into your Apple ID, decrypts the local FindMy cache, and creates native `device_tracker` + `sensor` entities — one per AirTag.

**HACS-installable. Config flow UI. No YAML.**

```
Mac (any Mac signed in to your Apple ID)        Home Assistant
─────────────────────────────────────────       ─────────────────────────────
  findmylocateagent (Apple background daemon)   ┌────────────────────────────┐
       ↓ writes                                 │ AirTagSync custom integ.   │
  ~/Library/Caches/com.apple.findmy.fmipcore/   │                            │
  Items.data (encrypted) ◄── SSH/SFTP poll ─────│  • asyncssh fetch          │
                                                │  • ChaCha20-Poly1305       │
  Find My.app (kept running by a 4-line         │    decrypt with FMIP key   │
  launchd plist — no Python on the Mac)         │  • device_tracker.airtag_* │
                                                │  • sensor.airtag_*_battery │
                                                └────────────────────────────┘
```

## Why an HA integration (not a Mac service)?

- Configuration lives in HA's encrypted storage — set up once via the UI.
- Updates ship via HACS, not a `git pull` on the Mac.
- Mac becomes a passive data source. The only thing you maintain on the Mac is FindMy.app being open.

## What this does **not** do

- It does **not** query Apple's gateway directly — that requires extracting the `BeaconStore` key, which is in a SIP-protected keychain item this flow doesn't capture yet. (Phase 3.)
- It does **not** track friends, phones, or Macs — only AirTags and Find My-tagged accessories you own.
- It does **not** work without a Mac that's signed in to your Apple ID and has FindMy.app open.

## Prerequisites

| Where | Needed |
| --- | --- |
| Mac | macOS 13+ signed into the Apple ID that owns the AirTags, **SIP disabled**, `amfi_get_out_of_my_way=0x1` boot-arg, FindMy.app opened at least once. |
| Mac | Remote Login enabled (System Settings → General → Sharing → Remote Login). |
| Mac | The integration's public SSH key added to `~/.ssh/authorized_keys` (restricted with `command=` so it can only read Items.data). |
| HA | Home Assistant 2024.1 or newer. HACS installed if you want UI install. |
| Network | Same LAN — HA's host needs TCP 22 to the Mac. |

## Install

### Via HACS (recommended)

1. HACS → Integrations → ⋯ → Custom repositories → add `https://github.com/PrayerfulDrop/airtagsync-ha` with category **Integration**.
2. Find **AirTagSync** in the integrations list → Install.
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → AirTagSync.

### Manual

```bash
cd /config
git clone https://github.com/PrayerfulDrop/airtagsync-ha tmp-airtagsync
mkdir -p custom_components
cp -r tmp-airtagsync/custom_components/airtagsync custom_components/
rm -rf tmp-airtagsync
```
Restart HA → Settings → Devices & Services → Add Integration → AirTagSync.

## One-time Mac setup

### 1. Extract the FMIP key

This uses [findmy-key-extractor](https://github.com/PrayerfulDrop/findmy-key-extractor) — a fork with Intel + Apple Silicon support. (Upstream PR: [manonstreet/findmy-key-extractor#4](https://github.com/manonstreet/findmy-key-extractor/pull/4).)

```bash
git clone https://github.com/PrayerfulDrop/findmy-key-extractor.git ~/src/findmy-key-extractor
cd ~/src/findmy-key-extractor
./extract.sh
```

When it finishes, you'll have three files in `keys/`. The one AirTagSync needs is `FMIPDataManager.bplist` (171 bytes). You'll paste its base64 form into the HA config flow.

```bash
base64 -i ~/src/findmy-key-extractor/keys/FMIPDataManager.bplist | pbcopy
# the bplist is now on your clipboard, ready to paste into HA
```

⚠️ **Anyone with this file can read your AirTag locations.** Treat it like a password.

### 2. Enable Remote Login

System Settings → General → Sharing → Remote Login → On. Restrict to a single user (your Mac account) for tightness.

### 3. Add the integration's SSH key

The integration generates a keypair for you at config-flow time, but if you'd rather install one ahead of time you can. The pattern that ships with this repo is a restricted line:

```
command="if [ \"$SSH_ORIGINAL_COMMAND\" = \"cat ~/Library/Caches/com.apple.findmy.fmipcore/Items.data\" ]; then eval \"$SSH_ORIGINAL_COMMAND\"; else echo refused; exit 1; fi",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA…
```

This way, even if the private key leaks, the only command anyone can run with it is `cat Items.data`. They cannot get a shell, forward ports, or read any other file.

### 4. Keep FindMy.app running

`Items.data` only refreshes while FindMy.app is open. Drop this LaunchAgent in `~/Library/LaunchAgents/com.user.findmy-keepalive.plist` (no Python, no service code):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.user.findmy-keepalive</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string><string>-gj</string><string>/System/Applications/FindMy.app</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>600</integer>
</dict></plist>
```

Then `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.user.findmy-keepalive.plist`. FindMy.app will be re-launched every 10 minutes if it ever quits.

## Configuring

Settings → Devices & Services → Add Integration → **AirTagSync**. The form asks:

| Field | What |
| --- | --- |
| Mac hostname or IP | e.g. `192.168.5.1` or `mac.local` |
| SSH port | `22` |
| Mac username | the Mac account FindMy.app is signed into |
| SSH private key | paste the ed25519 private key whose public half is in the Mac's `authorized_keys` |
| FMIPDataManager.bplist | paste the base64'd bplist (or just the raw 32-byte key in base64) |
| Home latitude / longitude / radius | center + radius for the "home" state |
| Poll interval | seconds between SSH fetches; default 30s, Apple's network refreshes the cache about once per minute so faster won't help much |
| Include AirPods / audio accessories | off by default |

The integration validates everything before saving: it SSHes to the Mac, fetches `Items.data`, decrypts with your key, and counts items. If any step fails the form shows a specific error.

## What you get

Per AirTag (where `<name>` is `swim_bag`, `evelyns_bike`, etc):

- `device_tracker.<name>` — GPS source_type tracker with `latitude`, `longitude`, `gps_accuracy`. HA's zone resolver will mark it `home` / `not_home` / other zones automatically.
- `sensor.<name>_battery` — `normal`, `low`, `critical`, or `unknown` (Apple reports a status enum, not %).
- A device card grouping both, with manufacturer = "Apple" and model = "AirTag".

## How it refreshes

The integration polls every `scan_interval_s` seconds (default 30s):

1. Open SSH connection to the Mac.
2. `cat ~/Library/Caches/com.apple.findmy.fmipcore/Items.data` (this is all the restricted SSH key allows).
3. ChaCha20-Poly1305 decrypt with the stored FMIP key.
4. Parse, filter (AirPods filter respected), update entities.

The natural update cadence is bounded by **how often Apple's network learns a new fix for your AirTag** — typically 30s to 15min depending on how many iPhones pass near it. Polling faster than that won't get fresher data.

## Architecture notes

- `coordinator.py` is a `DataUpdateCoordinator` so HA handles the timer + listener dispatch.
- `asyncssh` is used non-blocking; one open connection per poll, closed immediately.
- The FMIP key is stored as base64 in the config entry data — HA encrypts config entries at rest.
- The SSH private key is stored the same way. HA encrypts at rest.
- No third-party servers are involved. No data leaves your LAN.

## Troubleshooting

**"SSH auth failed"** — the public key for the private key you pasted isn't in the Mac's `~/.ssh/authorized_keys`. Add it.

**"SSH connect failed"** — Mac isn't reachable on port 22. Verify Remote Login is on, firewall isn't blocking, IP is correct, both hosts are on the same LAN.

**"Decrypt failed"** — the file was fetched but the FMIP key doesn't open it. Re-extract the keys; `FMIPDataManager.bplist` rotates if you sign out / sign in to iCloud.

**No entities appear** — open Settings → Devices & Services → AirTagSync → "Logs" — the coordinator emits detailed errors on each refresh failure.

## License

MIT.

## Acknowledgements

- [findmy-key-extractor](https://github.com/manonstreet/findmy-key-extractor) (manonstreet) — original ARM64 key extractor; this project's contributor extended it for Intel.
- [FindMySyncPlus](https://github.com/manonstreet/FindMySyncPlus) (manonstreet) — proved out the ChaCha20-Poly1305 path against `Items.data`.
- [findmy.py](https://github.com/malmeloo/FindMy.py) (malmeloo) — Apple Find My protocol reference; used in this project's Phase 3 design.
