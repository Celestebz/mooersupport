import re


MODEL_PATTERNS = [
    ("GE100 Pro Li", r"\bge\s*100\s*pro\s*li\b|\bge100proli\b"),
    ("GE100 Pro", r"\bge\s*100\s*pro\b|\bge100pro\b"),
    ("GE1000", r"\bge\s*1000\b|\bge1000\b"),
    ("GE300 Lite", r"\bge\s*300\s*lite\b|\bge300lite\b|\bg\s*300\s*lite\b"),
    ("GE300", r"\bge\s*300\b|\bge300\b"),
    ("GE250", r"\bge\s*250\b|\bge250\b"),
    ("GE200 Pro Li", r"\bge\s*200\s*pro\s*li\b|\bge200proli\b"),
    ("GE200", r"\bge\s*200\b|\bge200\b"),
    ("GE150 Pro Li", r"\bge\s*150\s*pro\s*li\b|\bge150proli\b"),
    ("GE150 Pro", r"\bge\s*150\s*pro\b|\bge150pro\b"),
    ("GE150 MAX Li", r"\bge\s*150\s*max\s*li\b|\bge150maxli\b|\bge150_max_v"),
    ("GE150 MAX", r"\bge\s*150\s*max\b|\bge150max\b"),
    ("GE150 Plus", r"\bge\s*150\s*plus\b|\bge150plus\b"),
    ("GE150", r"\bge\s*150\b|\bge150\b"),
    ("GS1000Li", r"\bgs\s*1000\s*li\b|\bgs1000li\b"),
    ("GS1000", r"\bgs\s*1000\b|\bgs1000\b"),
    ("Prime P2", r"\bprime\s*p2\b|\bp2\b"),
    ("Prime P1", r"\bprime\s*p1\b|\bp1\b"),
    ("Prime M2", r"\bprime\s*m2\b|\bm2\b"),
    ("Prime M1", r"\bprime\s*m1\b|\bm1\b"),
    ("Prime S1", r"\bprime\s*s1\b|\bs1\b"),
    ("GWF4", r"\bgwf\s*4\b|\bgwf4\b"),
    ("iAMP", r"\bi\s*amp\b|\biamp\b"),
    ("F15i Li", r"\bf\s*15i\s*li\b|\bf15i\s*li\b"),
    ("F15i", r"\bf\s*15i\b|\bf15i\b"),
    ("F40i", r"\bf\s*40i\b|\bf40i\b"),
    ("SD75", r"\bsd\s*75\b|\bsd75\b"),
    ("SD50A", r"\bsd\s*50a\b|\bsd50a\b"),
    ("Black Truck", r"\bblack\s*truck\b"),
    ("Red Truck", r"\bred\s*truck\b"),
    ("Micro Looper II", r"\bmicro\s*looper\s*(?:ii|2)\b"),
]


QUOTE_SPLIT_PATTERNS = [
    r"\n\s*on .{0,120}wrote:\s*\n",
    r"\n\s*-{2,}\s*original message\s*-{2,}\s*\n",
    r"\n\s*-{2,}\s*forwarded message\s*-{2,}\s*\n",
    r"\n\s*from:\s*.+\n\s*sent:\s*.+\n",
]


def normalize_model(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def current_message_text(subject, body):
    text = body or ""
    for pattern in QUOTE_SPLIT_PATTERNS:
        parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE | re.DOTALL)
        if parts:
            text = parts[0]
    text = re.sub(r"(?m)^\s*>.*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return f"{subject or ''} {text}".strip()


def extract_product_model(subject, body, fallback_model=None):
    current = current_message_text(subject, body).lower()
    full = f"{subject or ''} {body or ''}".lower()
    for model, pattern in MODEL_PATTERNS:
        if re.search(pattern, current, re.IGNORECASE):
            return model
    for model, pattern in MODEL_PATTERNS:
        if re.search(pattern, full, re.IGNORECASE):
            return model
    return fallback_model or ""


def _find_all(pattern, text):
    return sorted(set(m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)))


