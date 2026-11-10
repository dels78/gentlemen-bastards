#!/usr/bin/env python3
"""Validate protocol schemas and example artifacts (stdlib only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCHEMA_DIR = ROOT / "schemas"
EXAMPLE_DIR = ROOT / "examples"

ENVELOPE_FIELDS = ("id", "type", "version", "created_at", "producer", "refs", "payload")

TYPE_CONSTANTS = {
    "snapshot": "snapshot",
    "plan": "plan",
    "question": "question",
    "receipt": "receipt",
    "report": "report",
    "consult-request": "consult-request",
    "consult-response": "consult-response",
    "brain-proposal": "brain-proposal",
    "decision": "decision",
}

EXAMPLE_TO_TYPE = {
    "snapshot.json": "snapshot",
    "plan.json": "plan",
    "question.json": "question",
    "receipt.json": "receipt",
    "report.json": "report",
    "consult-request.json": "consult-request",
    "consult-response.json": "consult-response",
    "brain-proposal.json": "brain-proposal",
    "question-brain-approval.json": "question",
    "decision.json": "decision",
    "receipt-brain-apply.json": "receipt",
}

INVALID_EXAMPLES = {
    "brain-proposal.invalid.json": "brain-proposal",
    "decision.invalid.json": "decision",
}


def ok(name: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    line = f"{status}: {name}"
    if detail and not passed:
        line += f" — {detail}"
    print(line)
    return passed


def is_str(v: Any) -> bool:
    return isinstance(v, str)


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def is_arr(v: Any) -> bool:
    return isinstance(v, list)


def check_envelope(doc: dict[str, Any], expected_type: str) -> tuple[bool, str]:
    for key in ENVELOPE_FIELDS:
        if key not in doc:
            return False, f"missing envelope field {key!r}"
    extra = set(doc.keys()) - set(ENVELOPE_FIELDS)
    if extra:
        return False, f"unexpected top-level keys: {sorted(extra)}"
    if not is_str(doc["id"]):
        return False, "id must be string"
    if doc["type"] != expected_type:
        return False, f"type must be {expected_type!r}, got {doc['type']!r}"
    if doc["type"] != TYPE_CONSTANTS.get(expected_type):
        return False, "type constant mismatch"
    if doc["version"] != 1:
        return False, "version must be 1"
    if not is_str(doc["created_at"]):
        return False, "created_at must be string"
    if not is_str(doc["producer"]):
        return False, "producer must be string"
    if not is_obj(doc["refs"]):
        return False, "refs must be object"
    if not is_obj(doc["payload"]):
        return False, "payload must be object"
    return True, ""


def check_refs_and_payload(doc: dict[str, Any], artifact_type: str) -> tuple[bool, str]:
    refs = doc["refs"]
    payload = doc["payload"]

    if artifact_type == "snapshot":
        if "window" not in payload or "items" not in payload:
            return False, "snapshot payload missing window or items"
        window = payload["window"]
        if not is_obj(window) or not is_str(window.get("from")) or not is_str(window.get("to")):
            return False, "snapshot window invalid"
        if not is_arr(payload["items"]):
            return False, "snapshot items must be array"
        for i, item in enumerate(payload["items"]):
            if not is_obj(item):
                return False, f"snapshot items[{i}] not object"
            for req in ("kind", "ref", "summary"):
                if req not in item:
                    return False, f"snapshot items[{i}] missing {req}"
            if item["kind"] not in ("email", "linear_issue", "calendar_event"):
                return False, f"snapshot items[{i}] invalid kind"
            if not is_str(item["ref"]) or not is_str(item["summary"]):
                return False, f"snapshot items[{i}] ref/summary must be strings"
        return True, ""

    if artifact_type == "plan":
        if not is_str(refs.get("snapshot_id")):
            return False, "plan refs.snapshot_id required string"
        if "writes" not in payload or "questions" not in payload:
            return False, "plan payload missing writes or questions"
        if not is_arr(payload["writes"]) or not is_arr(payload["questions"]):
            return False, "plan writes/questions must be arrays"
        for i, w in enumerate(payload["writes"]):
            if not is_obj(w):
                return False, f"plan writes[{i}] not object"
            for req in ("system", "action", "object_ref", "description"):
                if req not in w or not is_str(w[req]):
                    return False, f"plan writes[{i}] missing or invalid {req}"
        for i, q in enumerate(payload["questions"]):
            if not is_str(q):
                return False, f"plan questions[{i}] must be string"
        return True, ""

    if artifact_type == "question":
        if not is_str(refs.get("artifact_id")) or not is_str(refs.get("item_ref")):
            return False, "question refs artifact_id and item_ref required strings"
        if "text" not in payload or "blocking" not in payload:
            return False, "question payload missing text or blocking"
        if not is_str(payload["text"]) or not is_bool(payload["blocking"]):
            return False, "question text/blocking types invalid"
        return True, ""

    if artifact_type == "receipt":
        if is_str(refs.get("plan_id")):
            # Plan receipt variant (Writer) — original behavior.
            if "results" not in payload or not is_arr(payload["results"]):
                return False, "receipt payload.results must be array"
            for i, r in enumerate(payload["results"]):
                if not is_obj(r):
                    return False, f"receipt results[{i}] not object"
                for req in ("object_ref", "status", "readback"):
                    if req not in r:
                        return False, f"receipt results[{i}] missing {req}"
                if not is_str(r["object_ref"]) or not is_str(r["readback"]):
                    return False, f"receipt results[{i}] object_ref/readback must be strings"
                if r["status"] not in ("applied", "failed", "skipped"):
                    return False, f"receipt results[{i}] invalid status"
            return True, ""

        # Brain-apply receipt variant (Librarian, gated apply — GB-728J D3).
        if doc["producer"] != "librarian":
            return False, "brain-apply receipt producer must be librarian"
        extra_refs = set(refs.keys()) - {"decision_id", "question_id", "proposal_id"}
        if extra_refs:
            return False, f"brain-apply receipt unexpected refs: {sorted(extra_refs)}"
        for req in ("decision_id", "question_id", "proposal_id"):
            if not is_str(refs.get(req)):
                return False, f"brain-apply receipt refs.{req} required string"
        for req in ("pr_url", "branch", "base_sha", "head_sha"):
            if not is_str(payload.get(req)):
                return False, f"brain-apply receipt payload.{req} required string"
        if "results" not in payload or not is_arr(payload["results"]):
            return False, "brain-apply receipt payload.results must be array"
        if len(payload["results"]) != 1:
            return False, "brain-apply receipt results must have exactly one entry"
        r = payload["results"][0]
        if not is_obj(r):
            return False, "brain-apply receipt results[0] not object"
        for req in ("object_ref", "status", "readback"):
            if req not in r:
                return False, f"brain-apply receipt results[0] missing {req}"
        if not is_str(r["object_ref"]) or not is_str(r["readback"]):
            return False, "brain-apply receipt results[0] object_ref/readback must be strings"
        if r["status"] != "pr_opened":
            return False, "brain-apply receipt results[0] status must be pr_opened"
        if r["readback"] != payload["pr_url"]:
            return False, "brain-apply receipt results[0] readback must equal payload.pr_url"
        return True, ""

    if artifact_type == "report":
        if "period" not in payload or "highlights" not in payload:
            return False, "report payload missing period or highlights"
        period = payload["period"]
        if not is_obj(period) or not is_str(period.get("from")) or not is_str(period.get("to")):
            return False, "report period invalid"
        if not is_arr(payload["highlights"]):
            return False, "report highlights must be array"
        for i, h in enumerate(payload["highlights"]):
            if not is_str(h):
                return False, f"report highlights[{i}] must be string"
        return True, ""

    if artifact_type == "consult-request":
        if not is_str(refs.get("artifact_id")) or not is_str(refs.get("item_ref")):
            return False, "consult-request refs artifact_id and item_ref required strings"
        if "question" not in payload or "responder" not in payload:
            return False, "consult-request payload missing question or responder"
        if not is_str(payload["question"]) or not is_str(payload["responder"]):
            return False, "consult-request question/responder must be strings"
        return True, ""

    if artifact_type == "consult-response":
        if not is_str(refs.get("request_id")):
            return False, "consult-response refs.request_id required string"
        if "outcome" not in payload or "answer" not in payload:
            return False, "consult-response payload missing outcome or answer"
        if payload["outcome"] not in ("answered", "escalated", "abort"):
            return False, "consult-response invalid outcome"
        if not is_str(payload["answer"]):
            return False, "consult-response answer must be string"
        return True, ""

    if artifact_type == "brain-proposal":
        for req in (
            "proposer",
            "target",
            "change_kind",
            "rationale",
            "proposal",
            "evidence_refs",
        ):
            if req not in payload:
                return False, f"brain-proposal payload missing {req}"
        if not is_str(payload["proposer"]):
            return False, "brain-proposal proposer must be string"
        target = payload["target"]
        if target is not None and not is_str(target):
            return False, "brain-proposal target must be string or null"
        if payload["change_kind"] not in ("create", "amend", "supersede", "archive"):
            return False, "brain-proposal invalid change_kind"
        if not is_str(payload["rationale"]) or not payload["rationale"].strip():
            return False, "brain-proposal rationale must be non-empty string"
        if not is_obj(payload["proposal"]):
            return False, "brain-proposal proposal must be object"
        if not is_arr(payload["evidence_refs"]):
            return False, "brain-proposal evidence_refs must be array"
        if not payload["evidence_refs"]:
            return False, "brain-proposal evidence_refs must be non-empty"
        for i, ref in enumerate(payload["evidence_refs"]):
            if not is_str(ref) or not ref.strip():
                return False, f"brain-proposal evidence_refs[{i}] must be non-empty string"
        return True, ""

    if artifact_type == "decision":
        if doc["producer"] != "coordinator":
            return False, "decision producer must be coordinator"
        if refs:
            return False, "decision refs must be the empty object"
        allowed = {"decision", "subject_ref", "proposal_ref", "decided_by", "rationale"}
        extra = set(payload.keys()) - allowed
        if extra:
            return False, f"decision payload unexpected fields: {sorted(extra)}"
        if payload.get("decision") not in ("approved", "rejected"):
            return False, "decision payload.decision must be approved or rejected"
        for req in ("subject_ref", "proposal_ref"):
            if not is_str(payload.get(req)) or not payload[req].strip():
                return False, f"decision payload.{req} required non-empty string"
        if payload.get("decided_by") != "martin":
            return False, "decision payload.decided_by must be martin"
        if "rationale" in payload and (
            not is_str(payload["rationale"]) or not payload["rationale"].strip()
        ):
            return False, "decision payload.rationale must be non-empty string when present"
        return True, ""

    return False, f"unknown artifact type {artifact_type!r}"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    all_pass = True

    schema_files = sorted(SCHEMA_DIR.glob("*.json"))
    if not schema_files:
        all_pass = ok("schemas directory non-empty", False, "no schema files")
        print("FAIL: aborting")
        return 1

    for path in schema_files:
        try:
            data = load_json(path)
            passed = is_obj(data) and "$schema" in data
            all_pass = ok(f"parse schema {path.name}", passed) and all_pass
        except json.JSONDecodeError as e:
            all_pass = ok(f"parse schema {path.name}", False, str(e)) and all_pass

    examples: dict[str, dict[str, Any]] = {}
    examples_by_file: dict[str, dict[str, Any]] = {}
    for filename, artifact_type in sorted(EXAMPLE_TO_TYPE.items()):
        path = EXAMPLE_DIR / filename
        try:
            doc = load_json(path)
            examples[artifact_type] = doc
            examples_by_file[filename] = doc
            all_pass = ok(f"parse example {filename}", is_obj(doc)) and all_pass
        except (json.JSONDecodeError, OSError) as e:
            all_pass = ok(f"parse example {filename}", False, str(e)) and all_pass
            continue

        env_ok, env_detail = check_envelope(doc, artifact_type)
        all_pass = ok(f"envelope {filename}", env_ok, env_detail) and all_pass

        body_ok, body_detail = check_refs_and_payload(doc, artifact_type)
        all_pass = ok(f"refs/payload {filename}", body_ok, body_detail) and all_pass

    # Lineage across examples
    if "plan" in examples and "snapshot" in examples:
        match = examples["plan"]["refs"].get("snapshot_id") == examples["snapshot"]["id"]
        all_pass = ok(
            "lineage plan.snapshot_id == snapshot.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

    if "receipt" in examples and "plan" in examples:
        match = examples["receipt"]["refs"].get("plan_id") == examples["plan"]["id"]
        all_pass = ok(
            "lineage receipt.plan_id == plan.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

    if "question" in examples and "snapshot" in examples:
        q = examples["question"]["refs"]
        match = q.get("artifact_id") == examples["snapshot"]["id"]
        all_pass = ok(
            "lineage question.artifact_id == snapshot.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

    if "consult-response" in examples and "consult-request" in examples:
        match = (
            examples["consult-response"]["refs"].get("request_id")
            == examples["consult-request"]["id"]
        )
        all_pass = ok(
            "lineage consult-response.request_id == consult-request.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

    # GB-728J chain: decision -> question (Librarian) -> brain-proposal
    decision_doc = examples.get("decision")
    approval_q = examples_by_file.get("question-brain-approval.json")
    proposal_doc = examples.get("brain-proposal")
    if decision_doc and approval_q and proposal_doc:
        match = decision_doc["payload"].get("subject_ref") == approval_q["id"]
        all_pass = ok(
            "lineage decision.subject_ref == question-brain-approval.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

        match = decision_doc["payload"].get("proposal_ref") == proposal_doc["id"]
        all_pass = ok(
            "lineage decision.proposal_ref == brain-proposal.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

        match = approval_q["refs"].get("artifact_id") == proposal_doc["id"]
        all_pass = ok(
            "lineage question-brain-approval.artifact_id == brain-proposal.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

        match = approval_q.get("producer") == "librarian"
        all_pass = ok(
            "question-brain-approval producer is librarian",
            match,
            "" if match else "producer differs",
        ) and all_pass

    # GB-728J chain: brain-apply receipt -> decision/question/brain-proposal
    ba_receipt = examples_by_file.get("receipt-brain-apply.json")
    if ba_receipt and decision_doc and approval_q and proposal_doc:
        refs = ba_receipt["refs"]
        match = refs.get("decision_id") == decision_doc["id"]
        all_pass = ok(
            "lineage receipt-brain-apply.decision_id == decision.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

        match = refs.get("question_id") == approval_q["id"]
        all_pass = ok(
            "lineage receipt-brain-apply.question_id == question-brain-approval.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

        match = refs.get("proposal_id") == proposal_doc["id"]
        all_pass = ok(
            "lineage receipt-brain-apply.proposal_id == brain-proposal.id",
            match,
            "" if match else "ids differ",
        ) and all_pass

    for filename, artifact_type in sorted(INVALID_EXAMPLES.items()):
        path = EXAMPLE_DIR / filename
        try:
            doc = load_json(path)
            all_pass = ok(f"parse invalid example {filename}", is_obj(doc)) and all_pass
        except (json.JSONDecodeError, OSError) as e:
            all_pass = ok(f"parse invalid example {filename}", False, str(e)) and all_pass
            continue

        env_ok, env_detail = check_envelope(doc, artifact_type)
        body_ok, body_detail = check_refs_and_payload(doc, artifact_type)
        should_fail = not (env_ok and body_ok)
        detail = ""
        if not should_fail:
            detail = "expected validation failure but example passed"
        elif env_ok and not body_ok:
            detail = body_detail
        elif not env_ok:
            detail = env_detail
        all_pass = ok(f"invalid example {filename} rejected", should_fail, detail) and all_pass

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
