# -*- coding: utf-8 -*-
# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import json
import os
import subprocess
import frappe
import pymysql
import redis
import requests
from rq import Worker
from frappe.model.document import Document
from frappe.utils.background_jobs import get_redis_conn

from bench_manager.bench_manager.utils import (
	normalize_site_config,
	publish_console,
	verify_whitelisted_call,
)
from bench_manager.bench_manager.doctype.bench_settings.bench_settings import (
	sync_backups,
	sync_sites,
	update_site_list,
)


class BenchHealth(Document):
	pass


@frappe.whitelist()
def get_health_snapshot():
	verify_whitelisted_call()
	latest = frappe.get_all(
		"Bench Health Log",
		fields=["name", "creation", "overall_status", "summary_json", "per_site_json"],
		order_by="creation desc",
		limit=1,
	)
	logs = frappe.get_all(
		"Bench Health Log",
		fields=["name", "creation", "overall_status"],
		order_by="creation desc",
		limit=20,
	)
	latest_entry = latest[0] if latest else None
	if latest_entry:
		if latest_entry.get("summary_json"):
			latest_entry["summary"] = json.loads(latest_entry["summary_json"])
		if latest_entry.get("per_site_json"):
			latest_entry["per_site"] = json.loads(latest_entry["per_site_json"])
	return {"latest": latest_entry, "logs": logs}


@frappe.whitelist()
def run_health_checks(key=None):
	verify_whitelisted_call()
	user = getattr(frappe.session, "user", None) or "Administrator"
	try:
		publish_console(key, "Running Bench Health checks...", user=user)
		summary, per_site = _run_checks(key, user)
		_save_health_log(summary, per_site)
		frappe.enqueue(
			"bench_manager.bench_manager.doctype.bench_settings.bench_settings.sync_backups",
			queue="short",
		)
		return {"status": "ok", "summary": summary, "per_site": per_site}
	except Exception:
		frappe.log_error(title="Bench Health Failed", message=frappe.get_traceback())
		publish_console(key, "ERROR: Bench Health checks failed.", user=user)
		raise


@frappe.whitelist()
def repair_site(site_name, key=None):
	verify_whitelisted_call()
	user = getattr(frappe.session, "user", None) or "Administrator"
	try:
		publish_console(key, "Repairing site {0}".format(site_name), user=user)
		normalize_site_config(site_name)
		sync_sites()
		sync_backups()
		site = frappe.get_doc("Site", site_name)
		site.update_app_list()
		site.save()
		frappe.db.commit()
		return {"status": "ok"}
	except Exception:
		frappe.log_error(
			title="Bench Health Repair Site Failed",
			message=frappe.get_traceback(),
		)
		publish_console(key, "ERROR: Repair failed for {0}".format(site_name), user=user)
		raise


@frappe.whitelist()
def repair_all(key=None):
	verify_whitelisted_call()
	user = getattr(frappe.session, "user", None) or "Administrator"
	try:
		publish_console(key, "Repairing all sites", user=user)
		for site_name in update_site_list():
			normalize_site_config(site_name)
		sync_sites()
		sync_backups()
		return {"status": "ok"}
	except Exception:
		frappe.log_error(
			title="Bench Health Repair All Failed",
			message=frappe.get_traceback(),
		)
		publish_console(key, "ERROR: Repair all failed", user=user)
		raise


def _run_checks(key, user):
	common_config = _read_common_site_config()
	summary = {
		"redis": _check_redis(common_config),
		"rq": _check_rq_workers(),
		"socketio": _check_socketio(common_config),
		"bench": _check_bench_commands(),
		"mariadb": _check_mariadb(common_config),
	}
	per_site = _check_sites(key, user)
	overall = all(item.get("ok") for item in summary.values()) and all(
		item.get("ok") for item in per_site.values()
	)
	summary["overall_status"] = "Pass" if overall else "Fail"
	return summary, per_site


def _read_common_site_config():
	bench_path = frappe.utils.get_bench_path()
	common_path = os.path.join(bench_path, "sites", "common_site_config.json")
	if not os.path.exists(common_path):
		return {}
	with open(common_path, "r") as handle:
		return json.load(handle)


def _check_redis(common_config):
	results = {}
	for key, label in [
		("redis_cache", "cache"),
		("redis_queue", "queue"),
		("redis_socketio", "socketio"),
	]:
		url = common_config.get(key)
		if not url:
			results[label] = {"ok": False, "message": "Missing {0} URL".format(key)}
			continue
		try:
			client = redis.from_url(url)
			client.ping()
			results[label] = {"ok": True, "message": "OK"}
		except Exception:
			frappe.log_error(
				title="Bench Health Redis Failed",
				message=frappe.get_traceback(),
			)
			results[label] = {"ok": False, "message": "Unreachable"}
	return {"ok": all(item["ok"] for item in results.values()), "details": results}


