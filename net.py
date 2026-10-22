"""A GET that survives a flaky library server.

These library sites are small, and they occasionally take longer than usual to
accept a connection. That shows up as a connect timeout, and one retry a few
seconds later almost always succeeds - so every request to a library goes through
here rather than straight to `requests`.

The timeout is deliberately a pair: how long to wait for the *connection*, and how
long to wait for data once connected. A single number applies to both, which means
a slow-but-working server gets cut off just as readily as a dead one.
"""
import time

import requests

# Long enough for a slow server to answer, short enough that a dead one fails fast.
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 90
RETRIES = 3


def get(url, *, retries=RETRIES, backoff=2.0, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), **kw):
    """GET with retries on connection failures and timeouts.

    A retry only happens for a *transport* failure - if the server answers, even
    with an error status, that answer is returned as-is and the caller decides.
    """
    last = None
    for attempt in range(retries):
        try:
            return requests.get(url, timeout=timeout, **kw)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last


def friendly(e, library):
    """Turn a transport failure into something worth showing a reader."""
    name = str(e)
    if isinstance(e, requests.Timeout) or "timed out" in name or "Timeout" in name:
        return (f"{library} ప్రస్తుతం స్పందించడం లేదు (సమయం మించిపోయింది). "
                f"సైట్ నెమ్మదిగా ఉండవచ్చు — కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి.\n"
                f"[{library} did not respond in time. The site may be slow or briefly "
                f"unreachable; please try again in a moment.]")
    if isinstance(e, requests.ConnectionError) or "Connection" in name:
        return (f"{library} కు కనెక్షన్ కుదరలేదు. మీ ఇంటర్నెట్ లేదా ఆ సైట్ "
                f"తాత్కాలికంగా అందుబాటులో లేకపోవచ్చు.\n"
                f"[Could not connect to {library}. Your connection or the site may be "
                f"briefly unavailable.]")
    return name
