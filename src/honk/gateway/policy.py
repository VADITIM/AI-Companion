"""Which addresses the gateway may open: public http(s) only. No private ranges, no localhost, no metadata endpoints."""
import ipaddress
import re
import socket
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; HonkResearchBot/0.2; local personal prototype)"
BAD_EXT = re.compile(r"\.(exe|msi|dmg|pkg|apk|bat|cmd|sh|ps1|jar|scr|deb|rpm|iso|zip|7z|rar|tar|gz|bin)(\?|$)", re.I)


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http and https addresses can be opened")
    if parts.username or parts.password:
        raise ValueError("no logins")
    if BAD_EXT.search(parts.path):
        raise ValueError("no downloads")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None)
    except socket.gaierror:
        raise ValueError(f"cannot find the host {parts.hostname}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise ValueError("only public internet addresses can be opened")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirect)


def http_get(url, max_bytes, timeout):
    """GET only. Returns (final url, content type, text)."""
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with _OPENER.open(req, timeout=timeout) as r:
        body = r.read(max_bytes)
        return r.geturl(), r.headers.get("Content-Type", ""), body.decode(r.headers.get_content_charset() or "utf-8", "replace")
