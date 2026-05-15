"""ChaCha20-Poly1305 decryptor for FindMy Items.data."""

from __future__ import annotations

import math
import plistlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    horizontal_accuracy: float
    timestamp_ms: int
    altitude: float | None


@dataclass(frozen=True)
class Item:
    identifier: str
    name: str
    serial_number: str | None
    is_audio_accessory: bool
    battery_status: int | None
    system_version: str | None
    location: Location | None


def extract_fmip_key(bplist_bytes: bytes) -> bytes:
    """Extract the 32-byte FMIP symmetric key from FMIPDataManager.bplist."""
    plist = plistlib.loads(bplist_bytes)
    key = plist["symmetricKey"]["key"]["data"]
    if len(key) != 32:
        raise ValueError(f"FMIP key length {len(key)} != 32")
    return key


def decrypt_items_data(items_blob: bytes, fmip_key: bytes) -> list[dict]:
    """
    Decrypt Items.data bytes.

    Outer plist: {signature: HMAC(64), encryptedData: nonce(12) || ct || tag(16)}.
    Decrypt with ChaCha20-Poly1305 using the FMIP symmetric key.
    """
    outer = plistlib.loads(items_blob)
    enc = outer["encryptedData"]
    nonce = enc[:12]
    ct_with_tag = enc[12:]
    plaintext = ChaCha20Poly1305(fmip_key).decrypt(nonce, ct_with_tag, None)
    inner = plistlib.loads(plaintext)
    if not isinstance(inner, list):
        raise ValueError(f"Expected list, got {type(inner).__name__}")
    return inner


def parse_items(raw: list[dict], include_audio: bool) -> list[Item]:
    """Filter raw item dicts and convert to typed Item objects."""
    out: list[Item] = []
    for d in raw:
        is_audio = bool(d.get("isAppleAudioAccessory", False))
        if is_audio and not include_audio:
            continue

        ident = d.get("identifier")
        name = d.get("name")
        if not ident or not name:
            continue

        loc: Location | None = None
        loc_d = d.get("location")
        if isinstance(loc_d, dict) and "latitude" in loc_d and "longitude" in loc_d:
            loc = Location(
                latitude=float(loc_d["latitude"]),
                longitude=float(loc_d["longitude"]),
                horizontal_accuracy=float(loc_d.get("horizontalAccuracy") or 0),
                timestamp_ms=int(loc_d.get("timeStamp") or 0),
                altitude=(float(loc_d["altitude"]) if loc_d.get("altitude") is not None else None),
            )

        out.append(Item(
            identifier=ident,
            name=name,
            serial_number=(d.get("serialNumber") or None),
            is_audio_accessory=is_audio,
            battery_status=(int(d["batteryStatus"]) if d.get("batteryStatus") is not None else None),
            system_version=(d.get("systemVersion") or None),
            location=loc,
        ))
    return out


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_BATTERY_LABELS = {0: "unknown", 1: "critical", 2: "normal", 3: "medium", 4: "low"}


def battery_label(code: int | None) -> str:
    if code is None:
        return "unknown"
    return _BATTERY_LABELS.get(code, f"status_{code}")
