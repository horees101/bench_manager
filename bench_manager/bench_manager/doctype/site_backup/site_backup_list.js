frappe.listview_settings['Site Backup'] = {
	onload(listview) {
		const siteFilter = listview.page.add_field({
			fieldname: 'site_name',
			label: __('Site'),
			fieldtype: 'Link',
			options: 'Site',
			change() {
				const value = siteFilter.get_value();
				if (value) {
					listview.filter_area.add([
						[listview.doctype, 'site_name', '=', value]
					]);
				}
			}
		});

		if (frappe.route_options && frappe.route_options.site_name) {
			listview.filter_area.add([
				[listview.doctype, 'site_name', '=', frappe.route_options.site_name]
			]);
			siteFilter.set_value(frappe.route_options.site_name);
			frappe.route_options = null;
		}
	}
};
