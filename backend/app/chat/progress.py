"""User-facing progress and friendly error messages for chat."""

from app.review.labels import load_labels

_PROGRESS_STEPS = {
    "request_understanding": "understanding",
    "planning_generation": "planning",
    "decomposition": "plan_ready",
    "task_retrieval": "searching",
    "task_completed": "step_done",
    "synthesis": "writing",
    "run_failed": "failed",
}
_ENGLISH = {
    "understanding": "Reading and understanding your question?",
    "planning": "Planning the work in small steps?",
    "plan_ready": "Split into {n} steps: {goals}",
    "searching": "Searching documents for step {task_id}?",
    "step_done": "Finished step {task_id}.",
    "writing": "Putting the answer together?",
    "failed": "I couldn?t process this request.",
}
_ERROR_EN = {
    "PLAN_REJECTED": ("I couldn?t split this request into suitable steps.", "Try breaking it into shorter sentences and send it again."),
    "PROVIDER_LIMIT": ("The model is busy or taking too long to respond.", "Wait a moment, then try again."),
    "CONDITION_NOT_AVAILABLE": ("This processing mode is not currently available.", "Choose another mode and try again."),
    "PIPELINE_RUN_FAILED": ("I ran into a problem processing this request.", "Send the request again in a moment."),
    "UNKNOWN": ("An unknown error occurred.", "Try again; if it continues, contact an administrator."),
    "RATE_LIMITED": ("You?re sending messages too quickly.", "Try again in a few seconds."),
    "SOURCE_NOT_FOUND": ("I couldn?t find the selected document.", "Reload the document list and try again."),
    "CONVERSATION_NOT_FOUND": ("I couldn?t find this conversation.", "Return to the list and open the conversation again."),
    "MESSAGE_REQUIRED": ("Your message is empty.", "Enter a message and send it again."),
    "PRODUCT_PROVIDER_NOT_CONFIGURED": ("The response service is not configured.", "Try again later or contact an administrator."),
    "DERIVED_INDEX_UNAVAILABLE": ("The search index is not currently available.", "Try again when the index is ready."),
}

def stage_label(event: dict, language: str = "vi") -> dict | None:
    stage = event.get("stage")
    step = _PROGRESS_STEPS.get(stage)
    if step is None:
        return None
    if language == "en":
        template = _ENGLISH[step]
    else:
        template = load_labels().get("progress", {}).get(step)
        if not template:
            return None
    if stage == "run_failed":
        if language == "en":
            return {"step": step, "text": friendly_error("PIPELINE_RUN_FAILED", language)["message"]}
        return {"step": step, "text": friendly_error("PIPELINE_RUN_FAILED")["message"]}
    if stage == "decomposition":
        tasks = event.get("tasks", [])
        goals = [str(task.get("goal", ""))[:60] for task in tasks]
        text = template.format(n=len(tasks), goals="; ".join(goals))
    elif stage in {"task_retrieval", "task_completed"}:
        result = event.get("result", {})
        text = template.format(task_id=event.get("task_id") or result.get("task_id", ""))
    else:
        text = template
    return {"step": step, "text": text}

def friendly_error(code: str, language: str = "vi") -> dict:
    code = code if code in _ERROR_EN else "UNKNOWN"
    if language == "en":
        message, hint = _ERROR_EN[code]
    else:
        entry = load_labels().get("friendly_errors", {}).get(code, {})
        message, hint = entry.get("message"), entry.get("hint")
        if not message or not hint:
            code = "UNKNOWN"
            entry = load_labels().get("friendly_errors", {}).get(code, {})
            message, hint = entry.get("message", ""), entry.get("hint", "")
    return {"code": code, "message": message, "hint": hint}
