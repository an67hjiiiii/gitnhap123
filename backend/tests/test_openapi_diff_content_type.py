from app.review.tools.openapi_diff import diff


def document(media_types):
    content = {media_type: {"schema": {"type": "string"}} for media_type in media_types}
    return {
        "openapi": "3.0.3",
        "info": {"title": "Example", "version": "1"},
        "paths": {
            "/items": {
                "post": {
                    "requestBody": {"content": content},
                    "responses": {"204": {"description": "ok"}},
                }
            }
        },
    }


def media_change(old_types, new_types):
    changes = diff(document(old_types), document(new_types)).changes
    return [change for change in changes if change.kind == "REQUEST_BODY_CONTENT_TYPE_CHANGED"]


def test_reports_added_media_types_sorted_as_non_breaking():
    changes = media_change(["application/json"], ["application/json", "text/plain", "application/xml"])

    assert len(changes) == 1
    assert changes[0].severity == "NON_BREAKING"
    assert changes[0].detail == "Request body media types added: application/xml, text/plain"


def test_reports_removed_media_types_sorted_as_breaking():
    changes = media_change(["application/xml", "text/plain"], ["text/plain"])

    assert len(changes) == 1
    assert changes[0].severity == "BREAKING"
    assert changes[0].detail == "Request body media types removed: application/xml"


def test_reports_added_and_removed_types_together_in_sorted_order():
    changes = media_change(["application/json", "text/plain"], ["application/xml", "text/plain"])

    assert len(changes) == 1
    assert changes[0].detail == "Request body media types added: application/xml; removed: application/json"


def test_same_media_types_produce_no_content_type_change():
    assert media_change(["text/plain", "application/json"], ["application/json", "text/plain"]) == []


def test_diff_order_is_deterministic():
    old = document(["application/json", "text/plain"])
    new_a = document(["application/xml", "text/plain"])
    new_b = document(["text/plain", "application/xml"])

    assert diff(old, new_a).model_dump(mode="json") == diff(old, new_b).model_dump(mode="json")
