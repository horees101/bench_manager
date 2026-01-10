# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappé and contributors
# For license information, please see license.txt


import json
import os
import random
import re
import shlex
import time
from subprocess import PIPE, STDOUT, Popen, CalledProcessError, run
import frappe
import pymysql
from frappe.model.document import Document


class CommandFailed(Exception):
	def __init__(self, command, console_dump):
		super().__init__("Command failed: {command}".format(command=command))
		self.command = command
		self.console_dump = console_dump


def execute_bench_command(command, command_doc, cwd="..", user=None, console_dump=""):
	if isinstance(command, str):
		command = shlex.split(command)
	terminal = Popen(
		command,
		stdin=PIPE,
		stdout=PIPE,
		stderr=STDOUT,
		cwd=cwd,
		text=True,
		bufsize=1,
	)
	for line in iter(terminal.stdout.readline, ""):
		if line == "":
			break
		line = line.rstrip("\n")
		publish_console(command_doc.name, line, user=user)
		console_dump += line + "\n"

	if terminal.wait():
		raise CommandFailed(" ".join(command), console_dump)
	return console_dump


def run_command(
	commands,
	doctype,
	key,
	cwd="..",
	docname=" ",
	after_command=None,
	retry_context=None,
):
	verify_whitelisted_call()
	if not commands:
		publish_console(key, "ERROR: No commands provided for execution.")
		frappe.log_error(
			title="Bench Manager Command Failed",
			message="No commands provided for execution.",
		)
		frappe.throw("No commands provided for execution.")
	original_docname = docname
	docname = docname or doctype
	user = getattr(frappe.session, "user", None) or "Administrator"
	start_time = frappe.utils.time.time()
	console_dump = ""
	logged_command = " && ".join(commands)
	logged_command += (
		" "  # to make sure passwords at the end of the commands are also hidden
	)
	sensitive_data = [
		"--mariadb-root-password",
		"--admin-password",
		"--root-password",
		"--db-password",
	]
	for password in sensitive_data:
		logged_command = re.sub(
			"{password} .*? ".format(password=password), "", logged_command, flags=re.DOTALL
		)
	command_doc = frappe.get_doc(
		{
			"doctype": "Bench Manager Command",
			"key": key,
			"source": doctype + ": " + docname,
			"command": logged_command,
			"console": console_dump,
			"status": "Pending",
		}
	)
	command_doc.insert()
	frappe.db.commit()
	command_doc.db_set("status", "Running", update_modified=False)
	publish_console(
		key,
		"Executing Command:\n{logged_command}".format(logged_command=logged_command),
		user=user,
	)
	publish_console(key, "START", user=user)
	publish_progress(key, percent=5, stage="start", user=user)
	command_status = "Success"
	try:
		if doctype == "Site" and original_docname and original_docname.strip():
			normalize_site_config(original_docname)
		progress_context = (retry_context or {}).get("progress_context")
		for command in commands:
			if _is_reinstall_command(command) or _is_new_site_command(command):
				preflight_site_operation(_get_site_name_from_command(command), key, command)
			if _is_backup_command(command):
				publish_progress(key, percent=40, stage="database", user=user)
			if _is_restore_command(command):
				_publish_restore_stages(key, user=user)
			if _is_new_site_command(command):
				console_dump = _run_new_site_with_retry(
					command,
					command_doc,
					cwd,
					console_dump,
					user=user,
					retry_context=retry_context or {},
				)
				continue

			if progress_context == "new_site":
				if "install-app erpnext" in command:
					publish_progress(key, percent=70, stage="install", user=user)
				elif " migrate" in command:
					publish_progress(key, percent=100, stage="migrate", user=user)
			if progress_context == "restore" and " migrate" in command:
				publish_progress(key, percent=95, stage="migrate", user=user)
				publish_console(key, "Restore stage: migrate", user=user)

			console_dump = _run_command_with_lock_retry(
				command, command_doc, cwd, console_dump, user=user
			)
			if _is_backup_command(command):
				publish_progress(key, percent=70, stage="files", user=user)
				publish_progress(key, percent=90, stage="sync", user=user)

		if progress_context == "new_site":
			publish_progress(key, percent=100, stage="migrate", user=user)

		_close_the_doc(start_time, key, console_dump, status="Success", user=user)
	except Exception as e:
		command_status = "Failed"
		frappe.log_error(
			title="Bench Manager Command Failed",
			message=frappe.get_traceback(),
		)
		publish_console(key, "ERROR: {0}".format(e), user=user)
		publish_console(key, frappe.get_traceback(), user=user)
		if isinstance(e, CommandFailed):
			console_dump = e.console_dump
		_close_the_doc(
			start_time,
			key,
			"{} \n\n{}".format(e, console_dump),
			status="Failed",
			user=user,
		)
	finally:
		try:
			publish_progress(
				key,
				percent=100,
				stage="complete" if command_status == "Success" else "failed",
				user=user,
			)
		except Exception:
			pass
		frappe.db.commit()
		# hack: frappe.db.commit() to make sure the log created is robust,
		# and the _refresh throws an error if the doc is deleted
		frappe.enqueue(
			"bench_manager.bench_manager.utils._refresh",
			doctype=doctype,
			docname=docname,
			commands=commands,
		)
		if command_status == "Success":
			_enqueue_backup_sync_if_needed(commands)


