"""Server side of the import dashboard (web page "Data import").

* ``admin``: who may act (this computer, or the administrator token).
* ``state``: the job table and a small key/value store for cached checks.
* ``earthdata``: the Earthdata Login on this server and the per-product access check.
* ``nasa``: what NASA's catalogue holds now, per product.
* ``jobs``: the import queue and its single worker (runs ``megavir-ingest`` as a child process).
* ``overview``: what is stored, merged with NASA's side, and the import history.
"""