def _check_rq_workers():
	try:
		connection = get_redis_conn()
		workers = Worker.all(connection=connection)
		queues = {queue_name: False for queue_name in ["short", "long"]}
		for worker in workers:
			for queue in worker.queue_names():
				if queue in queues:
					queues[queue] = True
		return {"ok": all(queues.values()), "details": queues}
	except Exception:
		frappe.log_error(
			title="Bench Health RQ Failed",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "details": {}}


def _check_socketio(common_config):
	port = common_config.get("socketio_port") or frappe.conf.get("socketio_port") or 9000
	url = "http://127.0.0.1:{0}/socket.io/?EIO=3&transport=polling".format(port)
	try:
		response = requests.get(url, timeout=5)
		return {"ok": response.status_code == 200, "message": response.status_code}
	except Exception:
		frappe.log_error(
			title="Bench Health SocketIO Failed",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "message": "Unreachable"}


def _check_bench_commands():
	try:
		result = subprocess.run(
			["bench", "--version"], capture_output=True, text=True, check=True
		)
		return {"ok": True, "message": result.stdout.strip()}
	except Exception:
		frappe.log_error(
			title="Bench Health Bench Command Failed",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "message": "bench not available"}


def _check_mariadb(common_config):
	host = common_config.get("db_host") or frappe.conf.get("db_host") or "127.0.0.1"
	port = int(common_config.get("db_port") or frappe.conf.get("db_port") or 3306)
	password = common_config.get("root_password")
	if not password:
		return {"ok": False, "message": "Missing root_password in common_site_config.json"}
	try:
		connection = pymysql.connect(
			host=host, port=port, user="root", passwd=password, connect_timeout=5
		)
		connection.close()
		return {"ok": True, "message": "Connected"}
	except Exception:
		frappe.log_error(
			title="Bench Health MariaDB Failed",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "message": "Unable to connect"}


def _check_sites(key, user):
	bench_path = frappe.utils.get_bench_path()
	per_site = {}
	for site_name in update_site_list():
		site_result = {"ok": True, "details": {}}
		site_path = os.path.join(bench_path, "sites", site_name)
		if not os.path.isdir(site_path):
			site_result["ok"] = False
			site_result["details"]["exists"] = False
			per_site[site_name] = site_result
			continue

		site_result["details"]["exists"] = True
		site_config_path = os.path.join(site_path, "site_config.json")
		try:
			with open(site_config_path, "r") as handle:
				site_config = json.load(handle)
			site_result["details"]["site_config"] = True
		except Exception:
			site_result["ok"] = False
			site_result["details"]["site_config"] = False
			per_site[site_name] = site_result
			continue

		required_fields = [
			"db_name",
			"db_user",
			"db_password",
			"db_host",
			"db_port",
			"db_type",
		]
		missing_fields = [field for field in required_fields if not site_config.get(field)]
		if missing_fields:
			site_result["ok"] = False
			site_result["details"]["missing_fields"] = missing_fields

		site_result["details"]["list_apps"] = _run_bench_site_command(
			site_name, ["list-apps"]
		)

		if site_result["details"]["list_apps"]["ok"]:
			site_result["details"]["console_check"] = _run_bench_site_command(
				site_name,
				["console", "-c", "import frappe; print('ok')"],
			)

		backup_path = os.path.join(site_path, "private", "backups")
		has_backup = False
		if os.path.isdir(backup_path):
			for filename in os.listdir(backup_path):
				if filename.endswith("-database.sql") or filename.endswith("-database.sql.gz"):
					has_backup = True
					break
		site_result["details"]["has_backup"] = has_backup
		if not has_backup:
			site_result["ok"] = False

		per_site[site_name] = site_result
		publish_console(key, "Checked site {0}".format(site_name), user=user)
	return per_site


def _run_bench_site_command(site_name, args):
	bench_path = frappe.utils.get_bench_path()
	command = ["bench", "--site", site_name] + args
	try:
		result = subprocess.run(
			command,
			cwd=bench_path,
			capture_output=True,
			text=True,
			timeout=30,
		)
		ok = result.returncode == 0
		return {"ok": ok, "output": result.stdout.strip() or result.stderr.strip()}
	except Exception:
		frappe.log_error(
			title="Bench Health Site Command Failed",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "output": "Command failed"}


def _save_health_log(summary, per_site):
	doc = frappe.get_doc(
		{
			"doctype": "Bench Health Log",
			"overall_status": summary.get("overall_status"),
			"summary_json": json.dumps(summary, indent=2, sort_keys=True),
			"per_site_json": json.dumps(per_site, indent=2, sort_keys=True),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