def _close_the_doc(start_time, key, console_dump, status, user):
	time_taken = frappe.utils.time.time() - start_time
	final_console_dump = ""
	console_dump = console_dump.split("\n\r")
	for i in console_dump:
		i = i.split("\r")
		final_console_dump += "\n" + i[-1]

	# For Webhook to trigger using cmd.save()
	cmd = frappe.get_doc("Bench Manager Command", key)
	cmd.console = final_console_dump
	cmd.status = status
	cmd.time_taken = time_taken
	cmd.save()

	publish_console(
		key,
		"{0}!\nThe operation took {1} seconds".format(status, time_taken),
		user=user,
	)


def _refresh(doctype, docname, commands):
	frappe.get_doc(doctype, docname).run_method("after_command", commands=commands)


def publish_progress(key, percent, stage, user, label=None):
	frappe.publish_realtime(
		event="bench_manager_command",
		message={"type": "progress", "percent": percent, "stage": stage, "label": label},
		room=key,
		user=user,
	)


def publish_console(key, message, user=None):
	if not key:
		return
	if isinstance(message, (dict, list)):
		message = json.dumps(message, ensure_ascii=False)
	message = str(message)
	frappe.publish_realtime(
		event="bench_manager_command",
		message="{0}\n".format(message),
		room=key,
		user=user,
	)


def normalize_site_config(site_name):
	site_config_path = os.path.join(
		frappe.utils.get_bench_path(), "sites", site_name, "site_config.json"
	)
	if not os.path.exists(site_config_path):
		return False

	with open(site_config_path, "r") as f:
		site_config = json.load(f)

	updated = False
	if not site_config.get("db_user") and site_config.get("db_name"):
		site_config["db_user"] = site_config.get("db_name")
		updated = True
	if not site_config.get("db_host"):
		site_config["db_host"] = frappe.conf.get("db_host") or "127.0.0.1"
		updated = True
	if not site_config.get("db_port"):
		site_config["db_port"] = frappe.conf.get("db_port") or 3306
		updated = True

	if updated:
		with open(site_config_path, "w") as f:
			json.dump(site_config, f, indent=4)
	return updated


def _run_single_command(command, command_doc, cwd, console_dump, user=None):
	return execute_bench_command(
		command=command,
		command_doc=command_doc,
		cwd=cwd,
		user=user,
		console_dump=console_dump,
	)


