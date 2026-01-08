frappe.listview_settings['Site Backup'] = {
	onload(listview) {
		const allSitesLabel = __('All Sites');
		const siteOptions = [allSitesLabel];
		const siteFilterMode = listview.page.add_field({
			fieldname: 'site_filter_mode',
			label: __('Filter'),
			fieldtype: 'Select',
			options: siteOptions,
			change() {
				const value = siteFilterMode.get_value();
				if (!value || value === allSitesLabel) {
					listview.filter_area.remove(listview.doctype, 'site_name');
					return;
				}
				listview.filter_area.add([
					[listview.doctype, 'site_name', '=', value]
				]);
			}
		});

		frappe.db.get_list('Site', { fields: ['name'], limit: 200 }).then((sites) => {
			(sites || []).forEach((site) => {
				siteOptions.push(site.name);
			});
			siteFilterMode.df.options = siteOptions;
			siteFilterMode.refresh();

			const routeSite = frappe.route_options && frappe.route_options.site_name;
			const defaultSite =
				routeSite ||
				frappe.boot.sitename ||
				frappe.boot.site_name ||
				frappe.boot.site;

			if (routeSite) {
				frappe.route_options = null;
			}

			if (defaultSite) {
				siteFilterMode.set_value(defaultSite);
				listview.filter_area.add([
					[listview.doctype, 'site_name', '=', defaultSite]
				]);
			} else {
				siteFilterMode.set_value(allSitesLabel);
			}
		});

		frappe.realtime.on('Bench-Manager:refresh-backups', () => {
			listview.refresh();
		});
	}
};
