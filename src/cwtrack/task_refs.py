"""Validation for stable platform assignment references."""


def valid_task_ref(value) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"connection_id", "class_id", "assignment_id"}
    if not required.issubset(value) or set(value) - (required | {"question_id"}):
        return False
    if not all(isinstance(value[key], str) and value[key] for key in required):
        return False
    return value.get("question_id") is None or (
        isinstance(value.get("question_id"), str) and bool(value["question_id"])
    )
