# -*- coding: utf-8 -*-
# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import os
import posixpath
from subprocess import PIPE, CalledProcessError, run

import frappe


class LocalAdapter:
	def upload_backup_set(self, site_name, file_paths):
		return

	def delete_backup_set(self, site_name, backup_prefix):
		return


class RcloneAdapter:
	def __init__(self, remote_name, path_prefix=None):
		self.remote_name = (remote_name or "").strip()
		self.path_prefix = (path_prefix or "").strip().strip("/")

	def upload_backup_set(self, site_name, file_paths):
		remote_site_path = self._remote_site_path(site_name)
		if not remote_site_path:
			return

		for file_path in file_paths:
			remote_file = posixpath.join(remote_site_path, os.path.basename(file_path))
			self._run_rclone(["copyto", file_path, remote_file])

	def delete_backup_set(self, site_name, backup_prefix):
		remote_site_path = self._remote_site_path(site_name)
		if not remote_site_path:
			return
		self._run_rclone(
			["delete", "--include", "{0}*".format(backup_prefix), remote_site_path]
		)

	def _remote_site_path(self, site_name):
		if not self.remote_name:
			return None
		if self.path_prefix:
			remote_path = posixpath.join(self.path_prefix, site_name)
		else:
			remote_path = site_name
		return "{0}:{1}".format(self.remote_name, remote_path)

	def _run_rclone(self, args):
		command = ["rclone"] + args
		try:
			run(command, check=True, stdout=PIPE, stderr=PIPE)
		except CalledProcessError:
			frappe.log_error(
				title="Bench Manager Rclone Error",
				message="Rclone command failed: {0}".format(" ".join(command)),
			)