def _first_snippet(text, patterns, window=170):
    lower = text.lower()
    best = None
    for pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match and (best is None or match.start() < best):
            best = match.start()
    if best is None:
        return text[: min(len(text), 360)].strip()
    start = max(0, best - window)
    end = min(len(text), best + window * 2)
    return text[start:end].strip()


def extract_issue_facts(subject, body, fallback_model=None):
    current = current_message_text(subject, body)
    current_lower = current.lower()
    full_lower = f"{subject or ''} {body or ''}".lower()
    model = extract_product_model(subject, body, fallback_model=fallback_model)

    facts = {
        "product_model": model,
        "issue_fingerprint": "unknown_issue",
        "issue_type": "unknown_issue",
        "actions": [],
        "failure_stage": [],
        "symptoms": [],
        "versions": _find_all(r"\bv?\d+(?:\.\d+){0,3}\b", current),
        "platforms": _find_all(r"\b(?:windows\s*11|windows\s*10|windows|macos|os\s*x|android|ios|usb\s*2\.0|usb\s*3\.0)\b", current),
        "evidence": "",
        "negative_reasons": [],
        "current_text": current,
    }

    firmware_context = any(x in current_lower for x in [
        "firmware update", "firmware upgrade", "update firmware",
        "updating firmware", "upgrade firmware", "latest version",
        "update it", "installing v", "install v", "after upgrade",
        "upgrade to v", "upgraded to v", "after updating",
        "after update", "latest update"
    ]) or (
        any(x in current_lower for x in ["update", "upgrade"])
        and bool(re.search(r"\bv?\d+(?:\.\d+){1,3}\b|\bv\s*\d+\b", current_lower, re.IGNORECASE))
    )
    software_context = any(x in current_lower for x in ["mooer studio", "software", "driver", "editor"])
    progress_failure = bool(re.search(r"\b(?:0|19|100)\s*%", current_lower)) or "progress bar" in current_lower
    update_error = bool(re.search(
        r"\b(?:error|failed|fail|stuck)\b|does\s+not\s+complete|cannot\s+update|can't\s+update",
        current_lower,
    ))
    comp_flash = bool(re.search(
        r"\bcomp(?:\s+button)?\b.{0,50}(?:flash|flashing|blink|blinking)|(?:flash|flashing|blink|blinking).{0,50}\bcomp(?:\s+button)?\b",
        current_lower,
    ))
    freeze_after_update = firmware_context and any(x in current_lower for x in [
        "freeze", "freezes", "frozen", "freezing", "feezing",
        "screen freeze", "constant freeze"
    ])
    old_version_request = any(x in current_lower for x in ["old version", "previous version", "version mismatch", "backup", "back up", "revert to version"])
    ui_window_issue = software_context and bool(re.search(
        r"\bwindow\b|screen\s+(?:size|fit|display)|fit\s+into\s+the\s+screen|resize|display\s+scal|cannot\s+(?:reduce|increase)|can't\s+(?:reduce|increase)",
        current_lower,
    ))
    iamp_family_context = bool(re.search(
        r"\b(?:f15i|f40i|sd10i|sd30i|hornet\s*15i|hornet\s*30i)\b|\bi\s*amp\b|\biamp\b",
        current_lower,
        re.IGNORECASE,
    )) or normalize_model(model) in {"f15i", "f15ili", "f40i", "f40ili", "sd10i", "sd30i", "iamp"}
    app_version_too_low = bool(re.search(
        r"(?:app|application|version).{0,80}(?:too|to)\s+low|"
        r"(?:too|to)\s+low.{0,80}(?:app|application|version)|"
        r"asked\s+me\s+to\s+update|informed\s+me\s+that\s+its\s+version|"
        r"(?:app|application|version|版本).{0,80}(?:过低|太低)|"
        r"(?:过低|太低).{0,80}(?:app|application|version|版本)",
        current_lower,
        re.IGNORECASE,
    ))
    iamp_app_unusable = iamp_family_context and bool(re.search(
        r"(?:用不了|无法使用|不能使用|打不开|不能连接|无法连接|连不上|连接不上|not\s+working|"
        r"doesn['’]?t\s+work|does\s+not\s+work|cannot\s+connect|can['’]?t\s+connect)",
        current_lower,
        re.IGNORECASE,
    ))

    if firmware_context and not (app_version_too_low and iamp_family_context):
        facts["actions"].append("firmware_update")
    if software_context:
        facts["actions"].append("software_or_driver")
    if progress_failure:
        facts["failure_stage"].append("progress_stuck_or_partial")
    if comp_flash:
        facts["symptoms"].append("comp_button_flashing")
    if update_error:
        facts["symptoms"].append("update_error")
    if freeze_after_update:
        facts["symptoms"].append("freeze_after_update")
    if old_version_request:
        facts["symptoms"].append("old_version_or_backup_request")
    if ui_window_issue:
        facts["symptoms"].append("software_window_display_issue")
    if (app_version_too_low or iamp_app_unusable) and iamp_family_context:
        facts["symptoms"].append("app_version_too_low")

    if (app_version_too_low or iamp_app_unusable) and iamp_family_context:
        facts["issue_type"] = "app_version_too_low_connection_failure"
        facts["issue_fingerprint"] = "app_version_too_low_connection_failure"
        if "app_connection" not in facts["actions"]:
            facts["actions"].append("app_connection")
    elif firmware_context and (progress_failure or comp_flash or ("update_error" in facts["symptoms"])):
        facts["issue_type"] = "firmware_update_failed"
        facts["issue_fingerprint"] = "firmware_update_failed_progress_or_error"
    elif freeze_after_update:
        facts["issue_type"] = "firmware_update_failed"
        facts["issue_fingerprint"] = "firmware_update_freeze_after_update"
    elif ui_window_issue:
        facts["issue_type"] = "software_install_driver"
        facts["issue_fingerprint"] = "software_window_display_or_scaling"
    elif old_version_request and software_context:
        facts["issue_type"] = "software_install_driver"
        facts["issue_fingerprint"] = "software_old_version_or_backup_request"
    connection_context = (
        any(x in current_lower for x in ["bluetooth", "usb", "wireless"])
        or bool(re.search(r"\b(?:mooer\s*)?app\b", current_lower))
    ) and any(x in current_lower for x in [
        "connect", "connection", "pair", "paired", "not working",
        "doesn't work", "does not work", "cannot", "can't"
    ])
    if facts["issue_fingerprint"] == "unknown_issue" and connection_context and not firmware_context:
        facts["issue_type"] = "app_usb_bluetooth_connection"
        facts["issue_fingerprint"] = "app_usb_bluetooth_connection"
    audio_context = any(x in current_lower for x in [
        "no sound", "no output", "no main output", "output signal",
        "sound fades", "sound becomes", "audio cuts", "cuts out",
        "distorted", "distortion", "fuzzy", "compressed",
        "hum-noise", "hum noise", "hiss", "noise"
    ])
    if facts["issue_fingerprint"] == "unknown_issue" and audio_context:
        facts["issue_type"] = "audio_output_noise"
        facts["issue_fingerprint"] = "audio_output_noise_or_distortion"

    fallback_norm = normalize_model(fallback_model)
    fact_norm = normalize_model(model)
    if fallback_norm and fact_norm and fallback_norm != fact_norm:
        if not (fallback_norm == "ge300" and fact_norm == "ge300lite"):
            facts["negative_reasons"].append(f"product_mismatch:{fallback_model}->{model}")

    if not model and fallback_model:
        facts["product_model"] = fallback_model

    facts["evidence"] = _first_snippet(
        current,
        [
            r"firmware.{0,80}(?:update|upgrade|version|failed|error)",
            r"(?:stuck|progress|error|failed|freeze|flashing).{0,120}",
            r"(?:version|app|application).{0,120}(?:too|to)\s+low",
            r"(?:mooer studio|driver|software).{0,100}",
            r"(?:noise|distorted|fuzzy|output).{0,100}",
        ],
    )

    if facts["issue_fingerprint"] == "unknown_issue" and any(k in full_lower for k in ["firmware", "update", "ge300", "ge200"]):
        facts["negative_reasons"].append("no_current_message_failure_fact")

    return facts


