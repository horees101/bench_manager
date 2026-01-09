// Copyright (c) 2017, Frappe and contributors
// For license information, please see license.txt

const startConsoleDialog = (key, action) => {
	const launch = () =>
		typeof window.console_dialog === "function" ? window.console_dialog(key) : null;

	const dialog = launch();
	if (dialog) {
		action(dialog);
		return;
	}

	frappe.require("/assets/bench_manager/js/bench_manager.js", () => {
		const loaded = launch();
		if (loaded) {
			action(loaded);
			return;
		}
		frappe.msgprint(
			__('Socket.IO is down; console streaming unavailable. Check Bench Health dashboard.')
		);
		frappe.msgprint(__('Open Bench Manager Command list to view logs.'));
		action(null);
	});
};

const withSaveDisabled = (frm, action) => {
	frm.disable_save();
	const result = action();
	if (result && result.always) {
		result.always(() => frm.enable_save());
	} else {
		frm.enable_save();
	}
};

frappe.ui.form.on('Bench Settings', {
	onload: function(frm) {
		let site_config_fields = ["background_workers", "shallow_clone", "admin_password",
			"auto_email_id", "auto_update", "frappe_user", "global_help_setup",
			"gunicorn_workers", "github_username",
			"github_password", "mail_login", "mail_password", "mail_port", "mail_server",
			"use_tls", "rebase_on_pull", "redis_cache", "redis_queue", "redis_socketio",
			"restart_supervisor_on_update", "root_password", "serve_default_site",
			"socketio_port", "update_bench_on_update", "webserver_port", "developer_mode",
			"file_watcher_port"];
		site_config_fields.forEach(function(val){
			frm.toggle_display(val, frm.doc[val] != undefined);
		});
		frappe.call({
			method: 'bench_manager.bench_manager.doctype.bench_settings.bench_settings.enqueue_sync_backups',
			freeze: false
		});
	},
	refresh: function(frm) {
		frm.add_custom_button(__("Get App"), function(){
			var dialog = new frappe.ui.Dialog({
				title: 'App Name',
				fields: [
					{fieldname: 'app_name', fieldtype: 'Data', reqd:true, label: 'Name of the frappe repo hosted on github'}
				]
			});
			dialog.set_primary_action(__("Get App"), () => {
				let key = frappe.datetime.get_datetime_as_string();
				startConsoleDialog(key, () => {
					withSaveDisabled(frm, () => frm.call("console_command", {
						key: key,
						caller: 'get-app',
						app_name: dialog.fields_dict.app_name.value
					}, () => {
						dialog.hide();
					}));
				});
			});
			dialog.show();
		});
		frm.add_custom_button(__('New Site'), function(){
			frappe.call({
				method: 'bench_manager.bench_manager.doctype.site.site.pass_exists',
				args: {
					doctype: frm.doctype
				},
				btn: this,
				callback: function(r){
					var dialog = new frappe.ui.Dialog({
						fields: [
							{fieldname: 'site_name', fieldtype: 'Data', label: "Site Name", reqd: true},
							{fieldname: 'install_erpnext', fieldtype: 'Check', label: "Install ERPNext"},
							{
								fieldname: 'db_mode',
								fieldtype: 'Select',
								label: 'Database Mode',
								options: ['local', 'remote', 'clustered'],
								default: 'local',
								reqd: true
							},
							{
								fieldname: 'db_host',
								fieldtype: 'Data',
								label: 'DB Host',
								default: '127.0.0.1',
								depends_on: 'eval:doc.db_mode != "local"'
							},
							{
								fieldname: 'db_port',
								fieldtype: 'Int',
								label: 'DB Port',
								default: 3306,
								depends_on: 'eval:doc.db_mode != "local"'
							},
							{
								fieldname: 'db_root_user',
								fieldtype: 'Data',
								label: 'DB Root User',
								default: 'root',
								depends_on: 'eval:doc.db_mode != "local"'
							},
							{
								fieldname: 'db_root_password',
								fieldtype: 'Password',
								label: 'DB Root Password',
								reqd: true,
								depends_on: 'eval:doc.db_mode != "local"'
							},
							{fieldname: 'admin_password', fieldtype: 'Password',
								label: 'Administrator Password', reqd: r['message']['condition'][0] != 'T',
								default: (r['message']['admin_password'] ? r['message']['admin_password'] :'admin'),
								depends_on: `eval:${String(r['message']['condition'][0] != 'T')}`},
							{
								fieldname: 'mysql_password',
								fieldtype: 'Password',
								label: 'MariaDB Root Password',
								reqd: r['message']['condition'][1] != 'T',
								default: r['message']['root_password'],
								depends_on: `eval:${String(r['message']['condition'][1] != 'T')} && doc.db_mode == "local"`
							}
						],
					});
					dialog.set_primary_action(__("Create"), () => {
						let key = frappe.datetime.get_datetime_as_string();
						const site_name = (dialog.fields_dict.site_name.value || "").trim();
						if (!site_name) {
							frappe.msgprint(__('Please enter a site name.'));
							return;
						}
						let install_erpnext;
						if (dialog.fields_dict.install_erpnext.last_value != 1){
							install_erpnext = "false";
						} else {
							install_erpnext = "true";
						}
						const dbMode = dialog.fields_dict.db_mode.value || "local";
						if (dbMode !== "local") {
							if (!dialog.fields_dict.db_host.value) {
								frappe.msgprint(__('Please enter a database host.'));
								return;
							}
							if (!dialog.fields_dict.db_root_user.value) {
								frappe.msgprint(__('Please enter a database root user.'));
								return;
							}
							if (!dialog.fields_dict.db_root_password.value) {
								frappe.msgprint(__('Please enter a database root password.'));
								return;
							}
						}
						frappe.call({
							method: 'bench_manager.bench_manager.doctype.site.site.verify_password',
							args: {
								site_name: site_name,
								mysql_password: dialog.fields_dict.mysql_password.value,
								db_host: dialog.fields_dict.db_host.value,
								db_port: dialog.fields_dict.db_port.value,
								db_root_user: dialog.fields_dict.db_root_user.value,
								db_root_password: dialog.fields_dict.db_root_password.value
							},
							callback: function(r){
								if (r.message == "console"){
									startConsoleDialog(key, () => {
										withSaveDisabled(frm, () => frappe.call({
											method: 'bench_manager.bench_manager.doctype.site.site.create_site',
											args: {
												site_name: site_name,
												admin_password: dialog.fields_dict.admin_password.value,
												mysql_password: dialog.fields_dict.mysql_password.value,
												install_erpnext: install_erpnext,
												key: key,
												db_mode: dialog.fields_dict.db_mode.value,
												db_host: dialog.fields_dict.db_host.value,
												db_port: dialog.fields_dict.db_port.value,
												db_root_user: dialog.fields_dict.db_root_user.value,
												db_root_password: dialog.fields_dict.db_root_password.value
											},
											freeze: true,
											callback: function(response) {
												if (response.message && response.message.status) {
													frappe.show_alert({
														message: __('Site creation queued for {0}', [site_name]),
														indicator: 'green'
													});
												}
											},
											error: function(err) {
												frappe.msgprint(err.message || __('Unable to start site creation.'));
											}
										}));
										dialog.hide();
									});
								} 
							}
						});
					});
					dialog.show();
				}
			});
		});
		frm.add_custom_button(__("Update"), function(){
			let key = frappe.datetime.get_datetime_as_string();
			startConsoleDialog(key, () => {
				withSaveDisabled(frm, () => frm.call("console_command", {
					key: key,
					caller: "bench_update"
				}));
			});
		});
		frm.add_custom_button(__('Sync'), () => {
			withSaveDisabled(frm, () => frappe.call({
				method: 'bench_manager.bench_manager.doctype.bench_settings.bench_settings.sync_all'
			}));
		});
		frm.add_custom_button("Reload", () => {
			frappe.prompt([
	  {
		  label: 'Root Password',
		  fieldname: 'password',
		  fieldtype: 'Password'
	  },
		  ], (values) => {
			let key = frappe.datetime.get_datetime_as_string();
			startConsoleDialog(key, () => {
				withSaveDisabled(frm, () => frappe.call({
					method: "bench_manager.bench_manager.doctype.bench_settings.bench_settings.setup_and_restart_nginx",
					args: {
						"root_password": values.password,
						key
					},
					callback: function(r) {
						if (r.message && r.message.status === "queued") {
							frappe.show_alert({
								message: __('Queued reload and nginx restart'),
								indicator: 'green'
							});
						}
					}
				}));
			});
		  })
		});
	},
	allow_dropbox_access: function(frm) {
		if (frm.doc.app_access_key && frm.doc.app_secret_key) {
			withSaveDisabled(frm, () => frappe.call({
				method: "bench_manager.bench_manager.doctype.bench_settings.bench_settings.get_dropbox_authorize_url",
				freeze: true,
				callback: function(r) {
					if(!r.exc) {
						window.open(r.message.auth_url);
					}
				}
			}))
		}
		else if (frm.doc.__onload && frm.doc.__onload.dropbox_setup_via_site_config) {
			withSaveDisabled(frm, () => frappe.call({
				method: "bench_manager.bench_manager.doctype.bench_settings.bench_settings.get_redirect_url",
				freeze: true,
				callback: function(r) {
					if(!r.exc) {
						window.open(r.message.auth_url);
					}
				}
			}))
		}
		else {
			frappe.msgprint(__("Please enter values for App Access Key and App Secret Key"))
		}
	}
});
