frappe.pages["bench-manager"] = frappe.pages["bench-manager"] || {};

frappe.pages["bench-manager"].on_page_load = function () {
	if (frappe.bench_manager_backups_synced) {
		return;
	}

	frappe.bench_manager_backups_synced = true;
	frappe.call({
		method:
			"bench_manager.bench_manager.doctype.bench_settings.bench_settings.sync_backups_if_stale",
		args: {},
		freeze: false,
	});
};