def score_issue_match(email_row, target_model, issue_title="", keywords=None, category=""):
    keywords = keywords or []
    subject = email_row.get("subject") or ""
    body = email_row.get("body") or ""
    row_model = email_row.get("product_model") or ""
    facts = extract_issue_facts(subject, body, fallback_model=row_model)
    current_lower = facts["current_text"].lower()

    target_norm = normalize_model(target_model)
    fact_norm = normalize_model(facts.get("product_model"))
    product_match = bool(target_norm and fact_norm and (
        target_norm == fact_norm or (target_norm == "ge300" and fact_norm == "ge300lite")
    ))
    if target_norm and not fact_norm:
        return {
            "matched": False,
            "confidence": 0.0,
            "facts": facts,
            "matched_keywords": [],
            "reject_reason": f"Missing product evidence for target {target_model}",
        }
    if target_norm and fact_norm and not product_match:
        return {
            "matched": False,
            "confidence": 0.0,
            "facts": facts,
            "matched_keywords": [],
            "reject_reason": f"Product mismatch: target {target_model}, email {facts.get('product_model')}",
        }

    matched_keywords = []
    for kw in keywords:
        kw_norm = (kw or "").strip().lower()
        if kw_norm and kw_norm in current_lower:
            matched_keywords.append(kw)

    target_text = f"{issue_title} {category} {' '.join(keywords)}".lower()
    target_wants_firmware_failed = any(x in target_text for x in ["firmware", "update", "upgrade"]) and any(
        x in target_text for x in ["failed", "fail", "stuck", "error", "freeze", "firmware_update_failed"]
    )
    target_wants_freeze = "freeze" in target_text or "frozen" in target_text
    target_wants_progress_error = any(x in target_text for x in ["failed", "fail", "stuck", "error", "progress", "firmware_update_failed"])
    target_wants_audio = any(x in target_text for x in ["audio", "sound", "noise", "output", "distorted"])

    fact_fp = facts.get("issue_fingerprint") or ""
    if target_wants_firmware_failed and not fact_fp.startswith("firmware_update"):
        return {
            "matched": False,
            "confidence": 0.2,
            "facts": facts,
            "matched_keywords": matched_keywords,
            "reject_reason": f"Different issue facts: {fact_fp}",
        }
    if target_wants_freeze and fact_fp != "firmware_update_freeze_after_update":
        return {
            "matched": False,
            "confidence": 0.25,
            "facts": facts,
            "matched_keywords": matched_keywords,
            "reject_reason": f"Different firmware issue facts: {fact_fp}",
        }
    if target_wants_progress_error and not target_wants_freeze and fact_fp != "firmware_update_failed_progress_or_error":
        return {
            "matched": False,
            "confidence": 0.25,
            "facts": facts,
            "matched_keywords": matched_keywords,
            "reject_reason": f"Different firmware issue facts: {fact_fp}",
        }
    if target_wants_audio and facts.get("issue_type") != "audio_output_noise":
        return {
            "matched": False,
            "confidence": 0.2,
            "facts": facts,
            "matched_keywords": matched_keywords,
            "reject_reason": f"Different issue facts: {fact_fp}",
        }

    score = 0.35
    if product_match:
        score += 0.25
    if matched_keywords:
        score += min(0.25, 0.08 * len(matched_keywords))
    if fact_fp != "unknown_issue":
        score += 0.15
    if facts.get("negative_reasons"):
        score -= 0.25

    return {
        "matched": score >= 0.55,
        "confidence": max(0.0, min(0.95, score)),
        "facts": facts,
        "matched_keywords": matched_keywords,
        "reject_reason": "",
    }
