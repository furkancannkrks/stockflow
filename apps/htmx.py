def is_htmx_request(request) -> bool:
    """Return whether the request was issued by HTMX."""
    return request.headers.get("HX-Request", "").lower() == "true"
