# Mac setup guide

AirTagSync reads the FindMy app's local cache. To make that work you must:

1. Disable two macOS security features so a debugger can attach to Apple-signed binaries.
2. Run a one-time key extractor and copy the result to Home Assistant.
3. Enable Remote Login and install a single, restricted SSH key.
4. Keep FindMy.app running with a 4-line launch plist.

Every step is reversible. Nothing this guide tells you to do is permanent.

> ⚠️ Disabling SIP and AMFI weakens macOS's defenses. Only do this on a Mac you control, on a network you trust. You can re-enable both with one command each when you're done extracting keys — the integration only needs the *result*, not the relaxed state.

## 0. What you need

- A Mac signed in to the Apple ID that owns your AirTags.
- 30 minutes uninterrupted, plus two reboots.
- A USB keyboard if the Mac is headless (you'll need to boot to Recovery).
- Admin password for the Mac.

## 1. Disable System Integrity Protection

SIP prevents non-Apple code from attaching debuggers to Apple binaries. The extractor uses `lldb` to read decryption keys out of FindMy's process memory — SIP must be off for this to work.

### Apple Silicon (M1 / M2 / M3 / M4)

1. **Shut down** the Mac. (Not restart — fully shut down.)
2. Hold the **Power button** until you see "Loading startup options."
3. Click **Options** → Continue. Pick your admin user and authenticate.
4. Top menu bar → **Utilities** → **Terminal**.
5. Run:
   ```bash
   csrutil disable
   ```
   Type `y` when asked, enter your admin password.
6. Top-left  menu → **Restart**.

### Intel

1. **Restart** while holding `⌘ + R` to enter Recovery Mode.
2. Top menu bar → **Utilities** → **Terminal**.
3. Run:
   ```bash
   csrutil disable
   ```
4. Top-left  menu → **Restart**.

### Verify after reboot

```bash
csrutil status
```

You should see `System Integrity Protection status: disabled.`

## 2. Set the AMFI boot-arg

Apple Mobile File Integrity is the second layer — even with SIP off, AMFI still blocks the debugger from attaching to Apple-signed processes. To turn it off you set a boot-arg in NVRAM.

In Terminal (regular login, not Recovery):

```bash
sudo nvram boot-args="amfi_get_out_of_my_way=0x1"
```

Reboot:

```bash
sudo reboot
```

After reboot, verify:

```bash
nvram boot-args
# expected output:
# boot-args  amfi_get_out_of_my_way=0x1
```

If the output is empty or missing the AMFI flag, the NVRAM write didn't stick. Repeat the `sudo nvram boot-args=...` and reboot again.

## 3. Open FindMy.app and let it pair

Open the **Find My** app from Launchpad or Spotlight. Sign in if it asks. Wait until your AirTags appear in the "Items" tab — this means the app has fetched their data from iCloud and written the local keys we're about to extract. Quit the app.

## 4. Grant Full Disk Access to your Terminal

The extractor needs to read files inside `~/Library/com.apple.icloud.searchpartyd/`, which is protected by macOS's privacy system.

- System Settings → Privacy & Security → **Full Disk Access**
- Click the `+` and add **Terminal** (`/System/Applications/Utilities/Terminal.app`).
- Toggle it **on**.
- Close and re-open Terminal so the new permission applies.

## 5. Run the extractor

```bash
git clone https://github.com/PrayerfulDrop/findmy-key-extractor.git ~/src/findmy-key-extractor
cd ~/src/findmy-key-extractor
./extract.sh
```

The extractor:

1. Quits any stale `lldb` and `findmylocateagent` processes.
2. Restarts FindMy.app while two `lldb` waiters are sitting on the relevant symbols.
3. Captures three Apple-internal keys at the moment FindMy.app uses them.
4. Writes the keys into `~/src/findmy-key-extractor/keys/`.

Successful run leaves three files in `keys/`:

| File | Size | What |
| --- | --- | --- |
| `LocalStorage.key` | 32 bytes | AES key for findmylocateagent's SQLite DB. **Not used by AirTagSync.** |
| `FMFDataManager.bplist` | 171 bytes | Find-My-Friends encryption keys. **Not used by AirTagSync.** |
| `FMIPDataManager.bplist` | 171 bytes | ⭐ **The one AirTagSync needs.** Find-My-iPhone symmetric key — this decrypts Items.data. |

If the extractor fails or any file is missing, see [Troubleshooting the extractor](#troubleshooting-the-extractor) below.

## 6. Convert the FMIP file to base64

The HA config flow expects this pasted into a text box.

```bash
base64 -i ~/src/findmy-key-extractor/keys/FMIPDataManager.bplist | pbcopy
```

It's now on your clipboard. Don't lose it — but also don't store it anywhere unencrypted; treat this string like a password.

## 7. Generate an SSH key for AirTagSync

This key is dedicated to the integration. It's restricted to running exactly one command (`cat Items.data`) — even if it leaks, an attacker can't get a shell or read other files.

```bash
ssh-keygen -t ed25519 -N "" -f ~/src/airtagsync-ha-key -C "airtagsync-ha-readonly"
```

Install the **public** half with a strict restriction:

```bash
PUB=$(cat ~/src/airtagsync-ha-key.pub)
RESTRICT='command="if [ \"$SSH_ORIGINAL_COMMAND\" = \"cat ~/Library/Caches/com.apple.findmy.fmipcore/Items.data\" ]; then eval \"$SSH_ORIGINAL_COMMAND\"; else echo refused; exit 1; fi",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty'
echo "$RESTRICT $PUB" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Test it works:

```bash
ssh -i ~/src/airtagsync-ha-key -o BatchMode=yes localhost \
    'cat ~/Library/Caches/com.apple.findmy.fmipcore/Items.data' | head -c 8
# expected: bplist00
```

And test that the restriction is in force:

```bash
ssh -i ~/src/airtagsync-ha-key -o BatchMode=yes localhost 'whoami'
# expected: refused
```

The **private** half — `~/src/airtagsync-ha-key` (no `.pub`) — is what you'll paste into the HA config flow:

```bash
cat ~/src/airtagsync-ha-key | pbcopy
```

## 8. Enable Remote Login

System Settings → General → Sharing → **Remote Login** → on.

Recommended: leave "Allow access for" set to **Only these users** and add only your own user. This integration only needs SSH access for that one user.

## 9. Keep FindMy.app running

`Items.data` only refreshes while FindMy.app is running. The integration polls the **cached** data; the cache only gets updated when FindMy.app is alive.

Create `~/Library/LaunchAgents/com.user.findmy-keepalive.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.user.findmy-keepalive</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-gj</string>
    <string>/System/Applications/FindMy.app</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>600</integer>
</dict></plist>
```

Load it:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.user.findmy-keepalive.plist
```

`open -gj` launches FindMy hidden (no dock bounce, no window). The plist re-runs every 10 minutes — `open` is idempotent on an already-running app, so this is a free way to keep FindMy alive forever.

## 10. (Optional) Re-enable SIP and clear the boot-arg

The integration **does not** need SIP or AMFI relaxed at runtime — only the one-time extraction step did. Once you have `FMIPDataManager.bplist` extracted and pasted into HA, you can roll back:

```bash
sudo nvram -d boot-args
```

Then reboot into Recovery (same procedure as step 1) and:

```bash
csrutil enable
```

Reboot again. The integration will continue to work — the FMIP key keeps decrypting Items.data because it's still the same symmetric key Apple's daemon uses.

You'll need to redo the disable/extract dance only if:

- You sign out of iCloud and back in (Apple rotates the symmetric key).
- You change Apple ID password.
- You upgrade macOS to a major version that changes the encryption scheme (rare).

## Troubleshooting the extractor

**`extract.sh` runs but produces no files.** The most common cause is a stale `findmylocateagent` that was already alive when `lldb --wait-for` tried to attach. Force a clean state:

```bash
sudo pkill -9 lldb
sudo pkill -9 findmylocateagent  # may say no process found — that's ok
./extract.sh
```

**`csrutil status` still says enabled after reboot.** You didn't actually run `csrutil disable` in Recovery Mode. Make sure you booted into Recovery (Apple Silicon: hold Power on shutdown; Intel: hold ⌘R on restart) and ran `csrutil disable` from Recovery's Terminal — running it from regular Terminal fails silently on M-series.

**`nvram boot-args` is empty.** Some Macs reset NVRAM during reboot. After running `sudo nvram boot-args=...`, immediately verify with `nvram boot-args` before rebooting. If it shows up there but is missing after reboot, you may need to also disable secure boot in Recovery (Apple Silicon only): Recovery → Utilities → Startup Security Utility → "Reduced Security" → Allow user management of kernel extensions.

**`lldb` says "process timeout" or "operation not permitted."** AMFI is still active. Verify with `nvram boot-args` — it must show `amfi_get_out_of_my_way=0x1`.

**FindMy.app prompts for Apple ID password every time it opens.** This is normal once, after sign-in changes. Just provide it. The extractor watches for the symbol calls that happen *after* you're signed in, so the timing usually works out automatically.

## What gets stored and where

| What | Where |
| --- | --- |
| `LocalStorage.key`, `FMIPDataManager.bplist`, `FMFDataManager.bplist` | `~/src/findmy-key-extractor/keys/` (your Mac) |
| AirTagSync SSH private key | `~/src/airtagsync-ha-key` (your Mac); copied once into HA's encrypted config entry |
| FMIP key (base64'd bplist) | HA's encrypted config entry, never written to disk in plaintext |

You can delete the extractor checkout and the `keys/` directory after pasting the FMIP key into HA. The integration only needs what's already inside HA at that point.

> If you'd prefer to keep the keys around for re-deploying to another HA instance later: leave them where they are, but make sure your Mac account password protects them (they're in your home directory, not world-readable).
