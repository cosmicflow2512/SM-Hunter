#!/usr/bin/env python3
"""Small SMS reservation monitor for authorized testing workflows."""

import json
import os
import random
import signal
import sys
import time

import requests


API_URL = "https://api.grizzlysms.com/stubs/handler_api.php"
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

API_KEY = os.environ.get("SMS_API_KEY", "").strip()
SERVICE = os.environ.get("SMS_SERVICE", "wx").strip()
COUNTRY = os.environ.get("SMS_COUNTRY", "62").strip()
MAX_PRICE = float(os.environ.get("MAX_PRICE", "5"))
PRIORITY_PROVIDERS = os.environ.get(
    "PRIORITY_PROVIDERS", "406,393,405,311"
).strip()
EXCLUDED_PROVIDERS = os.environ.get(
    "EXCLUDED_PROVIDERS", "396,415,418,12,162,25,405"
).strip()
BURST = max(1, int(os.environ.get("BURST", "4")))
CYCLE_PAUSE = max(1.0, float(os.environ.get("CYCLE_PAUSE", "8")))
POLL_INTERVAL = max(2.0, float(os.environ.get("POLL_INTERVAL", "5")))
HOLD_SECONDS = max(60, int(os.environ.get("HOLD_SECONDS", "900")))
MAX_RESERVATIONS = max(1, int(os.environ.get("MAX_RESERVATIONS", "1")))
EXPECTED_EGRESS_COUNTRY = os.environ.get("EXPECTED_EGRESS_COUNTRY", "TR").upper()

PUSHOVER_TOKEN = os.environ.get("PUSHOVER_APP_TOKEN", "").strip()
PUSHOVER_USER = os.environ.get("PUSHOVER_USER_KEY", "").strip()
PUSHOVER_DEVICE = os.environ.get("PUSHOVER_DEVICE", "").strip()
PUSHOVER_PRIORITY = int(os.environ.get("PUSHOVER_PRIORITY", "1"))

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "sms-hunter/1.0",
        "Accept": "application/json,text/plain,*/*",
    }
)

active_id = None


class ApiFailure(RuntimeError):
    pass


def request_api(action, **extra):
    params = {"api_key": API_KEY, "action": action, **extra}
    last_error = None
    for attempt in range(5):
        try:
            response = SESSION.get(API_URL, params=params, timeout=20)
            if response.status_code == 429 or response.status_code >= 500:
                raise ApiFailure(f"HTTP {response.status_code}")
            response.raise_for_status()
            text = response.text.strip()
            try:
                return response.json()
            except (ValueError, json.JSONDecodeError):
                return text
        except (requests.RequestException, ApiFailure) as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(min(2 ** (attempt + 1), 20) + random.random())
    raise ApiFailure(f"API nicht erreichbar: {last_error}")


def verify_egress():
    response = SESSION.get("https://ipinfo.io/country", timeout=15)
    response.raise_for_status()
    detected = response.text.strip().upper()
    print(f"VPN-Ausgangsland: {detected}", flush=True)
    if detected != EXPECTED_EGRESS_COUNTRY:
        raise RuntimeError(
            f"Sicherheitsabbruch: erwartet {EXPECTED_EGRESS_COUNTRY}, erhalten {detected}"
        )


def pushover(title, message):
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        return
    data = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": PUSHOVER_PRIORITY,
    }
    if PUSHOVER_DEVICE:
        data["device"] = PUSHOVER_DEVICE
    try:
        response = SESSION.post(PUSHOVER_URL, data=data, timeout=15)
        result = response.json()
        if response.status_code != 200 or result.get("status") != 1:
            print(f"Pushover abgelehnt: {result.get('errors', response.status_code)}")
    except Exception as exc:
        print(f"Pushover fehlgeschlagen: {exc}")


def stop_activation(activation_id, completed=False):
    status = 6 if completed else 8
    try:
        reply = request_api("setStatus", id=activation_id, status=status)
        print(f"Aktivierung {activation_id}, Statusantwort: {reply}")
    except Exception as exc:
        print(f"Statusänderung für {activation_id} fehlgeschlagen: {exc}")


