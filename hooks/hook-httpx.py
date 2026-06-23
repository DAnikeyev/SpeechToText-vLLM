# PyInstaller hook for httpx.
#
# httpx depends on certifi (lazy-imported inside create_ssl_context),
# httpcore (lazy-imported inside HTTPTransport.__init__), and h11
# (lazy-imported inside httpcore._sync.http11).  PyInstaller's static
# analysis cannot discover these, so we declare them explicitly.

from PyInstaller.utils.hooks import collect_data_files

hiddenimports = [
    "certifi",
    "httpcore",
    "httpcore._sync",
    "httpcore._sync.http11",
    "httpcore._sync.connection",
    "httpcore._sync.connection_pool",
    "httpcore._async",
    "httpcore._async.http11",
    "httpcore._async.connection",
    "httpcore._async.connection_pool",
    "h11",
    "h11._events",
    "h11._state",
    "h11._connection",
]

datas = collect_data_files("certifi")