def _run_new_site_with_retry(
	command, command_doc, cwd, console_dump, user=None, retry_context=None
):
	retry_context = retry_context or {}
	max_attempts = 3
	for attempt in range(1, max_attempts + 1):
		publish_progress(command_doc.name, percent=10, stage="db-connect", user=user)
		publish_progress(command_doc.name, percent=30, stage="db-create", user=user)
		try:
			console_dump = _run_single_command(
				command, command_doc, cwd, console_dump, user=user
			)
		except Exception as error:
			if isinstance(error, CommandFailed):
				console_dump = error.console_dump
			error_text = "{}".format(error)
			if _should_retry_mariadb(error_text, console_dump) and attempt < max_attempts:
				publish_console(
					command_doc.name,
					"Retrying MariaDB connection (attempt {0}/{1})".format(
						attempt + 1, max_attempts
					),
					user=user,
				)
				_refresh_mariadb_grants(retry_context, command_doc.name, user)
				command = _swap_mariadb_login_scope(command, retry_context)
				time.sleep(random.randint(3, 5))
				continue
			if _should_retry_mariadb(error_text, console_dump):
				publish_console(
					command_doc.name,
					"MariaDB connection failed after retries.",
					user=user,
				)
			raise

		publish_progress(command_doc.name, percent=50, stage="install", user=user)
		return console_dump
	return console_dump


def _refresh_mariadb_grants(retry_context, key, user):
	host = retry_context.get("db_host") or "127.0.0.1"
	port = int(retry_context.get("db_port") or 3306)
	user_name = retry_context.get("db_user") or "root"
	password = retry_context.get("db_password")
	if not password:
		return
	try:
		connection = pymysql.connect(
			host=host, user=user_name, passwd=password, port=port, connect_timeout=5
		)
		with connection.cursor() as cursor:
			cursor.execute("FLUSH PRIVILEGES;")
		connection.commit()
		connection.close()
		publish_console(
			key,
			"Refreshed MariaDB privileges before retry.",
			user=user,
		)
	except Exception:
		publish_console(
			key,
			"Unable to refresh MariaDB privileges; retrying anyway.",
			user=user,
		)


def _swap_mariadb_login_scope(command, retry_context):
	if "--mariadb-user-host-login-scope" in command:
		scope = retry_context.get("login_scope") or "%"
		next_scope = "localhost" if scope == "%" else "%"
		retry_context["login_scope"] = next_scope
		return re.sub(
			r"--mariadb-user-host-login-scope=['\"]?[^\"' ]+['\"]?",
			"--mariadb-user-host-login-scope='{0}'".format(next_scope),
			command,
		)
	return "{command} --mariadb-user-host-login-scope='%'".format(command=command)


def _is_new_site_command(command):
	return command.strip().startswith("bench new-site ")


def _should_retry_mariadb(error_text, console_dump):
	error_blob = "{0}\n{1}".format(error_text, console_dump).lower()
	patterns = [
		"access denied for user",
		"host is not allowed",
		"access denied",
		"permission denied",
		"error 1045",
		"error 1130",
		"database exists",
		"already exists",
	]
	return any(pattern in error_blob for pattern in patterns)


@frappe.whitelist()
def verify_whitelisted_call():
	if "bench_manager" not in frappe.get_installed_apps():
		raise ValueError("This site does not have bench manager installed.")


def safe_decode(string, encoding="utf-8"):
	try:
		string = string.decode(encoding)
	except Exception:
		pass
	return string


def _is_backup_command(command):
	return " backup" in command and command.strip().startswith("bench ")


def _is_restore_command(command):
	return " restore" in command and command.strip().startswith("bench ")


def _publish_restore_stages(key, user):
	stages = [
		("validating backup", 10),
		("extracting", 30),
		("restoring database", 60),
		("restoring files", 80),
	]
	for stage, percent in stages:
		publish_progress(key, percent=percent, stage=stage, user=user)
		publish_console(key, "Restore stage: {0}".format(stage), user=user)


def _is_reinstall_command(command):
	return " reinstall" in command and command.strip().startswith("bench --site ")


def _get_site_name_from_command(command):
	match = re.search(r"--site\s+([^\s]+)", command)
	if match:
		return match.group(1)
	if _is_new_site_command(command):
		return command.strip().split(" ")[-1]
	return None


def _should_sync_backups(commands):
	triggers = [
		" backup",
		" restore",
		" drop-site",
	]
	return any(any(trigger in command for trigger in triggers) for command in commands)


