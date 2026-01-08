# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappé and contributors
# For license information, please see license.txt


import json
import os
import random
import re
import shlex
import time
from subprocess import PIPE, STDOUT, Popen
import frappe
import pymysql
from frappe.model.document import Document


class CommandFailed(Exception):
	def __init__(self, command, console_dump):
		super().__init__("Command failed: {command}".format(command=command))
		self.command = command
		self.console_dump = console_dump


def run_command(
	commands, doctype, key, cwd="..", docname=" ", after_command=None, retry_context=None
):
	verify_whitelisted_call()
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
	doc = frappe.get_doc(
		{
			"doctype": "Bench Manager Command",
			"key": key,
			"source": doctype + ": " + docname,
			"command": logged_command,
			"console": console_dump,
			"status": "Ongoing",
		}
	)
	doc.insert()
	frappe.db.commit()
	frappe.publish_realtime(
		key,
		"Executing Command:\n{logged_command}\n\n".format(logged_command=logged_command),
		user=user,
	)
	try:
		if doctype == "Site" and original_docname and original_docname.strip():
			normalize_site_config(original_docname)
		progress_context = (retry_context or {}).get("progress_context")
		for command in commands:
			if _is_new_site_command(command):
				console_dump = _run_new_site_with_retry(
					command,
					key,
					user,
					cwd,
					console_dump,
					retry_context=retry_context or {},
				)
				continue

			if progress_context == "new_site":
				if "install-app erpnext" in command:
					publish_progress(key, 70, "Installing ERPNext", user)
				elif " migrate" in command:
					publish_progress(key, 100, "Finalizing & migrations", user)

			console_dump = _run_single_command(command, key, user, cwd, console_dump)

		if progress_context == "new_site":
			publish_progress(key, 100, "Finalizing & migrations", user)

		_close_the_doc(start_time, key, console_dump, status="Success", user=user)
	except Exception as e:
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
		frappe.db.commit()
		# hack: frappe.db.commit() to make sure the log created is robust,
		# and the _refresh throws an error if the doc is deleted
		frappe.enqueue(
			"bench_manager.bench_manager.utils._refresh",
			doctype=doctype,
			docname=docname,
			commands=commands,
		)


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

	frappe.publish_realtime(
		key,
		"\n\n" + status + "!\nThe operation took " + str(time_taken) + " seconds",
		user=user,
	)


def _refresh(doctype, docname, commands):
	frappe.get_doc(doctype, docname).run_method("after_command", commands=commands)


def publish_progress(key, percent, label, user):
	frappe.publish_realtime(
		key,
		{"type": "progress", "percent": percent, "label": label},
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
		site_config["db_host"] = "127.0.0.1"
		updated = True
	if not site_config.get("db_port"):
		site_config["db_port"] = 3306
		updated = True

	if updated:
		with open(site_config_path, "w") as f:
			json.dump(site_config, f, indent=4)
	return updated


def _run_single_command(command, key, user, cwd, console_dump):
	terminal = Popen(
		shlex.split(command), stdin=PIPE, stdout=PIPE, stderr=STDOUT, cwd=cwd
	)
	for c in iter(lambda: safe_decode(terminal.stdout.read(1)), ""):
		frappe.publish_realtime(key, c, user=user)
		console_dump += str(c)

	if terminal.wait():
		raise CommandFailed(command, console_dump)
	return console_dump


def _run_new_site_with_retry(command, key, user, cwd, console_dump, retry_context=None):
	retry_context = retry_context or {}
	max_attempts = 3
	for attempt in range(1, max_attempts + 1):
		publish_progress(key, 10, "Validating DB connection", user)
		publish_progress(key, 30, "Creating site database", user)
		try:
			console_dump = _run_single_command(command, key, user, cwd, console_dump)
		except Exception as error:
			if isinstance(error, CommandFailed):
				console_dump = error.console_dump
			error_text = "{}".format(error)
			if _should_retry_mariadb(error_text, console_dump) and attempt < max_attempts:
				frappe.publish_realtime(
					key,
					"\nRetrying MariaDB connection (attempt {0}/{1})\n".format(
						attempt + 1, max_attempts
					),
					user=user,
				)
				_refresh_mariadb_grants(retry_context, key, user)
				command = _swap_mariadb_login_scope(command, retry_context)
				time.sleep(random.randint(3, 5))
				continue
			if _should_retry_mariadb(error_text, console_dump):
				frappe.publish_realtime(
					key,
					"\nMariaDB connection failed after retries.\n",
					user=user,
				)
			raise

		publish_progress(key, 50, "Installing Frappe", user)
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
		frappe.publish_realtime(
			key,
			"\nRefreshed MariaDB privileges before retry.\n",
			user=user,
		)
	except Exception:
		frappe.publish_realtime(
			key,
			"\nUnable to refresh MariaDB privileges; retrying anyway.\n",
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
