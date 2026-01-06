frappe.listview_settings['Site Backup'] = {
	onload(listview) {
		if (frappe.route_options && frappe.route_options.site_name) {
			listview.filter_area.add([
				[listview.doctype, 'site_name', '=', frappe.route_options.site_name]
			]);
			frappe.route_options = null;
		}
	}
};