def _enqueue_backup_sync_if_needed(commands):
	if not _should_sync_backups(commands):
		return
	try:
		frappe.enqueue(
			"bench_manager.bench_manager.doctype.bench_settings.bench_settings.sync_backups",
			queue="short",
		)
		if any(_is_backup_command(command) for command in commands):
			frappe.publish_realtime("Bench-Manager:refresh-backups")
	except Exception:
		frappe.log_error(
			title="Bench Manager Auto Sync",
			message="Failed to enqueue backup sync",
		)


def _run_command_with_lock_retry(command, command_doc, cwd, console_dump, user=None):
	site_name = _get_site_name_from_command(command)
	if not site_name or not (_is_reinstall_command(command) or _is_new_site_command(command)):
		return _run_single_command(command, command_doc, cwd, console_dump, user=user)

	max_attempts = 3
	for attempt in range(1, max_attempts + 1):
		try:
			return _run_single_command(command, command_doc, cwd, console_dump, user=user)
		except Exception as error:
			error_text = "{0}".format(error)
			if isinstance(error, CommandFailed):
				console_dump = error.console_dump
				error_text = "{0}\n{1}".format(error_text, console_dump)
			if _is_lock_timeout(error_text) and attempt < max_attempts:
				publish_console(
					command_doc.name,
					"LockTimeoutError: will retry in 5s (attempt {0}/{1})".format(
						attempt, max_attempts
					),
					user=user,
				)
				time.sleep(5)
				continue
			if _is_lock_timeout(error_text):
				lock_path = get_lock_path(site_name)
				publish_console(
					command_doc.name,
					"LockTimeoutError: lock at {0}. Check running bench processes.".format(
						lock_path
					),
					user=user,
				)
			raise
	return console_dump


def _is_lock_timeout(error_text):
	return "Failed to acquire lock: bench_new_site" in error_text or (
		"Failed to aquire lock: bench_new_site" in error_text
	)


def get_lock_path(site_name, lock_name="bench_new_site"):
	return os.path.join(
		frappe.utils.get_bench_path(), "sites", site_name, "locks", "{0}.lock".format(lock_name)
	)


def is_lock_stale(lock_path, stale_seconds=600):
	if not os.path.exists(lock_path):
		return False
	mtime = os.path.getmtime(lock_path)
	return (time.time() - mtime) > stale_seconds


def safe_remove_lock(lock_path):
	if not is_lock_stale(lock_path):
		return False
	try:
		os.remove(lock_path)
		frappe.log_error(
			title="Bench Manager Lock Cleanup",
			message="Removed stale lock: {0}".format(lock_path),
		)
		return True
	except OSError:
		frappe.log_error(
			title="Bench Manager Lock Cleanup Failed",
			message="Failed to remove lock: {0}".format(lock_path),
		)
		return False


def bench_process_holds_site_lock(site_name):
	try:
		result = run(["ps", "aux"], check=True, stdout=PIPE, stderr=PIPE, text=True)
	except CalledProcessError:
		return False
	processes = result.stdout
	if "bench new-site {0}".format(site_name) in processes:
		return True
	if "bench --site {0} reinstall".format(site_name) in processes:
		return True
	return False


def preflight_site_operation(site_name, key, operation_name):
	if not site_name:
		return
	lock_path = get_lock_path(site_name)
	lock_dir = os.path.dirname(lock_path)
	if not os.path.isdir(lock_dir):
		os.makedirs(lock_dir, exist_ok=True)

	if os.path.exists(lock_path):
		if bench_process_holds_site_lock(site_name):
			message = "Another bench operation is running for {0}.".format(site_name)
			publish_console(key, message)
			frappe.log_error(
				title="Bench Manager Lock Active",
				message="{0} ({1})".format(message, lock_path),
			)
			frappe.throw(message)
		if safe_remove_lock(lock_path):
			publish_console(key, "Stale lock detected, removing...")
		else:
			publish_console(
				key,
				"Lock file present and could not be removed: {0}".format(lock_path),
			)
			frappe.throw("Lock file present and could not be removed.")
	publish_console(key, "Lock OK for {0}".format(operation_name))
