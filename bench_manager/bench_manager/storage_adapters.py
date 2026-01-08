# -*- coding: utf-8 -*-
# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import os
import posixpath
from abc import ABC, abstractmethod
from subprocess import PIPE, CalledProcessError, run

import boto3
import frappe


class BackupStorageAdapter(ABC):
	@abstractmethod
	def upload(self, file_path, site_name):
		pass

	@abstractmethod
	def delete(self, file_path, site_name):
		pass


class LocalFSAdapter(BackupStorageAdapter):
	def upload(self, file_path, site_name):
		return

	def delete(self, file_path, site_name):
		return


class S3Adapter(BackupStorageAdapter):
	def __init__(self, bucket, region=None, access_key=None, secret_key=None, prefix=None):
		self.bucket = bucket
		self.region = region
		self.access_key = access_key
		self.secret_key = secret_key
		self.prefix = (prefix or "").strip().strip("/")

	def upload(self, file_path, site_name):
		if not self.bucket:
			return
		client = self._get_client()
		key = self._build_key(site_name, os.path.basename(file_path))
		try:
			client.upload_file(file_path, self.bucket, key)
		except Exception:
			frappe.log_error(
				title="Bench Manager S3 Error",
				message="Failed to upload {0} to {1}".format(file_path, key),
			)

	def delete(self, file_path, site_name):
		if not self.bucket:
			return
		client = self._get_client()
		key = self._build_key(site_name, os.path.basename(file_path))
		try:
			client.delete_object(Bucket=self.bucket, Key=key)
		except Exception:
			frappe.log_error(
				title="Bench Manager S3 Error",
				message="Failed to delete {0} from {1}".format(file_path, key),
			)

	def _build_key(self, site_name, filename):
		parts = [part for part in [self.prefix, site_name, filename] if part]
		return "/".join(parts)

	def _get_client(self):
		kwargs = {}
		if self.region:
			kwargs["region_name"] = self.region
		if self.access_key and self.secret_key:
			kwargs["aws_access_key_id"] = self.access_key
			kwargs["aws_secret_access_key"] = self.secret_key
		return boto3.client("s3", **kwargs)


class GDriveAdapter(BackupStorageAdapter):
	def __init__(self, remote_name, remote_path_prefix=None):
		self.remote_name = (remote_name or "").strip()
		self.remote_path_prefix = (remote_path_prefix or "").strip().strip("/")

	def upload(self, file_path, site_name):
		remote_path = self._remote_path(site_name, os.path.basename(file_path))
		if not remote_path:
			return
		self._run_rclone(["copyto", file_path, remote_path])

	def delete(self, file_path, site_name):
		remote_path = self._remote_path(site_name, os.path.basename(file_path))
		if not remote_path:
			return
		self._run_rclone(["deletefile", remote_path])

	def _remote_path(self, site_name, filename):
		if not self.remote_name:
			return None
		parts = [part for part in [self.remote_path_prefix, site_name, filename] if part]
		remote_path = posixpath.join(*parts) if parts else ""
		return "{0}:{1}".format(self.remote_name, remote_path)

	def _run_rclone(self, args):
		command = ["rclone"] + args
		try:
			run(command, check=True, stdout=PIPE, stderr=PIPE)
		except CalledProcessError:
			frappe.log_error(
				title="Bench Manager GDrive Error",
				message="Rclone command failed: {0}".format(" ".join(command)),
			)
