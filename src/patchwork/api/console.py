"""Approval console backend (Lambda behind API Gateway HTTP API with a Cognito JWT authorizer).

Routes (all require a signed-in ward engineer; the user name comes from the verified token, never the request):
  GET  /packages                      work packages waiting for a decision, plus recent decisions
  GET  /packages/{id}                 one package: defects, materials, the agent's work order text
  POST /packages/{id}/decision        {"decision": "approve" | "reject", "note": "..."}

Approving resumes the Step Functions approval execution, which files a MOCK ticket. Rejecting stops it and
records an override of the agent's plan. Only boto3 is used, so the Lambda needs no packaged dependencies.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "ap-south-1")
rds = boto3.client("rds-data", region_name=REGION)
sfn = boto3.client("stepfunctions", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)


def _param(k, v):
    if v is None:
        return {"name": k, "value": {"isNull": True}}
    if isinstance(v, bool):
        return {"name": k, "value": {"booleanValue": v}}
    return {"name": k, "value": {"stringValue": str(v)}}


class DatabaseWaking(Exception):
    """Aurora Serverless auto-pauses when idle (min 0 ACU, to save credits); resuming takes ~15-30 s."""


def sql(statement: str, params: dict | None = None, wait_s: float = 24.0) -> list[dict]:
    t0 = time.time()
    while True:
        try:
            r = rds.execute_statement(
                resourceArn=os.environ["DB_CLUSTER_ARN"],
                secretArn=os.environ["DB_SECRET_ARN"],
                database=os.environ.get("DB_NAME", "patchwork_final"),
                sql=statement,
                parameters=[_param(k, v) for k, v in (params or {}).items()],
                formatRecordsAs="JSON",
            )
            return json.loads(r["formattedRecords"]) if r.get("formattedRecords") else []
        except rds.exceptions.DatabaseResumingException:
            if time.time() - t0 > wait_s:  # stay inside API Gateway's 30 s limit; the page retries
                raise DatabaseWaking() from None
            time.sleep(3)


def reply(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def list_packages() -> dict:
    rows = sql(
        "SELECT wp.package_id, wp.priority, wp.total_area_m2, wp.exposure_score, wp.confidence, wp.state, "
        "array_length(wp.defect_ids, 1) AS n_defects, wp.created_at::text AS created_at, "
        "(SELECT d.road_name FROM defect d WHERE d.defect_id = wp.defect_ids[1]) AS road_name, "
        "(ar.package_id IS NOT NULL) AS waiting, a.decision, a.decided_by, a.decided_at::text AS decided_at, "
        "t.ticket_id FROM work_package wp LEFT JOIN approval_request ar USING (package_id) "
        "LEFT JOIN approval a ON a.package_id = wp.package_id LEFT JOIN ticket t ON t.package_id = wp.package_id "
        "WHERE wp.state IN ('awaiting_approval', 'filed', 'rejected', 'verified', 'escalated') "
        "ORDER BY (ar.package_id IS NULL), wp.priority, wp.exposure_score DESC LIMIT 200"
    )
    return reply(200, {"packages": rows})


def get_package(pid: str) -> dict:
    p = sql(
        "SELECT package_id, priority, total_area_m2, exposure_score, confidence, state, material::text AS material, "
        "rationale, pdf_key, array_to_string(defect_ids, ',') AS ids FROM work_package WHERE package_id = :p",
        {"p": pid},
    )
    if not p:
        return reply(404, {"error": "unknown package"})
    p = p[0]
    defects = sql(
        "SELECT d.defect_id, d.road_name, round(d.chainage_m::numeric, 0)::int AS chainage_m, d.latest_area_m2, "
        "d.latest_severity::text AS severity, d.status::text AS status, d.lat, d.lon, o.overlay_key "
        "FROM defect d JOIN observation o ON o.obs_id = d.latest_obs_id "
        "WHERE d.defect_id = ANY(string_to_array(:ids, ',')) ORDER BY d.chainage_m",
        {"ids": p.pop("ids")},
    )
    text = None
    if p.get("pdf_key") and os.environ.get("ARTIFACTS_BUCKET"):
        try:
            text = s3.get_object(Bucket=os.environ["ARTIFACTS_BUCKET"], Key=p["pdf_key"])["Body"].read().decode()
        except s3.exceptions.NoSuchKey:
            text = None
    p["material"] = json.loads(p["material"]) if p.get("material") else None
    waiting = bool(sql("SELECT 1 FROM approval_request WHERE package_id = :p", {"p": pid}))
    return reply(200, {"package": p, "defects": defects, "work_order": text, "waiting": waiting})


def decide(pid: str, body: dict, user: str) -> dict:
    decision = body.get("decision")
    note = str(body.get("note", ""))[:500]
    if decision not in ("approve", "reject"):
        return reply(400, {"error": "decision must be approve or reject"})
    tok = sql("SELECT task_token FROM approval_request WHERE package_id = :p", {"p": pid})
    if not tok:
        return reply(409, {"error": "no pending approval for this package (already decided, or never requested)"})
    payload = json.dumps({"decision": decision, "decided_by": user, "note": note})
    if decision == "approve":
        sfn.send_task_success(taskToken=tok[0]["task_token"], output=payload)
    else:
        sfn.send_task_failure(taskToken=tok[0]["task_token"], error="Rejected", cause=payload)
    sql(
        "INSERT INTO approval (approval_id, package_id, decision, decided_by, note, is_override) "
        "VALUES (:a, :p, :d, :by, :n, CAST(:o AS boolean))",
        {"a": uuid.uuid4().hex, "p": pid, "d": decision, "by": user, "n": note, "o": decision == "reject"},
    )
    sql("DELETE FROM approval_request WHERE package_id = :p", {"p": pid})
    return reply(200, {"package_id": pid, "decision": decision, "decided_by": user})


def handler(event, context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user = claims.get("cognito:username") or claims.get("username") or claims.get("sub")
    if not user:
        return reply(401, {"error": "not signed in"})
    route = event.get("routeKey", "")
    pid = (event.get("pathParameters") or {}).get("id", "")
    try:
        if route == "GET /packages":
            return list_packages()
        if route == "GET /packages/{id}":
            return get_package(pid)
        if route == "POST /packages/{id}/decision":
            return decide(pid, json.loads(event.get("body") or "{}"), f"console:{user}")
    except DatabaseWaking:
        return reply(503, {"error": "database waking up", "retry_after_s": 10})
    except sfn.exceptions.TaskTimedOut:
        return reply(409, {"error": "the approval request expired; ask the assistant to request approval again"})
    return reply(404, {"error": "unknown route"})