def parse_purchase(reply):
    if not isinstance(reply, dict):
        return None
    activation_id = reply.get("activationId") or reply.get("id")
    phone = reply.get("phoneNumber") or reply.get("phone")
    cost = reply.get("activationCost") or reply.get("cost")
    provider = reply.get("providerId") or reply.get("provider") or "unbekannt"
    if activation_id and phone:
        return {
            "id": str(activation_id),
            "phone": str(phone),
            "cost": float(cost) if cost is not None else None,
            "provider": str(provider),
        }
    return None


def reserve_number():
    filters = []
    if PRIORITY_PROVIDERS:
        filters.extend({"providerIds": PRIORITY_PROVIDERS} for _ in range(BURST))
    filters.append({"exceptProviderIds": EXCLUDED_PROVIDERS})

    for selected_filter in filters:
        reply = request_api(
            "getNumberV2",
            service=SERVICE,
            country=COUNTRY,
            maxPrice=MAX_PRICE,
            **selected_filter,
        )
        purchase = parse_purchase(reply)
        if purchase:
            if purchase["cost"] is not None and purchase["cost"] > MAX_PRICE:
                print("Preislimit überschritten; Reservierung wird abgebrochen.")
                stop_activation(purchase["id"], completed=False)
                continue
            return purchase

        reply_text = reply if isinstance(reply, str) else json.dumps(reply)
        if any(code in reply_text for code in ("BAD_KEY", "NO_BALANCE", "WRONG_SERVICE")):
            raise ApiFailure(reply_text)
        time.sleep(0.7)
    return None


def extract_code(reply):
    if isinstance(reply, dict):
        sms = reply.get("sms")
        if isinstance(sms, dict) and sms.get("code"):
            return str(sms["code"])
        if isinstance(sms, list):
            for item in reversed(sms):
                if isinstance(item, dict) and item.get("code"):
                    return str(item["code"])
    if isinstance(reply, str) and reply.startswith("STATUS_OK:"):
        return reply.split(":", 1)[1].strip()
    return None


def poll_for_message(activation_id):
    deadline = time.monotonic() + HOLD_SECONDS
    while time.monotonic() < deadline:
        reply = request_api("getStatusV2", id=activation_id)
        code = extract_code(reply)
        if code:
            return code
        if isinstance(reply, str) and reply in {"STATUS_CANCEL", "NO_ACTIVATION"}:
            return None
        time.sleep(POLL_INTERVAL)
    return None


def cleanup_and_exit(signum, _frame):
    global active_id
    print(f"Signal {signum} empfangen; räume auf.")
    if active_id:
        stop_activation(active_id, completed=False)
        active_id = None
    sys.exit(128 + signum)


def main():
    global active_id
    if not API_KEY:
        raise RuntimeError("SMS_API_KEY fehlt")
    if bool(PUSHOVER_TOKEN) != bool(PUSHOVER_USER):
        raise RuntimeError("Pushover benötigt Application Token und User Key")

    verify_egress()
    balance = request_api("getBalance")
    print(f"Kontostand-Antwort: {balance}", flush=True)

    reservations = 0
    while reservations < MAX_RESERVATIONS:
        purchase = reserve_number()
        if not purchase:
            print(f"Keine passende Nummer; neuer Versuch in {CYCLE_PAUSE:.0f}s.")
            time.sleep(CYCLE_PAUSE)
            continue

        reservations += 1
        active_id = purchase["id"]
        phone = purchase["phone"]
        cost = purchase["cost"]
        provider = purchase["provider"]
        print(
            f"Nummer reserviert: +{phone}, Preis {cost}, Anbieter {provider}",
            flush=True,
        )
        pushover(
            "Türkische Nummer verfügbar",
            f"Nummer: +{phone}\nPreis: {cost}\nAnbieter: {provider}",
        )

        code = poll_for_message(active_id)
        if code:
            stop_activation(active_id, completed=True)
            active_id = None
            print(f"SMS-Code: {code}", flush=True)
            pushover("SMS-Code eingetroffen", f"Code: {code}\nNummer: +{phone}")
            return 0

        print("Kein Code innerhalb der Haltezeit; Stornierung wird versucht.")
        stop_activation(active_id, completed=False)
        active_id = None

    print("Maximale Reservierungen für diesen Lauf erreicht.")
    return 2


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup_and_exit)
    signal.signal(signal.SIGINT, cleanup_and_exit)
    try:
        raise SystemExit(main())
    except Exception as exc:
        if active_id:
            stop_activation(active_id, completed=False)
        print(f"FATAL: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
