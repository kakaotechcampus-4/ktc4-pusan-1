"""Keep the deployment host out of the HTTP client's own log records.

:mod:`irya_ai.stt.elice` never writes the deployment URL itself, but it does
not own every logger that sees it. ``httpx`` logs one INFO line per request -
``HTTP Request: POST https://<deployment>/v1/audio/transcriptions "HTTP/1.1
200 OK"`` - on success and on failure alike, and ``httpcore`` names the same
host in its DEBUG connection records. Both propagate to the root logger, so
an application running at ``LOG_LEVEL=INFO``, which is the configured
default, prints the private endpoint without any code here asking it to.

The protection is a :class:`logging.Filter` on those two libraries' loggers.
A filter is the extension point :mod:`logging` publishes for this, so no
third-party method is replaced, and it runs on the logger the record came
from, which means it covers handlers the application attached anywhere above
- including the root handler an embedding app usually installs.

What it does is narrow on purpose. A record is rewritten only when its
formatted message actually contains a registered host, and then only that
host is replaced; method, path and status survive, so a request is still
traceable in the log. Records naming any other host - a second
``AsyncClient`` talking to somewhere unrelated, in this process, at the same
time - pass through untouched. Muting the application's whole HTTP logging to
protect one endpoint would cost more than it buys.

Only the host is registered, read from the client's ``base_url``. The default
request logging does not print the request's ``Authorization`` value or body.
However, httpcore DEBUG records can include response headers. This filter
redacts registered hosts, not arbitrary secrets in headers, paths or queries.
"""

import logging
import re
import threading
from urllib.parse import urlsplit

# What a protected host is replaced with. Recognisable in a log, and not a
# value that could be mistaken for a real host somebody might try to reach.
REDACTED_HOST = "<redacted-host>"

# Every logger ``httpx`` and ``httpcore`` write to. A filter only runs on the
# logger that created the record - ancestors contribute handlers, not filters
# - so "httpcore" alone would miss "httpcore.connection". The list is checked
# against the installed packages by ``test_stt_http_logging.py``, which is
# what catches a new logger name on an upgrade.
HTTP_CLIENT_LOGGERS = (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)

_lock = threading.Lock()
_hosts: set[str] = set()
_pattern: re.Pattern[str] | None = None


class _HostRedactingFilter(logging.Filter):
    """Replace registered hosts in a record, and leave every other one alone."""

    def filter(self, record: logging.LogRecord) -> bool:
        pattern = _pattern
        if pattern is None:
            return True

        try:
            message = record.getMessage()
        except Exception:
            # A record this cannot format is one it cannot inspect, and
            # ``logging`` prints the raw msg and args to stderr when its own
            # formatting fails. If the host is anywhere in that raw pair, the
            # record is dropped: there is nothing left to redact in place.
            raw = f"{record.msg!r} {record.args!r}"
            return pattern.search(raw) is None

        redacted = pattern.sub(REDACTED_HOST, message)
        if redacted == message:
            return True

        # The message is replaced already-formatted, so ``args`` has to go
        # with it or ``%`` would run a second time over the redacted text.
        # Handlers that read ``record.args`` structurally see an empty tuple
        # for these records; that only applies to records that named a
        # protected host.
        record.msg = redacted
        record.args = ()
        return True


_FILTER = _HostRedactingFilter()


def protect_host(base_url: object) -> str | None:
    """Hide ``base_url``'s host from the HTTP client loggers.

    Returns the host now protected, or ``None`` when there is no host to
    protect. Idempotent, and safe to call from several threads.

    :class:`irya_ai.stt.elice.EliceSttClient` calls this for the client it is
    given, so both the supported entry path and a caller-supplied
    ``AsyncClient`` are covered without the caller arranging anything. It is
    public so applications can register additional hosts used by httpx/httpcore.
    It does not install protection on another library's or application's logger.
    """

    host = _host_of(base_url)
    if not host:
        # An empty host would compile into a pattern that matches at every
        # position, redacting every HTTP record in the process. A client with
        # no ``base_url`` has nothing to hide here anyway: it is not the one
        # aimed at the deployment.
        return None

    global _pattern
    with _lock:
        if host in _hosts:
            return host
        _hosts.add(host)
        _pattern = re.compile(
            "|".join(re.escape(known) for known in sorted(_hosts)),
            re.IGNORECASE,
        )
        for name in HTTP_CLIENT_LOGGERS:
            # ``addFilter`` is a no-op when the filter is already attached,
            # so repeated clients do not stack copies of it.
            logging.getLogger(name).addFilter(_FILTER)
    return host


def protected_hosts() -> frozenset[str]:
    """The hosts currently hidden, lowercased."""

    with _lock:
        return frozenset(_hosts)


def clear_protected_hosts() -> None:
    """Forget every host and take the filter back off the loggers.

    Leaves the dependency loggers as they were before the first
    :func:`protect_host`. For teardown - a test, or an application shutting a
    deployment binding down - not for narrowing protection while requests are
    still in flight.
    """

    global _pattern
    with _lock:
        _hosts.clear()
        _pattern = None
        for name in HTTP_CLIENT_LOGGERS:
            logging.getLogger(name).removeFilter(_FILTER)


def _host_of(base_url: object) -> str:
    """The host of a URL, an ``httpx.URL``, or a bare host string."""

    host = getattr(base_url, "host", None)
    if host is None:
        text = str(base_url).strip()
        if "//" not in text:
            # ``urlsplit`` reads a schemeless string as a path, so a bare
            # "deployment.example:8000" would come back without a host.
            text = "//" + text
        host = urlsplit(text).hostname or ""
    return str(host).strip().lower()
