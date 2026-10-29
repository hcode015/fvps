#!/usr/bin/env python3
import os, re, io, json, time, uuid, zipfile, calendar, threading, urllib.request, urllib.error

TG = os.environ.get("TG_TOKEN", "").strip()
PAT = os.environ.get("GH_PAT", "").strip()
RDP = os.environ.get("RDP_PASSWORD", "").strip()
OWNER_REPO = "hcode015/fvps"
WF = "windows-rdp.yml"
API = "https://api.github.com"
GHH = {"Authorization": "Bearer " + PAT,
       "Accept": "application/vnd.github+json",
       "X-GitHub-Api-Version": "2022-11-28",
       "User-Agent": "winbot"}
OWNER_FILE = "/opt/winbot/owner"
KB = {"keyboard": [[{"text": "ساخت ویندوز جدید"}],
                   [{"text": "وضعیت"}, {"text": "توقف سرویس"}]],
      "resize_keyboard": True}


def req(url, data=None, headers=None, method=None, timeout=120):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def req_noredir(url, headers):
    op = urllib.request.build_opener(_NoRedirect)
    try:
        with op.open(urllib.request.Request(url, headers=headers), timeout=120) as r:
            return r.status, r.headers.get("Location"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read()


def fetch_info(rid):
    d = json.loads(gh("/repos/%s/actions/runs/%s/artifacts" % (OWNER_REPO, rid)))
    for a in d.get("artifacts", []):
        if a.get("name") == "connection-info" and not a.get("expired"):
            code, loc, body = req_noredir(
                API + "/repos/%s/actions/artifacts/%s/zip" % (OWNER_REPO, a["id"]), GHH)
            data = req(loc) if code in (301, 302, 303, 307, 308) and loc else body
            zf = zipfile.ZipFile(io.BytesIO(data))
            txt = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
            m = re.search(r"IP=(\d+\.\d+\.\d+\.\d+)", txt)
            if m:
                dns = re.search(r"DNS=(\S+)", txt)
                return m.group(1), (dns.group(1).rstrip(".") if dns else "")
    return None


def tg(method, **params):
    body = json.dumps(params).encode("utf-8")
    return json.loads(req("https://api.telegram.org/bot%s/%s" % (TG, method), body,
                          {"Content-Type": "application/json"}))


def send(chat, text):
    tg("sendMessage", chat_id=chat, text=text[:4000], reply_markup=KB,
       disable_web_page_preview=True)


def send_doc(chat, filename, content, caption):
    b = "----wb" + uuid.uuid4().hex

    def part(name, value, fn=None):
        h = '--%s\r\nContent-Disposition: form-data; name="%s"' % (b, name)
        if fn:
            h += '; filename="%s"' % fn
        h += "\r\n"
        if fn:
            h += "Content-Type: application/octet-stream\r\n"
        h += "\r\n"
        if isinstance(value, str):
            value = value.encode("utf-8")
        return h.encode("utf-8") + value + b"\r\n"

    body = (part("chat_id", str(chat)) + part("caption", caption) +
            part("document", content, filename) +
            ("--%s--\r\n" % b).encode("utf-8"))
    req("https://api.telegram.org/bot%s/sendDocument" % TG, body,
        {"Content-Type": "multipart/form-data; boundary=" + b})


def get_owner():
    try:
        with open(OWNER_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def set_owner(chat):
    with open(OWNER_FILE, "w") as f:
        f.write(str(chat))
    os.chmod(OWNER_FILE, 0o600)


def gh(path, method=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    return req(API + path, data, GHH, method)


def iso2ts(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def dispatch_run():
    t0 = time.time() - 5
    gh("/repos/%s/actions/workflows/%s/dispatches" % (OWNER_REPO, WF), "POST", {"ref": "main"})
    for _ in range(20):
        d = json.loads(gh("/repos/%s/actions/workflows/%s/runs?event=workflow_dispatch&per_page=10"
                          % (OWNER_REPO, WF)))
        cands = [r for r in d.get("workflow_runs", [])
                 if r.get("head_branch") == "main" and iso2ts(r["created_at"]) >= t0]
        if cands:
            return max(cands, key=lambda r: r["created_at"])
        time.sleep(6)
    raise RuntimeError("ران جدید پیدا نشد (۲ دقیقه)")


def deliver(chat, ip, dns):
    rdp = "\r\n".join([
        "screen mode id:i:2",
        "use multimon:i:0",
        "desktopwidth:i:1920",
        "desktopheight:i:1080",
        "session bpp:i:32",
        "full address:s:" + ip + ":3389",
        "username:s:runneradmin",
        "prompt for credentials:i:0",
        "promptcredentialonce:i:0",
        "authentication level:i:2",
        "negotiate security layer:i:1",
        "enablecredsspsupport:i:1",
        "redirectclipboard:i:1",
        "audiomode:i:0",
        "smart sizing:i:1",
        "bandwidthautodetect:i:1",
        "networkautodetect:i:1",
        "connection type:i:7",
        ""])
    bat = "\r\n".join([
        "@echo off",
        'cmdkey /generic:TERMSRV/%s /user:runneradmin /pass:"%s"' % (ip, RDP),
        'start "" mstsc "%%~dp0win-%s.rdp"' % ip,
        "exit /b",
        ""])
    send(chat, "ویندوز آماده اتصال است.\n"
               "آدرس: %s:3389\n"
               "MagicDNS: %s\n"
               "کاربر: runneradmin\n"
               "پسورد: %s\n\n"
               "اتصال دستی: mstsc → آدرس بالا → کاربر و پسورد بالا\n"
               "اتصال بدون تایپ پسورد: فایل connect-%s.bat را باز کن."
               % (ip, dns or "-", RDP or "(در env تنظیم نشده)", ip))
    send_doc(chat, "win-%s.rdp" % ip, rdp, "فایل Remote Desktop")
    send_doc(chat, "connect-%s.bat" % ip, bat, "اجرا: ذخیره پسورد + باز شدن mstsc")


def watch(rid, chat):
    info_sent = False
    err_sent = False
    while True:
        try:
            if not info_sent:
                got = fetch_info(rid)
                if got:
                    deliver(chat, got[0], got[1])
                    info_sent = True
            r = json.loads(gh("/repos/%s/actions/runs/%s" % (OWNER_REPO, rid)))
            if r["status"] == "completed":
                if info_sent:
                    send(chat, "سرویس پایان یافت (نتیجه: %s)." % r.get("conclusion"))
                else:
                    step = ""
                    try:
                        jobs = json.loads(gh("/repos/%s/actions/runs/%s/jobs" % (OWNER_REPO, rid)))
                        for j in jobs.get("jobs", []):
                            for s in j.get("steps", []) or []:
                                if s.get("conclusion") == "failure":
                                    step = s["name"]
                                    break
                            if step:
                                break
                    except Exception:
                        pass
                    if r.get("conclusion") == "success":
                        send(chat, "ران تمام شد ولی اطلاعات اتصال پیدا نشد.\n%s"
                             % r.get("html_url", ""))
                    else:
                        send(chat, "سرویس با خطا تمام شد.\nمرحله: %s\n%s"
                             % (step or "-", r.get("html_url", "")))
                return
        except Exception as e:
            if not err_sent:
                err_sent = True
                try:
                    send(chat, "خطا در پیگیری ران: %s" % e)
                except Exception:
                    pass
        time.sleep(10)


def new_run(chat):
    try:
        r = dispatch_run()
        send(chat, "ران #%s شروع شد؛ در حال ساخت (۲ تا ۳ دقیقه)..." % r["run_number"])
        threading.Thread(target=watch, args=(r["id"], chat), daemon=True).start()
    except Exception as e:
        send(chat, "خطا در ساخت: %s" % e)


def status(chat):
    d = json.loads(gh("/repos/%s/actions/workflows/%s/runs?per_page=5" % (OWNER_REPO, WF)))
    lines = ["#%s  %s  %s" % (r["run_number"], r["status"], r["html_url"])
             for r in d.get("workflow_runs", [])]
    send(chat, "\n".join(lines) if lines else "رانی پیدا نشد.")


def cancel(chat):
    d = json.loads(gh("/repos/%s/actions/workflows/%s/runs?status=in_progress&per_page=5"
                      % (OWNER_REPO, WF)))
    rs = d.get("workflow_runs", [])
    if not rs:
        send(chat, "ران در حال اجرا نیست.")
        return
    gh("/repos/%s/actions/runs/%s/cancel" % (OWNER_REPO, rs[0]["id"]), "POST", {})
    send(chat, "درخواست توقف ران #%s ثبت شد." % rs[0]["run_number"])


def main():
    print("winbot up", flush=True)
    off = 0
    while True:
        try:
            d = tg("getUpdates", offset=off, timeout=30)
            for u in d.get("result", []):
                off = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = (msg.get("chat") or {}).get("id")
                text = (msg.get("text") or "").strip()
                if not chat:
                    continue
                owner = get_owner()
                if not owner:
                    set_owner(chat)
                    send(chat, "ربات فعال شد. این چت به عنوان مالک ثبت شد.")
                    continue
                if str(chat) != owner:
                    continue
                if text in ("/start", "شروع"):
                    send(chat, "ربات آماده است.")
                elif text == "ساخت ویندوز جدید":
                    threading.Thread(target=new_run, args=(chat,), daemon=True).start()
                elif text == "وضعیت":
                    status(chat)
                elif text == "توقف سرویس":
                    cancel(chat)
        except Exception as e:
            print("poll error:", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
