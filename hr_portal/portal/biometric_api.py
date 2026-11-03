"""Endpoints the biometric machines (or their software) call. No login / CSRF: the machine proves itself with a key.

1) JSON push (any machine / middleware / small script)
   POST /api/biometric/punch/
   Header  X-Device-Key: <api key shown on the Biometric page>      (or  "device_key" inside the JSON)
   Body    {"employee_id": "EMP001", "timestamp": "2026-11-03 09:05:00"}            one punch
           {"punches": [{"employee_id": "EMP001", "timestamp": "..."}, ...]}       many punches
   `timestamp` is optional (= now) and is read as local time (Asia/Kolkata) unless it ends with Z / +05:30.

2) ZKTeco "ADMS / cloud server" push (most Indian fingerprint machines)
   Machine menu -> Comm. -> Cloud Server: address = this server, port = 8000.  The machine's serial number must be
   added on the Biometric page.   GET/POST /iclock/cdata , GET /iclock/getrequest
"""
import json
from datetime import datetime

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from . import services
from .models import BiometricDevice


def _aware(value):
    """'2026-11-03 09:05:00' / ISO text / unix seconds -> aware datetime (local time when no zone is given)."""
    if value in (None, ""):
        return timezone.now()
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit() and len(value) >= 9):
        return datetime.fromtimestamp(int(value), tz=timezone.get_current_timezone())
    text = str(value).strip().replace("Z", "+00:00")
    dt = parse_datetime(text)
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError(f"Cannot read the time: {value!r}")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _device_from_key(request, body=None):
    key = request.headers.get("X-Device-Key") or request.GET.get("key") or (body or {}).get("device_key") or ""
    return BiometricDevice.objects.filter(api_key=key, is_active=True).first() if key else None


@csrf_exempt
def punch(request):
    if request.method != "POST":
        return JsonResponse({"detail": "POST only"}, status=405)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Body must be JSON."}, status=400)
    device = _device_from_key(request, body if isinstance(body, dict) else {})
    if device is None:
        return JsonResponse({"detail": "Wrong or missing device key (header X-Device-Key)."}, status=401)
    raw = body.get("punches") if isinstance(body, dict) and "punches" in body else [body]
    items = []
    try:
        for r in raw:
            uid = r.get("employee_id") or r.get("user_id") or r.get("pin") or r.get("code")
            if not uid:
                raise ValueError("Each punch needs employee_id.")
            items.append((str(uid), _aware(r.get("timestamp") or r.get("time"))))
    except (ValueError, AttributeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse({"ok": True, **services.process_device_punches(device, items)})


# ---------------------------------------------------------------- ZKTeco ADMS push protocol
def _adms_device(request):
    sn = (request.GET.get("SN") or request.GET.get("sn") or "").strip()
    return BiometricDevice.objects.filter(serial=sn, is_active=True).first() if sn else None


@csrf_exempt
def adms_cdata(request):
    dev = _adms_device(request)
    if dev is None:
        return HttpResponse("ERROR: unknown device serial number", status=403, content_type="text/plain")
    if request.method == "GET":          # the machine says hello and asks for its settings
        dev.last_seen = timezone.now()
        dev.save(update_fields=["last_seen"])
        return HttpResponse(f"GET OPTION FROM: {dev.serial}\nATTLOGStamp=None\nOPERLOGStamp=9999\nErrorDelay=30\n"
                            "Delay=10\nTransTimes=00:00;14:05\nTransInterval=1\nTransFlag=TransData AttLog\n"
                            "Realtime=1\nEncrypt=0\n", content_type="text/plain")
    table = (request.GET.get("table") or "").upper()
    if table != "ATTLOG":
        return HttpResponse("OK", content_type="text/plain")
    items = []
    for line in request.body.decode("utf-8", "ignore").splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[0]:
            try:
                items.append((parts[0], _aware(parts[1])))
            except ValueError:
                continue
    services.process_device_punches(dev, items)
    return HttpResponse(f"OK: {len(items)}", content_type="text/plain")


@csrf_exempt
def adms_getrequest(request):
    dev = _adms_device(request)
    if dev is not None:
        dev.last_seen = timezone.now()
        dev.save(update_fields=["last_seen"])
    return HttpResponse("OK", content_type="text/plain")
