frappe.pages['bench-health'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Bench Health'),
		single_column: true,
	});

	const state = {
		latest: null,
		logs: [],
	};

	const render = () => {
		const latest = state.latest || {};
		const summary = latest.summary || {};
		const perSite = latest.per_site || {};
		const overall = summary.overall_status || 'Unknown';
		const logRows = (state.logs || [])
			.map((log) => {
				return `<tr>
					<td>${frappe.datetime.str_to_user(log.creation)}</td>
					<td>${log.overall_status || ''}</td>
				</tr>`;
			})
			.join('');

		const siteRows = Object.keys(perSite)
			.map((site) => {
				const status = perSite[site].ok ? 'green' : 'red';
				return `<tr>
					<td>${site}</td>
					<td><span class="indicator ${status}">${perSite[site].ok ? __('Healthy') : __('Issues')}</span></td>
					<td><button class="btn btn-default btn-xs" data-site="${site}">${__('Repair Site')}</button></td>
				</tr>`;
			})
			.join('');

		page.main.html(`
			<div class="bench-health-summary">
				<div class="card">
					<div class="card-body">
						<h5>${__('Overall Status')}: ${overall}</h5>
						<div class="bench-health-actions" style="margin-top: 12px;">
							<button class="btn btn-primary btn-sm" data-action="run">${__('Run Diagnostics')}</button>
							<button class="btn btn-default btn-sm" data-action="repair-all">${__('Repair All')}</button>
						</div>
					</div>
				</div>
				<div class="card" style="margin-top: 12px;">
					<div class="card-body">
						<h5>${__('Site Health')}</h5>
						<table class="table table-bordered">
							<thead>
								<tr>
									<th>${__('Site')}</th>
									<th>${__('Status')}</th>
									<th>${__('Actions')}</th>
								</tr>
							</thead>
							<tbody>
								${siteRows || `<tr><td colspan="2">${__('No sites found')}</td></tr>`}
							</tbody>
						</table>
					</div>
				</div>
				<div class="card" style="margin-top: 12px;">
					<div class="card-body">
						<h5>${__('Last 20 Health Runs')}</h5>
						<table class="table table-bordered">
							<thead>
								<tr>
									<th>${__('Timestamp')}</th>
									<th>${__('Status')}</th>
								</tr>
							</thead>
							<tbody>
								${logRows || `<tr><td colspan="2">${__('No runs yet')}</td></tr>`}
							</tbody>
						</table>
					</div>
				</div>
			</div>
		`);

		page.main.find('[data-action="run"]').on('click', () => runDiagnostics());
		page.main.find('[data-action="repair-all"]').on('click', () => repairAll());
		page.main.find('[data-site]').on('click', (event) => {
			const site = event.currentTarget.getAttribute('data-site');
			repairSite(site);
		});
	};

	const refreshSnapshot = () => {
		frappe.call({
			method: 'bench_manager.bench_manager.doctype.bench_health.bench_health.get_health_snapshot',
			callback: (response) => {
				state.latest = response.message.latest;
				state.logs = response.message.logs || [];
				render();
			},
		});
	};

	const runDiagnostics = () => {
		const key = frappe.datetime.get_datetime_as_string();
		startConsoleDialog(key, () => {
			frappe.call({
				method: 'bench_manager.bench_manager.doctype.bench_health.bench_health.run_health_checks',
				args: { key },
				callback: () => refreshSnapshot(),
				error: () => refreshSnapshot(),
			});
		});
	};

	const repairAll = () => {
		const key = frappe.datetime.get_datetime_as_string();
		startConsoleDialog(key, () => {
			frappe.call({
				method: 'bench_manager.bench_manager.doctype.bench_health.bench_health.repair_all',
				args: { key },
				callback: () => refreshSnapshot(),
				error: () => refreshSnapshot(),
			});
		});
	};

	const repairSite = (site) => {
		const key = frappe.datetime.get_datetime_as_string();
		startConsoleDialog(key, () => {
			frappe.call({
				method: 'bench_manager.bench_manager.doctype.bench_health.bench_health.repair_site',
				args: { site_name: site, key },
				callback: () => refreshSnapshot(),
				error: () => refreshSnapshot(),
			});
		});
	};

	const startConsoleDialog = (key, action) => {
		const launch = () =>
			typeof window.console_dialog === 'function' ? window.console_dialog(key) : null;

		const dialog = launch();
		if (dialog) {
			action(dialog);
			return;
		}

		frappe.require('/assets/bench_manager/js/bench_manager.js', () => {
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

	refreshSnapshot();
};
